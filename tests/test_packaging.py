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
                for name in ['plugin.json','main.py','dist/index.js','assets/fonts/NotoSansCJKsc-Regular.otf','assets/test.png','LICENSE','licenses/Noto-OFL.txt','engine/__init__.py','engine/io.py','engine/power.py','engine/tracker.py','engine/cards.py','engine/images.py','engine/diagnostics.py','engine/discovery.py','engine/proton.py','engine/logconfig.py','engine/deckstring.py','scripts/diagnose-logs.py']:
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

    def test_final_zip_installed_imports_and_old_layout_rejected(self):
        import importlib.util
        import zipfile
        source = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('verify_zip',source/'scripts/verify-decky-zip.py')
        verifier = importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ['scripts/package.py','main.py','engine/__init__.py','engine/io.py','engine/power.py','engine/tracker.py','engine/cards.py','engine/images.py','engine/diagnostics.py','engine/discovery.py','engine/proton.py','engine/logconfig.py','engine/deckstring.py','scripts/diagnose-logs.py']:
                dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,dest)
            (root/'package.json').write_text(json.dumps({'version':'0.1.1'}))
            for name in ['plugin.json','dist/index.js','assets/fonts/NotoSansCJKsc-Regular.otf','assets/test.png','LICENSE','licenses/Noto-OFL.txt','README.md']:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test fixture')
            # A header fixture only tests archive layout, never a published ELF.
            p=root/'bin/hearthstone-hud-renderer';p.parent.mkdir()
            header=bytearray(64);header[:6]=b'\x7fELF\x02\x01';header[18]=62;p.write_bytes(header)
            subprocess.run([sys.executable,str(root/'scripts/package.py')],check=True,capture_output=True)
            archive=root/'release/hearthstone-hud-0.1.1.zip'
            verifier.verify(archive)
            old=root/'old-layout.zip'
            with zipfile.ZipFile(archive) as src, zipfile.ZipFile(old,'w') as dst:
                for entry in src.infolist():
                    dst.writestr(entry.filename.replace('/py_modules/engine/','/engine/'),src.read(entry))
            with self.assertRaisesRegex(AssertionError,'Missing: py_modules'):
                verifier.verify(old)
