from datetime import datetime, timezone
from pathlib import Path
import copy
import json
import os
import threading
import uuid


class NoteStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'notes.json'
        self.lock = threading.Lock()

    def _read(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding='utf-8'))

    def list(self):
        with self.lock:
            return copy.deepcopy(self._read())

    def append(self, text, selection):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError('批注应为一至两千字')
        if not isinstance(selection, dict):
            raise ValueError('批注选择必须为对象')
        entry = {'id': uuid.uuid4().hex, 'text': text.strip(), 'selection': copy.deepcopy(selection),
                 'created_at': datetime.now(timezone.utc).isoformat()}
        with self.lock:
            entries = self._read()
            entries.append(entry)
            self._write(entries)
        return entry

    def _write(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(entries, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class GraphStore(NoteStore):
    """保存结构候选图快照，供后续实验设计讨论，不用于学生个人决策。"""

    LIMIT = 100
    PURPOSE = '供后续实验设计讨论，不构成学生个人决策依据'

    def __init__(self, directory):
        super().__init__(directory)
        self.path = Path(directory) / 'graphs.json'

    def append(self, run, note=None):
        if not isinstance(run, dict):
            raise ValueError('图快照应为对象')
        population = run.get('population')
        if not isinstance(population, dict) or not isinstance(population.get('fingerprint'), str):
            raise ValueError('图快照缺少观测集合指纹')
        if not isinstance(run.get('edges'), list) or not isinstance(run.get('parameters'), dict):
            raise ValueError('图快照缺少边或参数记录')
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ValueError('图备注应不超过两千字')
        edges = run['edges']
        entry = {
            'id': uuid.uuid4().hex,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'purpose': self.PURPOSE,
            'population': copy.deepcopy(population),
            'summary': {
                'edges': len(edges),
                'directed': sum(edge.get('status') == 'directed' for edge in edges),
                'undirected': sum(edge.get('status') == 'undirected' for edge in edges),
                'conflicts': len(run.get('conflicts') or []),
            },
            'note': (note or '').strip() or None,
            'run': copy.deepcopy(run),
        }
        with self.lock:
            entries = self._read()
            if len(entries) >= self.LIMIT:
                raise ValueError('保存的图已达上限 %d 份' % self.LIMIT)
            entries.append(entry)
            self._write(entries)
        return entry
