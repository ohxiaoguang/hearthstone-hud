"""Release failures must never leave a stale successful-looking ZIP."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

class PackagingTests(unittest.TestCase):
    def test_missing_invalid_and_short_binary_remove_stale_release(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/package.py'
        for binary in (None, b'Mach-O is not Linux', b'\x7fELF\x02\x01'):
            with self.subTest(binary=binary), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root/'scripts').mkdir()
                shutil.copyfile(script, root/'scripts/package.py')
                (root/'package.json').write_text(json.dumps({'version':'0.1.0'}))
                for name in ['plugin.json','main.py','dist/index.js','assets/fonts/NotoSansCJKsc-Regular.otf','assets/test.png','LICENSE','licenses/Noto-OFL.txt']:
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test fixture')
                if binary is not None:
                    (root/'bin').mkdir();(root/'bin/hearthstone-hud-renderer').write_bytes(binary)
                out=root/'release/hearthstone-hud-0.1.0.zip'
                out.parent.mkdir();out.write_bytes(b'stale artifact')
                result=subprocess.run([sys.executable,str(root/'scripts/package.py')],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(out.exists())
                self.assertFalse(out.with_suffix('.zip.tmp').exists())
                self.assertNotIn('Traceback',result.stderr)
