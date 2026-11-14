import copy
import unittest
from app import domain
from app.service import load_study


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.data = load_study()
        self.request = {'operation': 'correlation', 'left': 'practice', 'right': 'score'}

    def test_exact_linear_correlation(self):
        data = copy.deepcopy(self.data)
        data['observations'] = [{'learner': str(index), 'cohort': 'a', 'practice': index, 'score': 2 * index}
                                for index in range(5)]
        result = domain.act(data, self.request)
        self.assertAlmostEqual(result['correlation'], 1)
        self.assertEqual(result['n'], 5)

    def test_constant_is_undefined(self):
        data = copy.deepcopy(self.data)
        for row in data['observations']:
            row['practice'] = 1
        self.assertIsNone(domain.act(data, self.request)['correlation'])

    def test_missing_records_not_filled_with_zero(self):
        data = copy.deepcopy(self.data)
        result = domain.act(data, self.request)
        data['observations'].append({'cohort': 'a', 'practice': None, 'score': 10})
        self.assertEqual(result, domain.act(data, self.request))


if __name__ == '__main__':
    unittest.main()
