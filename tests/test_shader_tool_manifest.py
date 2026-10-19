"""Offline boundary tests: temporary Git repositories and synthetic bytecode only."""
import base64
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/prepare_shader_tools.py'
spec = importlib.util.spec_from_file_location('shader_tools', SCRIPT)
shader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shader)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.repo / '.gitignore').write_text('.local/\nprivate/\n')
        (self.repo / 'original.txt').write_text('original\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.root = self.repo / '.local/extracted/group'
        self.root.mkdir(parents=True)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def fixture(self):
        code = b'\0' * 0x100 + b'\x0f\0\x07\0\0\0\0\xe3'
        ctrl = bytearray(0x758)
        ctrl[0x708:0x70c] = (0x100).to_bytes(4, 'little')
        h = hashlib.sha1(code).hexdigest()[:16]
        (self.root / 'code.bin').write_bytes(code)
        (self.root / 'ctrl.bin').write_bytes(ctrl)
        row = ['synthetic', 'compute', '0', str(len(code)), '0', str(len(ctrl)),
               '0x100', '8', '0', '0', h, 'code.bin', 'ctrl.bin']
        self.write_manifest(row)
        return row

    def write_manifest(self, row):
        with (self.root / 'manifest.tsv').open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(shader.HEADER)
            writer.writerow(row)

    def test_cli_manifest_and_private_output(self):
        self.fixture()
        result = subprocess.run([sys.executable, str(SCRIPT), 'check-manifest',
                                 '--repo', str(self.repo), '--input', str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'stages': 1})
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_private_paths_reject_tracked_and_symlink_escape(self):
        with self.assertRaises(ValueError):
            shader.private_path(self.repo, self.repo / 'tools/out')
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.repo / '.local/escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            shader.private_path(self.repo, self.repo / '.local/escape/output')
        tracked = self.repo / '.local/tracked'
        tracked.write_text('x')
        self.git('add', '-f', str(tracked))
        with self.assertRaises(ValueError):
            shader.private_path(self.repo, tracked)

    def test_git_pin_rejects_wrong_head_and_modified_source(self):
        head = self.git('rev-parse', 'HEAD')
        shader.verify_pin(self.repo, head)
        with self.assertRaises(ValueError):
            shader.verify_pin(self.repo, '0' * 40)
        (self.repo / 'injected.cs').write_text('untrusted compile source')
        with self.assertRaisesRegex(ValueError, 'untracked'):
            shader.verify_pin(self.repo, head)
        (self.repo / 'injected.cs').unlink()
        (self.repo / 'original.txt').write_text('changed')
        with self.assertRaises(ValueError):
            shader.verify_pin(self.repo, head)

    def test_manifest_missing_or_empty_is_failure(self):
        with self.assertRaisesRegex(ValueError, 'PKZ'):
            shader.validate_manifest(self.repo, self.root)
        (self.root / 'manifest.tsv').write_text('\t'.join(shader.HEADER) + '\n')
        with self.assertRaisesRegex(ValueError, 'empty'):
            shader.validate_manifest(self.repo, self.root)

    def test_manifest_traversal_and_symlink_are_failure(self):
        row = self.fixture()
        copied = self.root.parent / 'code.bin'
        copied.write_bytes((self.root / 'code.bin').read_bytes())
        row[11] = '../code.bin'
        self.write_manifest(row)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            shader.validate_manifest(self.repo, self.root)
        (self.root / 'code.bin').unlink()
        (self.root / 'code.bin').symlink_to(copied)
        row[11] = 'code.bin'
        self.write_manifest(row)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            shader.validate_manifest(self.repo, self.root)

    def test_manifest_hash_size_and_control_mismatch(self):
        row = self.fixture()
        (self.root / 'code.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            shader.validate_manifest(self.repo, self.root)
        row = self.fixture()
        row[5] = '1'
        self.write_manifest(row)
        with self.assertRaisesRegex(ValueError, 'size'):
            shader.validate_manifest(self.repo, self.root)
        row = self.fixture()
        ctrl = bytearray((self.root / 'ctrl.bin').read_bytes())
        ctrl[0x708:0x70c] = (0xffff).to_bytes(4, 'little')
        (self.root / 'ctrl.bin').write_bytes(ctrl)
        with self.assertRaisesRegex(ValueError, 'start'):
            shader.validate_manifest(self.repo, self.root)

    def test_unsafe_hash_and_schema_are_failure(self):
        row = self.fixture()
        row[10] = '../../outside'
        self.write_manifest(row)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            shader.validate_manifest(self.repo, self.root)
        (self.root / 'manifest.tsv').write_text('code\tctrl\nx\ty\n')
        with self.assertRaisesRegex(ValueError, 'schema'):
            shader.validate_manifest(self.repo, self.root)

    def test_lock_rejects_changed_pin(self):
        lock = {'references': [{'name': 'SuperMarioWonderRecomp', 'revision': shader.WONDER}],
                'dependencies': [{'name': 'Ryubing', 'revision': shader.RYUBING}]}
        path = self.repo / 'dependencies.lock'
        path.write_text(json.dumps(lock))
        shader.verify_lock(self.repo)
        lock['dependencies'][0]['revision'] = 'floating'
        path.write_text(json.dumps(lock))
        with self.assertRaises(ValueError):
            shader.verify_lock(self.repo)

    def test_package_actual_archive_hash_and_source_are_checked(self):
        wonder = self.repo / '.local/wonder'
        assets = wonder / 'private/build/obj/project.assets.json'
        assets.parent.mkdir(parents=True)
        packages = self.repo / '.local/packages'
        directory = packages / 'example/1.0.0'
        directory.mkdir(parents=True)
        archive = directory / 'example.1.0.0.nupkg'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('Example.nuspec', '<package/>')
        content_hash = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
        archive.with_name(archive.name + '.sha512').write_text(content_hash)
        (directory / '.nupkg.metadata').write_text(json.dumps(
            {'contentHash': content_hash, 'source': shader.NUGET}))
        (directory / 'example.nuspec').write_text('<package/>')
        data = {'project': {'restore': {'sources': {shader.NUGET: {}}}},
                'libraries': {'Example/1.0.0': {'type': 'package', 'path': 'example/1.0.0',
                  'sha512': base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()}}}
        assets.write_text(json.dumps(data))
        self.assertIn('Example/1.0.0', shader.package_receipts(wonder, packages))
        (directory / 'example.nuspec').write_text('<tampered/>')
        with self.assertRaisesRegex(ValueError, 'expanded package'):
            shader.package_receipts(wonder, packages)
        (directory / 'example.nuspec').write_text('<package/>')
        archive.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'hash'):
            shader.package_receipts(wonder, packages)
        data['project']['restore']['sources'] = {'https://unapproved.invalid': {}}
        assets.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'sources'):
            shader.package_receipts(wonder, packages)

    def test_zero_exit_with_failed_results_is_rejected(self):
        fake = self.repo / '.local/fake-harness'
        fake.write_text('#!/bin/sh\nprintf "hash\\tstatus\\nabc\\tinvalid\\n"\nexit 0\n')
        fake.chmod(0o755)
        output = self.repo / '.local/results.tsv'
        result = shader.run([fake], log=output)
        self.assertEqual(result.returncode, 0)
        with self.assertRaisesRegex(ValueError, 'failed/invalid'):
            shader.check_results(output)
        output.write_text('hash\tstatus\na\tok\nb\tok-retry\n')
        self.assertEqual(shader.check_results(output), 2)
        with self.assertRaisesRegex(ValueError, 'complete input inventory'):
            shader.check_results(output, {'a', 'b', 'missing'})

    def test_subprocess_failure_preserves_actual_diagnostic(self):
        log = self.repo / '.local/build.log'
        with self.assertRaisesRegex(ValueError, 'compiler failure'):
            shader.run([sys.executable, '-c', 'print("compiler failure"); raise SystemExit(7)'], log=log)
        self.assertEqual(log.read_text(), 'compiler failure\n')


if __name__ == '__main__':
    unittest.main()
