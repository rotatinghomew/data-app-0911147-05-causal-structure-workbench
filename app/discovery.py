"""同一观测集合上的结构候选探索。

一次探索固定在同一批记录上：选定人群与变量后做整行完整筛选，所有
条件独立检验共用该矩阵，不把不同观测集合的统计量拼进同一张图。输
出为与资料相容的结构候选（等价类）、每条关系的检验证据与知识依据、
方向未定边所需的额外假设，以及自助重抽样的稳定程度。结果供后续实
验设计讨论，不宣布任何变量必然导致另一变量。
"""

from itertools import combinations
import hashlib
import json
import math

import numpy as np

from . import domain


ALPHA_DEFAULT = 0.05
ALPHA_RANGE = (0.001, 0.5)
MAX_CONDITIONING_LIMIT = 4
BOOTSTRAP_LIMIT = 200
MIN_ROWS = 10
CANDIDATE_LIMIT = 24
ENUMERATION_EDGE_LIMIT = 10

SCOPE_NOTE = '结构候选用于后续实验设计讨论，不构成学生个人决策依据；本结果不宣布任何变量必然导致另一变量。'

ASSUMPTIONS = [
    '因果充分性未默认成立：所选变量之外可能存在未记录的共同原因，邻接关系可能反映潜在共同原因而非直接因果；'
    '只有额外接受“无未记录共同原因”时，有向边才可作因果解释。',
    '忠实性：假设总体中成立的独立关系能在样本检验中显现，样本检验不遗漏恰好成立的独立性。',
    '检验模型：Fisher z 偏相关，假设变量间关系近似线性、条件分布近似高斯。',
    '同一观测集合：本次全部检验共用同一批整行完整记录；更换人群或变量即构成新的观测集合，结果不可拼接。',
    '多重比较：逐检验使用同一显著性水平，未做多重比较校正；全部检验记录随图可查。',
]


class DiscoveryError(ValueError):
    """探索请求或资料不满足可解释分析的条件。"""


def _pair_key(left, right):
    return frozenset((left, right))


def _as_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise DiscoveryError('%s应为数值' % label)


def _as_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DiscoveryError('%s应为整数' % label)


