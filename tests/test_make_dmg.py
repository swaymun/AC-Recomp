"""Tests for scripts/make_dmg.py: bundle layout, disk-image layout, and (when the host has them) a Swift compile
smoke test and a real hdiutil image of a tiny fake app. No game data; nothing is uploaded."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import make_dmg as md  # noqa: E402


def fake_kit(path):
    for rel in ('tools/acr_build.py', 'tools/acr_setup_cmd.py', 'README.md'):
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(rel + '\n')
    (path / 'tools/__pycache__').mkdir()
    (path / 'tools/__pycache__/x.pyc').write_bytes(b'\0')
    return path


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.kit = fake_kit(self.tmp / 'kit')

    def test_bundle_layout_without_compiling(self):
        app = md.build_app(self.kit, self.tmp / md.APP_NAME, 'v0.1.0', sign=False, compile=False)
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleExecutable'], md.EXECUTABLE)
        self.assertEqual(info['CFBundleShortVersionString'], '0.1.0')
        self.assertEqual(info['CFBundleIconFile'], 'AppIcon')
        kit = app / 'Contents/Resources/kit'
        self.assertTrue((kit / 'tools/acr_setup_cmd.py').is_file())
        self.assertFalse((kit / 'tools/__pycache__').exists())
        self.assertRegex((kit / 'KIT_VERSION').read_text(), r'^v0\.1\.0\+[0-9a-f]{16}\n$')

    def test_kit_digest_tracks_content(self):
        a = md.kit_digest(self.kit)
        (self.kit / 'README.md').write_text('changed\n')
        self.assertNotEqual(a, md.kit_digest(self.kit))

    def test_rejects_a_folder_that_is_not_a_kit(self):
        (self.tmp / 'empty').mkdir()
        with self.assertRaises(md.DmgError):
            md.build_app(self.tmp / 'empty', self.tmp / md.APP_NAME, compile=False, sign=False)

    def test_image_layout(self):
        app = md.build_app(self.kit, self.tmp / 'build' / md.APP_NAME, sign=False, compile=False)
        stage = md.layout(app, self.tmp / 'stage')
        self.assertEqual(sorted(os.listdir(stage)), ['AC-Recomp Setup.app', 'Applications', 'Read Me First.txt'])
        self.assertEqual(os.readlink(stage / 'Applications'), '/Applications')
        readme = (stage / 'Read Me First.txt').read_text()
        self.assertIn('xattr -dr com.apple.quarantine', readme)
        self.assertIn('NO game code', readme)
        md.layout(app, stage)  # idempotent
        self.assertEqual(md.dmg_name('v0.1.0'), 'AC-Recomp-v0.1.0-macos.dmg')

    def test_create_image_command(self):
        calls = []
        orig = md.run
        md.run = lambda cmd, **kw: calls.append([str(c) for c in cmd]) or Path(cmd[-1]).write_text('img')
        self.addCleanup(setattr, md, 'run', orig)
        target = md.create_image(self.tmp / 'stage', self.tmp / 'out' / 'x.dmg')
        self.assertEqual(target.read_text(), 'img')
        cmd = calls[0]
        self.assertEqual(cmd[:2], ['hdiutil', 'create'])
        self.assertEqual(cmd[cmd.index('-format') + 1], 'UDZO')
        self.assertEqual(cmd[cmd.index('-srcfolder') + 1], str(self.tmp / 'stage'))

    @unittest.skipUnless(shutil.which('hdiutil') and sys.platform == 'darwin', 'needs hdiutil')
    def test_real_image_of_a_fake_app(self):
        app = md.build_app(self.kit, self.tmp / 'build' / md.APP_NAME, sign=False, compile=False)
        stage = md.layout(app, self.tmp / 'stage')
        target = md.create_image(stage, self.tmp / 'out' / md.dmg_name('v0.0.1'))
        out = subprocess.run(['hdiutil', 'imageinfo', target], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('UDZO', out.stdout)


@unittest.skipUnless(shutil.which('swiftc') and sys.platform == 'darwin', 'needs swiftc')
class SwiftSmokeTest(unittest.TestCase):
    def test_setup_app_compiles(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        md.compile_swift(ROOT / 'ports/macos-setup', tmp / md.EXECUTABLE)
        self.assertTrue(os.access(tmp / md.EXECUTABLE, os.X_OK))


if __name__ == '__main__':
    unittest.main()
