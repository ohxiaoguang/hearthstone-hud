"""Verify the final installed layout in a fresh isolated Python process."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def verify(archive):
    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(archive) as z:
        assert z.testzip() is None, 'Corrupt ZIP'
        names = set(z.namelist())
        required = ['main.py', 'plugin.json', 'dist/index.js',
                    'py_modules/engine/__init__.py', 'py_modules/engine/io.py',
                    'py_modules/engine/power.py', 'assets/certs/cacert.pem', 'licenses/certifi-MPL-2.0.txt', 'py_modules/engine/cards.py', 'py_modules/engine/tls.py', 'py_modules/engine/images.py', 'py_modules/engine/diagnostics.py', 'py_modules/engine/tracker.py', 'py_modules/engine/discovery.py', 'py_modules/engine/proton.py', 'py_modules/engine/logconfig.py', 'py_modules/engine/deckstring.py', 'scripts/diagnose-logs.py', 'bin/hearthstone-hud-renderer']
        for name in required:
            assert 'hearthstone-hud/' + name in names, 'Missing: ' + name
        assert not any(n.startswith('hearthstone-hud/engine/') for n in names), 'Old root engine layout'
        for name in names:
            path = Path(name)
            assert not path.is_absolute() and '..' not in path.parts, 'Unsafe ZIP path'
        z.extractall(folder)
        plugin = Path(folder) / 'hearthstone-hud'
        # -I excludes cwd/PYTHONPATH; -S excludes site-packages. Only the
        # installed py_modules is appended, exactly as Decky does. Decky's
        # injected module is represented by an empty module for import only.
        code = '''
import importlib.util, pathlib, sys, types
plugin = pathlib.Path(sys.argv[1])
sys.path.append(str(plugin / 'py_modules'))
sys.modules['decky'] = types.ModuleType('decky')
import engine.io, engine.power
for module in (engine.io, engine.power):
    assert plugin / 'py_modules' in pathlib.Path(module.__file__).parents
spec = importlib.util.spec_from_file_location('_', plugin / 'main.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.Plugin
print('Installed ZIP: engine.io, engine.power and main.py import successfully')
'''
        subprocess.run([sys.executable, '-I', '-S', '-c', code, str(plugin)],
                       cwd=folder, check=True)
        print(json.dumps({'zip': str(archive), 'installed_python_imports': 'passed'}))


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