def select_population(data, cohort, selected):
    """返回同一观测集合：指定人群内、所选变量整行完整的记录。"""
    rows = [row for row in data['observations'] if not cohort or row.get('cohort') == cohort]
    complete = []
    for row in rows:
        values = [row.get(name) for name in selected]
        if all(value is not None for value in values):
            complete.append((str(row.get('learner', len(complete))), [float(value) for value in values]))
    fingerprint = hashlib.sha256(json.dumps(
        {'cohort': cohort or 'all', 'variables': list(selected), 'rows': complete},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    matrix = (np.array([values for _, values in complete], dtype=float)
              if complete else np.zeros((0, len(selected))))
    population = {
        'cohort': cohort or 'all',
        'variables': list(selected),
        'rows_total': len(rows),
        'rows_used': len(complete),
        'fingerprint': fingerprint,
        'rule': '同一观测集合：所选人群内整行完整的记录，全部检验共用，不与其他集合拼接',
    }
    return population, matrix


def normalize_knowledge(raw, selected, known):
    """校验分析员提交的知识；引用未纳入变量的约束忽略并提示。"""
    knowledge = {'required': [], 'forbidden': [], 'temporal_order': []}
    notices = []
    raw = raw or {}
    if not isinstance(raw, dict):
        raise DiscoveryError('知识约束应为对象')
    for kind in knowledge:
        entries = raw.get(kind) or []
        if not isinstance(entries, list):
            raise DiscoveryError('知识约束应为列表')
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise DiscoveryError('知识约束条目应为二元组')
            left, right = str(entry[0]), str(entry[1])
            if left == right:
                raise DiscoveryError('知识约束两端不能是同一变量')
            if left not in known or right not in known:
                raise DiscoveryError('知识约束引用未登记变量：%s、%s' % (left, right))
            if left not in selected or right not in selected:
                notices.append('知识约束 %s→%s 涉及未纳入变量，本次已忽略' % (left, right))
                continue
            pair = [left, right]
            if pair not in knowledge[kind]:
                knowledge[kind].append(pair)
    return knowledge, notices


def _ci_test(corr, index, n, left, right, conditioning, alpha):
    """Fisher z 偏相关检验；退化或自由度不足时给出可解释记录。"""
    cond = tuple(sorted(conditioning))
    record = {'left': left, 'right': right, 'conditioning': list(cond), 'n': n,
              'r': None, 'p': None, 'decision': 'undefined', 'note': None}
    dof = n - len(cond) - 3
    if dof <= 0:
        record['note'] = '条件集相对样本量过大，自由度不足'
        return record
    cols = [index[left], index[right]] + [index[name] for name in cond]
    sub = corr[np.ix_(cols, cols)]
    if float(np.linalg.det(sub)) < 1e-10:
        record['note'] = '相关矩阵退化，无法计算偏相关'
        return record
    precision = np.linalg.inv(sub)
    scale = float(precision[0, 0] * precision[1, 1])
    if scale <= 0:
        record['note'] = '相关矩阵退化，无法计算偏相关'
        return record
    r = min(1.0, max(-1.0, -float(precision[0, 1]) / math.sqrt(scale)))
    if r in (1.0, -1.0):
        p = 0.0
    else:
        z = math.sqrt(dof) * abs(0.5 * math.log((1 + r) / (1 - r)))
        p = math.erfc(z / math.sqrt(2))
    record['r'] = r
    record['p'] = p
    record['decision'] = 'independent' if p > alpha else 'dependent'
    return record


def _skeleton(names, corr, index, n, alpha, max_cond):
    """PC-stable 骨架：同层先算邻域再统一删边，顺序无关、可复现。"""
    adjacent = {name: set(names) - {name} for name in names}
    sepsets = {}
    tests = []
    level = 0
    while level <= max_cond:
        pairs = sorted((left, right) for left in names for right in adjacent[left] if left < right)
        if not pairs:
            break
        testable = False
        removable = []
        for left, right in pairs:
            if any(entry[0] == left and entry[1] == right for entry in removable):
                continue
            for base_name in (left, right):
                base = sorted(adjacent[base_name] - {left, right})
                if len(base) < level:
                    continue
                testable = True
                for cond in combinations(base, level):
                    record = _ci_test(corr, index, n, left, right, cond, alpha)
                    tests.append(record)
                    if record['decision'] == 'independent':
                        removable.append((left, right, list(cond)))
                        break
                if any(entry[0] == left and entry[1] == right for entry in removable):
                    break
        for left, right, cond in removable:
            adjacent[left].discard(right)
            adjacent[right].discard(left)
            sepsets[_pair_key(left, right)] = cond
        level += 1
        if not testable:
            break
    unique_tests = []
    seen = set()
    for record in tests:
        key = (record['left'], record['right'], tuple(record['conditioning']))
        if key not in seen:
            seen.add(key)
            unique_tests.append(record)
    return adjacent, sepsets, unique_tests


def _collider_triples(names, adjacent, sepsets):
    colliders = set()
    for center in names:
        for left, right in combinations(sorted(adjacent[center]), 2):
            if right in adjacent[left]:
                continue
            sepset = sepsets.get(_pair_key(left, right))
            if sepset is not None and center not in sepset:
                colliders.add((left, center, right))
    return colliders


def _vstructures(names, adjacent, sepsets):
    directed = {}
    conflicts = []
    for left, center, right in sorted(_collider_triples(names, adjacent, sepsets)):
        for source in (left, right):
            if (center, source) in directed:
                conflicts.append({'kind': 'orientation_clash', 'pair': sorted([source, center]),
                                  'detail': '不同碰撞点证据给出相反方向'})
                continue
            reason = {'kind': 'collider',
                      'detail': 'v 结构：%s 与 %s 的分离集不含 %s' % (left, right, center)}
            directed.setdefault((source, center), []).append(reason)
    return directed, conflicts


def _undirected_pairs(names, adjacent, directed):
    pairs = []
    for left in names:
        for right in sorted(adjacent[left]):
            if left < right and (left, right) not in directed and (right, left) not in directed:
                pairs.append((left, right))
    return pairs


def _meek(names, directed, adjacent):
    """Meek 规则 R1–R3 传播定向，直到不动点。"""
    changed = True
    while changed:
        changed = False
        additions = []
        for left, right in _undirected_pairs(names, adjacent, directed):
            for x, y in ((left, right), (right, left)):
                reason = None
                for c in sorted(adjacent[x]):
                    if c != y and (c, x) in directed and y not in adjacent[c]:
                        reason = {'kind': 'meek', 'rule': 1,
                                  'detail': '%s→%s 且 %s 与 %s 不相邻' % (c, x, c, y)}
                        break
                if reason is None:
                    for c in sorted(adjacent[x]):
                        if (x, c) in directed and (c, y) in directed:
                            reason = {'kind': 'meek', 'rule': 2,
                                      'detail': '%s→%s→%s 已定向' % (x, c, y)}
                            break
                if reason is None:
                    middles = [c for c in sorted(adjacent[x])
                               if c != y and (c, y) in directed
                               and (x, c) not in directed and (c, x) not in directed]
                    for c, d in combinations(middles, 2):
                        if d not in adjacent[c]:
                            reason = {'kind': 'meek', 'rule': 3,
                                      'detail': '%s→%s 与 %s→%s 且 %s 与 %s 不相邻'
                                                % (c, y, d, y, c, d)}
                            break
                if reason is not None:
                    additions.append((x, y, reason))
                    break
        for x, y, reason in additions:
            if (x, y) not in directed and (y, x) not in directed:
                directed[(x, y)] = [reason]
                changed = True
    return directed


def _cyclic_required(required):
    """返回处于有向环上的 required 约束及一条示例环。"""
    edges = {a: set() for a, _ in required}
    for a, b in required:
        edges.setdefault(a, set()).add(b)
        edges.setdefault(b, set())

    def reaches(start, target):
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(edges.get(node, ()))
        return False

    cyclic = {(a, b) for a, b in required if reaches(b, a)}
    example = None
    if cyclic:
        start = sorted(cyclic)[0][0]

        def find_cycle(anchor, current, trail, visited):
            for nxt in sorted(edges.get(current, ())):
                if nxt == anchor and len(trail) > 1:
                    return trail + [anchor]
                if nxt in visited:
                    continue
                found = find_cycle(anchor, nxt, trail + [nxt], visited | {nxt})
                if found:
                    return found
            return None

        example = find_cycle(start, start, [start], {start})
    return cyclic, example


def _apply_knowledge(names, directed, adjacent, knowledge):
    """应用分析员提交的知识：required 为硬方向，temporal/forbidden 排除方向。"""
    conflicts = []
    required = [tuple(pair) for pair in knowledge['required']]
    cyclic, example = _cyclic_required(required)
    if cyclic:
        detail = '知识约束形成有向环'
        if example:
            detail += '：' + '→'.join(example)
        conflicts.append({'kind': 'knowledge_cycle',
                          'pairs': sorted([list(pair) for pair in cyclic]), 'detail': detail})
        required = [pair for pair in required if pair not in cyclic]
    exclusions = []
    for a, b in knowledge['forbidden']:
        exclusions.append((a, b, '流程限制禁止 %s→%s' % (a, b)))
    for a, b in knowledge['temporal_order']:
        exclusions.append((b, a, '时间先后：%s 不晚于 %s，排除 %s→%s' % (a, b, b, a)))
    for a, b in sorted(required):
        if b not in adjacent[a]:
            conflicts.append({'kind': 'required_missing', 'pair': [a, b],
                              'detail': '流程限制要求 %s→%s，但当前证据下两者不相邻' % (a, b)})
            continue
        if (b, a) in directed:
            conflicts.append({'kind': 'knowledge_clash', 'pair': [a, b],
                              'detail': '数据定向 %s→%s 与必需方向冲突' % (b, a)})
            continue
        reason = {'kind': 'knowledge', 'source': 'required',
                  'detail': '流程限制（必需方向）：%s→%s' % (a, b)}
        directed.setdefault((a, b), []).append(reason)
    for x, y, detail in sorted(exclusions):
        if y not in adjacent[x]:
            continue
        if (x, y) in directed:
            conflicts.append({'kind': 'knowledge_clash', 'pair': [x, y],
                              'detail': '数据定向 %s→%s 与被排除方向冲突' % (x, y)})
            continue
        reason = {'kind': 'knowledge', 'source': 'exclusion', 'detail': detail}
        directed.setdefault((y, x), []).append(reason)
    return conflicts


def _discover_structure(corr, names, n, alpha, max_cond, knowledge):
    index = {name: position for position, name in enumerate(names)}
    adjacent, sepsets, tests = _skeleton(names, corr, index, n, alpha, max_cond)
    colliders = _collider_triples(names, adjacent, sepsets)
    directed, conflicts = _vstructures(names, adjacent, sepsets)
    _meek(names, directed, adjacent)
    conflicts.extend(_apply_knowledge(names, directed, adjacent, knowledge))
    _meek(names, directed, adjacent)
    return adjacent, directed, sepsets, colliders, tests, conflicts


def _is_acyclic(names, arrows):
    outgoing = {name: set() for name in names}
    for a, b in arrows:
        outgoing[a].add(b)
    remaining = set(names)
    while remaining:
        sinks = [name for name in remaining if not (outgoing[name] & remaining)]
        if not sinks:
            return False
        remaining.difference_update(sinks)
    return True


def _candidates(names, adjacent, directed, colliders, limit=CANDIDATE_LIMIT):
    """枚举等价类中与知识相容的候选 DAG（不新增碰撞点、无有向环）。"""
    undirected = _undirected_pairs(names, adjacent, directed)
    note = None
    if len(undirected) > ENUMERATION_EDGE_LIMIT:
        return None, '方向未定边超过 %d 条，仅展示等价类，不逐一列举候选' % ENUMERATION_EDGE_LIMIT
    unshielded = {}
    for center in names:
        for left, right in combinations(sorted(adjacent[center]), 2):
            if right not in adjacent[left]:
                unshielded[(left, center, right)] = (left, center, right) in colliders
    candidates = []
    truncated = False
    for mask in range(2 ** len(undirected)):
        arrows = set(directed)
        for position, (left, right) in enumerate(undirected):
            arrows.add((left, right) if mask >> position & 1 == 0 else (right, left))
        if not _is_acyclic(names, arrows):
            continue
        consistent = True
        for (left, center, right), was_collider in unshielded.items():
            is_collider = (left, center) in arrows and (right, center) in arrows
            if is_collider != was_collider:
                consistent = False
                break
        if not consistent:
            continue
        candidates.append(sorted('%s→%s' % arrow for arrow in arrows))
        if len(candidates) >= limit:
            truncated = True
            break
    if truncated:
        note = '候选较多，仅列出前 %d 个' % limit
    return candidates, note


def _stability(matrix, names, alpha, max_cond, knowledge, replicates, seed):
    """自助重抽样：同一流程在重采样记录上重复，统计邻接与方向频率。"""
    n = matrix.shape[0]
    rng = np.random.default_rng(seed)
    tally = {}
    used = 0
    for _ in range(replicates):
        sample = matrix[rng.integers(0, n, n)]
        with np.errstate(invalid='ignore', divide='ignore'):
            corr = np.corrcoef(sample, rowvar=False)
        if not np.isfinite(corr).all():
            continue
        used += 1
        adjacent, directed, _, _, _, _ = _discover_structure(corr, names, n, alpha, max_cond, knowledge)
        for position, left in enumerate(names):
            for right in names[position + 1:]:
                key = (left, right)
                entry = tally.setdefault(key, {'present': 0, 'left_to_right': 0,
                                               'right_to_left': 0, 'undirected': 0, 'conflict': 0})
                if right not in adjacent[left]:
                    continue
                entry['present'] += 1
                forward, backward = (left, right) in directed, (right, left) in directed
                if forward and backward:
                    entry['conflict'] += 1
                elif forward:
                    entry['left_to_right'] += 1
                elif backward:
                    entry['right_to_left'] += 1
                else:
                    entry['undirected'] += 1
    stability = {}
    for (left, right), entry in sorted(tally.items()):
        if not entry['present']:
            continue
        stability[left + ' ↔ ' + right] = {
            'adjacency': entry['present'] / used,
            'left_to_right': entry['left_to_right'] / used,
            'right_to_left': entry['right_to_left'] / used,
            'undirected': entry['undirected'] / used,
            'conflict': entry['conflict'] / used,
        }
    return {'replicates_requested': replicates, 'replicates_used': used, 'pairs': stability}


def _edge_records(names, adjacent, directed, tests, conflicts):
    contested = {tuple(sorted(conflict['pair'])) for conflict in conflicts
                 if conflict.get('kind') == 'orientation_clash' and conflict.get('pair')}
    edges = []
    for left, right in _all_adjacent_pairs(names, adjacent):
        reasons = []
        arrows = []
        for source, target in ((left, right), (right, left)):
            if (source, target) in directed:
                arrows.append((source, target))
                reasons.extend(directed[(source, target)])
        pair_tests = [record for record in tests
                      if _pair_key(record['left'], record['right']) == _pair_key(left, right)]
        if len(arrows) == 2:
            status, direction = 'conflict', None
        elif len(arrows) == 1:
            status, direction = 'directed', list(arrows[0])
        else:
            status, direction = 'undirected', None
        edge = {'left': left, 'right': right, 'status': status, 'direction': direction,
                'oriented_by': reasons, 'evidence': pair_tests, 'needs': None,
                'contested': (left, right) in contested}
        if status == 'undirected':
            edge['needs'] = [
                {'direction': [left, right],
                 'assumption': ('要定为 %s→%s，需额外假设或新证据：例如补充该方向的流程知识、'
                                '更细的时间信息或干预/准实验数据；当前等价类内两方向与资料同样相容'
                                % (left, right))},
                {'direction': [right, left],
                 'assumption': ('要定为 %s→%s，需额外假设或新证据：例如补充该方向的流程知识、'
                                '更细的时间信息或干预/准实验数据；当前等价类内两方向与资料同样相容'
                                % (right, left))},
            ]
        edges.append(edge)
    return edges


def _all_adjacent_pairs(names, adjacent):
    pairs = []
    for left in names:
        for right in sorted(adjacent[left]):
            if left < right:
                pairs.append((left, right))
    return pairs


def explore(data, request):
    """执行一次结构候选探索；request 为分析员在页面上提交的完整选择。"""
    if not isinstance(request, dict):
        raise DiscoveryError('请求应为对象')
    definitions = domain.variables(data)
    known = set(definitions)
    selected = request.get('variables')
    if not isinstance(selected, list) or len(selected) < 2:
        raise DiscoveryError('请至少选择两个已登记变量')
    selected = [str(name) for name in selected]
    if len(set(selected)) != len(selected):
        raise DiscoveryError('变量选择重复')
    unknown = [name for name in selected if name not in known]
    if unknown:
        raise DiscoveryError('变量未登记：' + '、'.join(unknown))
    cohorts = {row.get('cohort') for row in data['observations']}
    cohort = request.get('cohort') or None
    if cohort is not None:
        cohort = str(cohort)
        if cohort not in cohorts:
            raise DiscoveryError('人群未登记：%s' % cohort)
    alpha = _as_float(request.get('alpha', ALPHA_DEFAULT), '显著性水平')
    if not ALPHA_RANGE[0] <= alpha <= ALPHA_RANGE[1]:
        raise DiscoveryError('显著性水平超出可解释范围')
    max_cond = _as_int(request.get('max_conditioning', 3), '最大条件集')
    if not 0 <= max_cond <= MAX_CONDITIONING_LIMIT:
        raise DiscoveryError('最大条件集超出支持范围 0..%d' % MAX_CONDITIONING_LIMIT)
    replicates = _as_int(request.get('bootstrap', 50), '重抽样次数')
    if not 0 <= replicates <= BOOTSTRAP_LIMIT:
        raise DiscoveryError('重抽样次数超出支持范围 0..%d' % BOOTSTRAP_LIMIT)
    knowledge, notices = normalize_knowledge(request.get('knowledge'), selected, known)

    population, matrix = select_population(data, cohort, selected)
    result = {
        'status': 'ok',
        'scope': SCOPE_NOTE,
        'population': population,
        'parameters': {
            'alpha': alpha,
            'max_conditioning': max_cond,
            'bootstrap': replicates,
            'ci_test': 'Fisher z 偏相关（线性、近似高斯假设）',
            'multiple_testing': '逐检验使用同一显著性水平，未做多重比较校正；全部检验记录随图可查',
            'orientation': 'v 结构 + Meek 规则 + 分析员提交知识',
        },
        'assumptions': list(ASSUMPTIONS),
        'notices': notices,
        'knowledge_used': knowledge,
        'conflicts': [],
        'edges': [],
        'removed': [],
        'candidates': {'list': [], 'note': None},
        'stability': None,
        'tests': [],
    }
    if population['rows_used'] < MIN_ROWS:
        result['status'] = 'insufficient'
        result['notices'].append(
            '该观测集合整行完整记录仅 %d 条（最少 %d 条），不足以给出可解释检验'
            % (population['rows_used'], MIN_ROWS))
        return result
    usable = []
    dropped = []
    for position, name in enumerate(selected):
        if float(np.std(matrix[:, position])) <= 1e-12:
            dropped.append(name)
        else:
            usable.append(name)
    if dropped:
        result['notices'].append(
            '变量 %s 在该观测集合内为常数，无法参与独立性检验，本次已排除' % '、'.join(dropped))
    if len(usable) < 2:
        result['status'] = 'insufficient'
        result['notices'].append('可用于结构探索的变量不足两个')
        return result
    if dropped:
        population, matrix = select_population(data, cohort, usable)
        result['population'] = population
        result['notices'].append('观测集合随可用变量更新为：' + '、'.join(usable))

    corr = np.corrcoef(matrix, rowvar=False)
    adjacent, directed, sepsets, colliders, tests, conflicts = _discover_structure(
        corr, usable, population['rows_used'], alpha, max_cond, knowledge)
    result['conflicts'] = conflicts
    result['tests'] = tests
    result['edges'] = _edge_records(usable, adjacent, directed, tests, conflicts)
    for pair, cond in sorted(sepsets.items(), key=lambda item: sorted(item[0])):
        left, right = sorted(pair)
        result['removed'].append({
            'left': left, 'right': right, 'sepset': cond,
            'evidence': [record for record in tests
                         if _pair_key(record['left'], record['right']) == pair],
        })
    candidates, note = _candidates(usable, adjacent, directed, colliders)
    result['candidates'] = {'list': candidates or [], 'note': note}
    if replicates:
        seed = int(hashlib.sha256(json.dumps(
            {'fingerprint': population['fingerprint'], 'alpha': alpha,
             'max_conditioning': max_cond, 'knowledge': knowledge},
            sort_keys=True).encode()).hexdigest()[:8], 16)
        result['stability'] = _stability(matrix, usable, alpha, max_cond, knowledge, replicates, seed)
    return result
