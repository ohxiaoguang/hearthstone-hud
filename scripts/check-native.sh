#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
file bin/hearthstone-hud-renderer | tee build/file.txt
readelf -h bin/hearthstone-hud-renderer | tee build/elf.txt
readelf --version-info bin/hearthstone-hud-renderer > build/symbols.txt
ldd bin/hearthstone-hud-renderer | tee build/ldd.txt
! grep -q 'not found' build/ldd.txt
python3 - <<'PY'
import re,pathlib,struct
header=pathlib.Path('bin/hearthstone-hud-renderer').read_bytes()[:64]
assert len(header)==64 and header[:7]==b'\x7fELF\x02\x01\x01', 'Expected ELF64 little endian'
assert struct.unpack_from('<H',header,18)[0]==62, 'Expected AMD x86-64'
assert struct.unpack_from('<H',header,16)[0] in (2,3), 'Expected executable or PIE'
print('ELF64 x86_64 executable verified')
versions=set(re.findall(r'GLIBC_(\d+)\.(\d+)',pathlib.Path('build/symbols.txt').read_text()))
assert versions, 'No glibc symbols detected'
assert max(tuple(map(int,v)) for v in versions)<=(2,31), versions
print('GLIBC baseline <= 2.31')
PY
