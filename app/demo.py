from pathlib import Path
from urllib.request import Request, urlopen
import json
import tempfile
import threading

from .service import create_server


def main():
    root = Path(__file__).resolve().parents[1]
    request = json.loads((root / 'data/default-action.json').read_text())
    with tempfile.TemporaryDirectory() as directory:
        server = create_server(state_dir=directory)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            print('本地产品实时运行：' + base)
            for route in ('/health', '/api/summary'):
                with urlopen(base + route, timeout=5) as response:
                    print(route, json.dumps(json.load(response), ensure_ascii=False, indent=2))
            operation = Request(base + '/api/action', json.dumps(request).encode(), {'Content-Type': 'application/json'})
            with urlopen(operation, timeout=5) as response:
                print('当前操作', json.dumps(json.load(response), ensure_ascii=False, indent=2))
            exploration = {'variables': ['preparation', 'practice', 'feedback', 'score'],
                           'knowledge': {'temporal_order': [['preparation', 'practice']],
                                         'required': [], 'forbidden': [['score', 'preparation']]},
                           'bootstrap': 30}
            structure = Request(base + '/api/discovery', json.dumps(exploration).encode(),
                                {'Content-Type': 'application/json'})
            with urlopen(structure, timeout=30) as response:
                result = json.load(response)
            print('结构候选探索（实际响应摘要）')
            print(' 观测集合', json.dumps(result['population'], ensure_ascii=False))
            print(' 边', json.dumps([(edge['left'], edge['right'], edge['status'], edge['direction'])
                                    for edge in result['edges']], ensure_ascii=False))
            print(' 冲突', json.dumps(result['conflicts'], ensure_ascii=False))
            print(' 候选数', len(result['candidates']['list']),
                  '稳定程度变量对', sorted((result['stability'] or {}).get('pairs', {})))
            print('运行结束；上述为当前版本的实际响应。')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
