from statistics import mean
import math


def variables(data):
    result = {row['name']: row for row in data['variables']}
    if len(result) != len(data['variables']):
        raise ValueError('重复变量')
    for kind in ('required', 'forbidden'):
        for left, right in data['knowledge'][kind]:
            if left not in result or right not in result or left == right:
                raise ValueError('知识约束引用无效变量')
    return result


def baseline(data):
    definitions = variables(data)
    return {'variables': list(definitions), 'rows': len(data['observations']),
            'cohorts': sorted({row['cohort'] for row in data['observations']}),
            'missing': {name: sum(row.get(name) is None for row in data['observations']) for name in definitions},
            'knowledge': data['knowledge']}


def act(data, request):
    definitions = variables(data)
    if request.get('operation') != 'correlation':
        raise ValueError('未知探索操作')
    left, right = request.get('left'), request.get('right')
    if left not in definitions or right not in definitions or left == right:
        raise ValueError('请选择不同的已登记变量')
    cohort = request.get('cohort')
    pairs = [(row[left], row[right]) for row in data['observations']
             if row.get(left) is not None and row.get(right) is not None
             and (not cohort or row['cohort'] == cohort)]
    coefficient = None
    if len(pairs) >= 2:
        left_mean = mean(pair[0] for pair in pairs)
        right_mean = mean(pair[1] for pair in pairs)
        left_variation = sum((pair[0] - left_mean) ** 2 for pair in pairs)
        right_variation = sum((pair[1] - right_mean) ** 2 for pair in pairs)
        if left_variation > 0 and right_variation > 0:
            coefficient = sum((pair[0] - left_mean) * (pair[1] - right_mean) for pair in pairs)
            coefficient /= math.sqrt(left_variation * right_variation)
    return {'left': left, 'right': right, 'n': len(pairs), 'correlation': coefficient,
            'notice': '成对描述性相关，不代表因果方向'}
