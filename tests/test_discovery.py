import json
import unittest
from pathlib import Path

from app import discovery
from app.service import load_study

CASES = {case['name']: case['study'] for case in json.loads(
    (Path(__file__).resolve().parents[1] / 'data/analysis-cases.json').read_text(encoding='utf-8'))}


def run(study, **overrides):
    request = {'variables': [variable['name'] for variable in study['variables']],
               'knowledge': study.get('knowledge'), 'bootstrap': 0}
    request.update(overrides)
    return discovery.explore(study, request)


def skeleton(result):
    return {tuple(sorted((edge['left'], edge['right']))) for edge in result['edges']}


class StructureCaseTests(unittest.TestCase):
    def test_chain_stays_equivalence_class(self):
        result = run(CASES['chain'])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(skeleton(result),
                         {('practice', 'preparation'), ('practice', 'score')})
        self.assertTrue(all(edge['status'] == 'undirected' for edge in result['edges']))
        self.assertEqual(len(result['candidates']['list']), 3)
        for edge in result['edges']:
            self.assertTrue(edge['needs'])
            self.assertIn('额外假设', edge['needs'][0]['assumption'])

    def test_fork_is_observationally_equivalent_to_chain(self):
        result = run(CASES['fork'])
        self.assertEqual(skeleton(result),
                         {('practice', 'preparation'), ('preparation', 'score')})
        self.assertTrue(all(edge['status'] == 'undirected' for edge in result['edges']))
        self.assertEqual(len(result['candidates']['list']), 3)

    def test_collider_oriented_by_separation_evidence(self):
        result = run(CASES['collider'], alpha=0.01)
        self.assertEqual(skeleton(result),
                         {('preparation', 'score'), ('practice', 'score')})
        for edge in result['edges']:
            self.assertEqual(edge['status'], 'directed')
            self.assertEqual(edge['direction'][1], 'score')
            self.assertIn('collider', {reason['kind'] for reason in edge['oriented_by']})
        self.assertEqual(result['candidates']['list'],
                         [['practice→score', 'preparation→score']])

    def test_collider_not_forced_at_looser_alpha(self):
        result = run(CASES['collider'], alpha=0.05)
        self.assertTrue(all(edge['status'] == 'undirected' for edge in result['edges']))
        self.assertGreater(len(result['candidates']['list']), 1)

    def test_latent_common_cause_keeps_sufficiency_assumption_visible(self):
        result = run(CASES['latent'])
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(any('共同原因' in assumption for assumption in result['assumptions']))
        for edge in result['edges']:
            if edge['status'] == 'directed':
                self.assertTrue(edge['oriented_by'])

    def test_knowledge_cycle_reported_not_silently_applied(self):
        result = run(CASES['knowledge_cycle'])
        kinds = {conflict['kind'] for conflict in result['conflicts']}
        self.assertIn('knowledge_cycle', kinds)
        cycle = next(conflict for conflict in result['conflicts']
                     if conflict['kind'] == 'knowledge_cycle')
        self.assertIn(['practice', 'score'], cycle['pairs'])
        self.assertIn(['score', 'practice'], cycle['pairs'])

    def test_constant_column_excluded_with_notice(self):
        study = json.loads(json.dumps(CASES['chain']))
        study['variables'].append({'name': 'constant', 'type': 'continuous', 'time': None})
        for row in study['observations']:
            row['constant'] = 1.5
        result = run(study, variables=['preparation', 'practice', 'score', 'constant'])
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(any('常数' in notice for notice in result['notices']))
        self.assertNotIn('constant', result['population']['variables'])

    def test_independent_variables_yield_empty_skeleton(self):
        study = json.loads(json.dumps(CASES['chain']))
        import random
        rng = random.Random(20261115)
        for row in study['observations']:
            row['preparation'] = rng.gauss(0, 1)
            row['practice'] = rng.gauss(0, 1)
            row['score'] = rng.gauss(0, 1)
        result = run(study, alpha=0.01)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['edges'], [])
        self.assertEqual(len(result['removed']), 3)


class PopulationConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.data = load_study()
        self.variables = ['preparation', 'practice', 'feedback', 'score']

    def test_single_observation_set_per_run(self):
        result = run(self.data, variables=self.variables, knowledge={})
        self.assertEqual({test['n'] for test in result['tests']},
                         {result['population']['rows_used']})
        self.assertEqual(result['population']['rows_used'], 225)

    def test_fingerprint_changes_with_population(self):
        fingerprints = set()
        for cohort in (None, 'a', 'b'):
            result = run(self.data, variables=self.variables, cohort=cohort, knowledge={})
            fingerprints.add(result['population']['fingerprint'])
            self.assertEqual({test['n'] for test in result['tests']},
                             {result['population']['rows_used']})
        self.assertEqual(len(fingerprints), 3)

    def test_fingerprint_changes_with_variable_selection(self):
        full = run(self.data, variables=self.variables, knowledge={})
        reduced = run(self.data, variables=['preparation', 'practice', 'score'], knowledge={})
        self.assertNotEqual(full['population']['fingerprint'],
                            reduced['population']['fingerprint'])

    def test_insufficient_rows_is_interpretable(self):
        study = json.loads(json.dumps(CASES['chain']))
        study['observations'] = study['observations'][:5]
        result = run(study)
        self.assertEqual(result['status'], 'insufficient')
        self.assertEqual(result['edges'], [])
        self.assertTrue(result['notices'])


class KnowledgeOrientationTests(unittest.TestCase):
    def test_temporal_knowledge_orients_and_is_visible(self):
        result = run(CASES['chain'],
                     knowledge={'temporal_order': [['preparation', 'practice']],
                                'required': [], 'forbidden': []})
        edge = next(edge for edge in result['edges']
                    if {edge['left'], edge['right']} == {'preparation', 'practice'})
        self.assertEqual(edge['status'], 'directed')
        self.assertEqual(edge['direction'], ['preparation', 'practice'])
        sources = {(reason['kind'], reason.get('source')) for reason in edge['oriented_by']}
        self.assertIn(('knowledge', 'exclusion'), sources)
        other = next(candidate for candidate in result['edges'] if candidate is not edge)
        self.assertEqual(other['status'], 'directed')
        self.assertEqual(other['direction'], ['practice', 'score'])
        propagated = {(reason['kind'], reason.get('rule')) for reason in other['oriented_by']}
        self.assertIn(('meek', 1), propagated)

    def test_forbidden_direction_conflict_is_reported(self):
        result = run(CASES['collider'], alpha=0.01,
                     knowledge={'temporal_order': [], 'required': [],
                                'forbidden': [['preparation', 'score']]})
        kinds = {conflict['kind'] for conflict in result['conflicts']}
        self.assertIn('knowledge_clash', kinds)

    def test_unknown_variable_rejected(self):
        with self.assertRaises(discovery.DiscoveryError):
            run(CASES['chain'], variables=['preparation', 'ghost'])
        with self.assertRaises(discovery.DiscoveryError):
            run(CASES['chain'], knowledge={'required': [['preparation', 'ghost']],
                                           'forbidden': [], 'temporal_order': []})

    def test_knowledge_on_excluded_variable_dropped_with_notice(self):
        result = run(CASES['chain'], variables=['preparation', 'practice'],
                     knowledge={'temporal_order': [['preparation', 'score']],
                                'required': [], 'forbidden': []})
        self.assertTrue(any('未纳入变量' in notice for notice in result['notices']))


class StabilityTests(unittest.TestCase):
    def test_bootstrap_reports_frequencies(self):
        result = run(CASES['chain'], bootstrap=50)
        stability = result['stability']
        self.assertEqual(stability['replicates_used'], 50)
        adjacent = stability['pairs']['practice ↔ score']
        self.assertGreaterEqual(adjacent['adjacency'], 0.8)
        for entry in stability['pairs'].values():
            for value in entry.values():
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 1)

    def test_bootstrap_is_reproducible(self):
        first = run(CASES['chain'], bootstrap=30)
        second = run(CASES['chain'], bootstrap=30)
        self.assertEqual(first['stability'], second['stability'])


if __name__ == '__main__':
    unittest.main()
