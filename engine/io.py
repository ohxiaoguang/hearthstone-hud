"""Local atomic IPC and bounded, rotation-aware complete-line tailing."""
import json
import os
from pathlib import Path


def atomic_json(path, data):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Tail:
    def __init__(self):
        self.path = None
        self.identity = None
        self.offset = 0
        self.partial = b''
        self.anchor = b''
        self.generation = 0

    def read(self, path):
        path = Path(path)
        try:
            with path.open('rb') as f:
                st = os.fstat(f.fileno())
                identity = (st.st_dev, st.st_ino)
                f.seek(max(0, self.offset - len(self.anchor)))
                changed = f.read(len(self.anchor)) != self.anchor
                if path != self.path or identity != self.identity or st.st_size < self.offset or changed:
                    self.offset, self.partial = 0, b''
                    self.generation += 1
                self.path, self.identity = path, identity
                f.seek(self.offset)
                data = f.read(1024 * 1024)
                self.offset = f.tell()
                f.seek(max(0, self.offset - 128))
                self.anchor = f.read(min(128, self.offset))
        except FileNotFoundError:
            return []
        parts = (self.partial + data).split(b'\n')
        self.partial = parts.pop()
        if len(self.partial) > 1024 * 1024:
            self.partial = b''
        return [p.decode('utf-8', errors='replace').rstrip('\r') for p in parts]
