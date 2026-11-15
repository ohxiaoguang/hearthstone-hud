"""Bounded log discovery. Never walk home or replay inactive old sessions."""
from . import i18n
import os
import time
from pathlib import Path


def discover(game_dir, manual='', now=None, max_age=300):
    now = time.time() if now is None else now
    roots = [Path(manual).expanduser()] if manual else [Path(game_dir)/'Logs', Path(game_dir)/'logs']
    found, errors = [], []
    visited = 0
    for root in roots:
        if root.is_file():
            candidates = [p for p in root.parent.iterdir() if p.name.lower() in ('power.log','decks.log','arena.log')]
        else:
            candidates = []
            if not root.exists():
                errors.append(str(root)+': '+i18n.t('log.missing_dir'))
                continue
            def onerror(exc):
                errors.append(str(exc))
            for folder, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
                visited += 1
                depth = len(Path(folder).relative_to(root).parts)
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink()) if depth < 6 and visited < 1024 else []
                for name in files:
                    if name.lower() in ('power.log', 'decks.log','arena.log'):
                        candidates.append(Path(folder)/name)
                if visited >= 1024:
                    errors.append(i18n.t('log.scan_limit'))
                    break
        for path in candidates:
            try:
                st = path.stat()
                if path.is_file():
                    found.append(dict(path=str(path), kind=path.name.lower(), mtime=st.st_mtime,
                                      size=st.st_size, active=now-st.st_mtime <= max_age))
            except OSError as exc:
                errors.append(str(exc))
    powers = [f for f in found if f['kind']=='power.log']
    selected = max(powers, key=lambda f:f['mtime'], default=None)
    decks = next((f for f in found if selected and f['kind']=='decks.log' and Path(f['path']).parent==Path(selected['path']).parent),None)
    arena = next((f for f in found if selected and f['kind']=='arena.log' and Path(f['path']).parent==Path(selected['path']).parent),None)
    return dict(roots=[str(r) for r in roots], power=selected, decks=decks, arena=arena,
                files=sorted(found,key=lambda f:f['mtime'],reverse=True)[:12], errors=errors,
                visited=visited, read_state=i18n.t('log.readable') if selected and selected['active'] else i18n.t('log.waiting_new_log') if selected else i18n.t('log.power_not_found'))


def gamescope_status(proc=Path('/proc')):
    """(detected, localized status text). The boolean never depends on the text."""
    errors = 0
    for comm in proc.glob('[0-9]*/comm'):
        try:
            name = comm.read_text().strip()
            if name == 'gamescope' or name.startswith('gamescope-'):
                return True, i18n.t('gamescope.detected',name=name)
            # Some wrappers use a different comm; inspect executable symlink only.
            exe = (comm.parent/'exe').resolve().name
            if exe == 'gamescope' or exe.startswith('gamescope-'):
                return True, i18n.t('gamescope.detected',name=exe)
        except OSError:
            errors += 1
    return False, i18n.t('gamescope.unknown') + (i18n.t('gamescope.partial') if errors else '')


class LogClock:
    def __init__(self,path,mtime):
        import re
        from datetime import datetime
        m=re.search(r'Hearthstone_(\d{4})_(\d{2})_(\d{2})',str(path))
        self.day=datetime(*map(int,m.groups())).date() if m else datetime.fromtimestamp(mtime).date()
        self.last=''

    def timestamp(self,time_of_day):
        from datetime import datetime,timedelta
        if self.last.startswith('23:') and time_of_day.startswith('00:'):
            self.day+=timedelta(days=1)
        self.last=time_of_day
        return datetime.fromisoformat(self.day.isoformat()+'T'+time_of_day[:15])
