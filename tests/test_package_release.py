"""Tests for scripts/package_release.py on synthetic Git repositories (and on this checkout's HEAD when it has the
release files). No game data is involved; nothing is uploaded."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import package_release as pr  # noqa: E402


def git(*args):
    return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True).stdout.strip()


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / 'repo'
        files = {name: f'{name}\n' for name in pr.FIXED}
        files.update({
            'tools/acr_build.py': 'import os\nimport prepare_runtime as prep\nfrom tools import helper\n',
            'tools/prepare_runtime.py': 'import import_owned_dump as inventory\n',
            'tools/import_owned_dump.py': 'import json\n',
            'tools/astral_shader_full_inventory.py': 'import inventory_astral_pkz as pkz\n',
            'tools/inventory_astral_pkz.py': '',
            'tools/helper.py': '',
            'tools/unrelated.py': 'import acr_build\n',
            'runtime/patches/series.macos': '# order\na.patch\n',
            'runtime/patches/a.patch': 'diff\n',
            'runtime/patches/b.patch': 'diff\n',
            'runtime/patches/a.NOTICE': 'notice\n',
            'assets/launcher/OFL.txt': 'ofl\n',
            'docs/OTHER.md': 'not shipped\n',
        })
        self.files = files
        self.commit(files)
        (self.repo / 'assets/launcher/font.ttf').write_bytes(b'\0\1\0\0binary')
        git('-C', self.repo, 'add', '-A')
        git('-C', self.repo, 'commit', '-qm', 'font')

    def commit(self, files):
        if not self.repo.exists():
            self.repo.mkdir()
            git('init', '-q', self.repo)
            git('-C', self.repo, 'config', 'user.email', 'test@example.com')
            git('-C', self.repo, 'config', 'user.name', 'Test')
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        git('-C', self.repo, 'add', '-A')
        git('-C', self.repo, 'commit', '-qm', 'x')

    def test_zip_holds_exactly_the_release_members(self):
        target, staged = pr.package('v0.1.0-preview', self.tmp / 'dist', self.repo)
        self.assertEqual(target.name, 'AC-Recomp-v0.1.0-preview-macos.zip')
        with zipfile.ZipFile(target) as z:
            names = z.namelist()
            top = 'AC-Recomp-v0.1.0-preview/'
            self.assertTrue(all(n.startswith(top) for n in names))
            rel = {n[len(top):] for n in names}
            mode = z.getinfo(top + 'tools/acr_build.py').external_attr >> 16
        self.assertIn('README-FIRST.txt', rel)
        self.assertNotIn('release/README-FIRST.txt', rel)
        for want in ('tools/acr_build.py', 'tools/prepare_runtime.py', 'tools/import_owned_dump.py',
                     'tools/helper.py', 'tools/inventory_astral_pkz.py', 'runtime/patches/a.patch', 'runtime/patches/a.NOTICE',
                     'runtime/patches/series.macos', 'assets/launcher/font.ttf', 'LICENSE'):
            self.assertIn(want, rel)
        for unwanted in ('tools/unrelated.py', 'runtime/patches/b.patch', 'docs/OTHER.md'):
            self.assertNotIn(unwanted, rel)
        self.assertTrue(mode & 0o111)
        self.assertEqual(sorted(rel), staged)

    def test_uncommitted_changes_are_not_packaged(self):
        (self.repo / 'tools/acr_build.py').write_text('import os\nimport prepare_runtime\nimport secret\n')
        (self.repo / 'tools/secret.py').write_text('x\n')
        _, staged = pr.package('v0.1.0', self.tmp / 'dist', self.repo)
        self.assertNotIn('tools/secret.py', staged)

    def test_missing_member_and_binary_text_are_refused(self):
        self.commit({'runtime/patches/series.macos': 'a.patch\nmissing.patch\n'})
        with self.assertRaises(pr.PackageError) as e:
            pr.package('v0.1.0', self.tmp / 'dist', self.repo)
        self.assertIn('runtime/patches/missing.patch', str(e.exception))
        self.commit({'runtime/patches/series.macos': 'a.patch\n'})
        (self.repo / 'docs/BUILDING.md').write_bytes(b'text\0more')
        git('-C', self.repo, 'commit', '-qam', 'nul')
        with self.assertRaises(pr.PackageError) as e:
            pr.package('v0.1.0', self.tmp / 'dist', self.repo)
        self.assertIn('docs/BUILDING.md: binary file', str(e.exception))

    def test_game_file_types_are_refused(self):
        self.commit({'runtime/patches/series.macos': 'a.patch\n', 'assets/launcher/x.spv': 'not really\n'})
        with self.assertRaises(pr.PackageError) as e:
            pr.package('v0.1.0', self.tmp / 'dist', self.repo)
        self.assertIn('forbidden file type .spv', str(e.exception))

    def test_bad_version(self):
        with self.assertRaises(pr.PackageError):
            pr.package('latest', self.tmp / 'dist', self.repo)

    @unittest.skipUnless((ROOT / 'scripts/export_public.py').is_file(), 'private exporter not present')
    def test_this_repository_head(self):
        listed = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', 'HEAD'],
                                capture_output=True, text=True).stdout.split()
        if 'tools/acr_build.py' not in listed or 'release/README-FIRST.txt' not in listed:
            self.skipTest('release files not committed yet')
        target, staged = pr.package('v0.1.0-preview', self.tmp / 'dist', ROOT)
        self.assertIn('tools/acr_build.py', staged)
        self.assertIn('tools/astral_shader_full_inventory.py', staged)
        self.assertIn('tools/inventory_astral_pkz.py', staged)
        self.assertIn('tools/extract_control_metadata.py', staged)
        self.assertIn('tools/cnmt_metadata.py', staged)
        self.assertFalse(any(s.startswith(('scripts/', 'tests/', 'public/')) for s in staged))
        self.assertNotIn('tools/extract_shared_fonts.py', staged)


if __name__ == '__main__':
    unittest.main()
