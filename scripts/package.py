"""Fail closed: source-only archives are never represented as installable plugins."""
from pathlib import Path
import json
import struct
import zipfile
root = Path(__file__).resolve().parent.parent
binary = root / 'bin/hearthstone-hud-renderer'
version = json.loads((root/'package.json').read_text())['version']
out = root/'release'/f'hearthstone-hud-{version}.zip'
tmp = out.with_suffix('.zip.tmp')
# A failed attempt must not leave a stale or partially written install ZIP.
out.unlink(missing_ok=True)
tmp.unlink(missing_ok=True)
required = ['plugin.json','package.json','main.py','dist/index.js','bin/hearthstone-hud-renderer','assets/fonts/NotoSansCJKsc-Regular.otf','assets/test.png','LICENSE','licenses/Noto-OFL.txt','engine/__init__.py','engine/io.py','engine/power.py','engine/tracker.py','engine/discovery.py','engine/proton.py','engine/logconfig.py','engine/cards.py','engine/images.py','engine/diagnostics.py','engine/deckstring.py','scripts/diagnose-logs.py']
for name in required:
    if not (root/name).is_file():
        raise SystemExit('缺少发布文件：'+name)
header = binary.read_bytes()[:20]
if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H',header[18:20])[0] != 62:
    raise SystemExit('拒绝打包：渲染器必须是 Linux x86_64 ELF')
out.parent.mkdir(exist_ok=True)
paths = [root/name for name in ['main.py','plugin.json','package.json','LICENSE','README.md','scripts/diagnose-logs.py']]
for folder in ['engine','dist','bin','assets','licenses','docs']:
    paths += [p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p) and p.name != '.gitkeep']
with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(paths):
        relative = p.relative_to(root)
        if relative.parts[0] == 'engine':
            relative = Path('py_modules') / relative
        info = zipfile.ZipInfo('hearthstone-hud/'+relative.as_posix(), (2026,1,1,0,0,0))
        info.external_attr = (0o100755 if p==binary else 0o100644)<<16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info,p.read_bytes())
tmp.replace(out)
print(out)
