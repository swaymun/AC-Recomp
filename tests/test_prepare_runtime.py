"""Offline synthetic Git/subprocess integration checks; no real game or cloud inputs."""
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import prepare_runtime as r


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ref = self.root / 'reference'
        self.ref.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.ref / 'original.txt').write_text('before\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.pin = r.git(self.ref, 'rev-parse', 'HEAD')
        self.patch = self.root / 'change.patch'
        self.patch.write_text('--- a/original.txt\n+++ b/original.txt\n@@ -1 +1 @@\n-before\n+after\n')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.ref), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_clone_apply_and_drift_fingerprint(self):
        source = self.root / 'copy'
        before = r.prepare_source(self.ref, source, [self.patch], self.pin)
        self.assertEqual((source / 'original.txt').read_text(), 'after\n')
        self.assertEqual((self.ref / 'original.txt').read_text(), 'before\n')
        self.assertEqual(r.git(source, 'rev-parse', 'HEAD'), self.pin)
        (source / 'original.txt').write_text('drift\n')
        self.assertNotEqual(before, r.source_fingerprint(source))

    def test_wrong_pin_dirty_and_existing_refused(self):
        with self.assertRaisesRegex(ValueError, 'wrong reference'):
            r.prepare_source(self.ref, self.root / 'copy', [self.patch], '0' * 40)
        (self.ref / 'original.txt').write_text('dirty\n')
        with self.assertRaisesRegex(ValueError, 'dirty reference'):
            r.prepare_source(self.ref, self.root / 'copy', [self.patch], self.pin)
        self.git('checkout', '--', 'original.txt')
        with self.assertRaisesRegex(ValueError, 'source already'):
            r.prepare_source(self.ref, self.ref, [self.patch], self.pin)

    def test_patch_order_and_bad_context_fails(self):
        second = self.root / 'second.patch'
        second.write_text(self.patch.read_text().replace('-before', '-after').replace('+after', '+final'))
        source = self.root / 'copy'
        r.prepare_source(self.ref, source, [self.patch, second], self.pin)
        self.assertEqual((source / 'original.txt').read_text(), 'final\n')
        with self.assertRaises(subprocess.CalledProcessError):
            r.prepare_source(self.ref, self.root / 'bad', [second], self.pin)

    def test_private_boundary_gitignore_tracking_and_symlink(self):
        (self.ref / '.gitignore').write_text('.local/\n')
        d = self.ref / '.local' / 'work'
        self.assertEqual(r.private(self.ref, d), d)
        with self.assertRaisesRegex(ValueError, 'inside repository'):
            r.private(self.ref, self.root / 'escape')
        d.parent.mkdir()
        d.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            r.private(self.ref, d)
        d.unlink()
        d.mkdir()
        (d / 'tracked').write_text('x')
        self.git('add', '-f', '.local/work/tracked')
        with self.assertRaisesRegex(ValueError, 'tracked private'):
            r.private(self.ref, d)

    def test_subprocess_logs_failure_and_exact_arguments(self):
        log = self.root / 'child.log'
        with self.assertRaisesRegex(ValueError, 'child exit 7'):
            r.run_logged([sys.executable, '-c', 'print("first blocker"); raise SystemExit(7)'], log)
        self.assertIn('first blocker', log.read_text())
        r.run_logged([sys.executable, '-c', 'import sys; print(sys.argv[1])', 'literal $(false)'], log)
        self.assertIn('literal $(false)', log.read_text())

    def test_manifest_file_hash_size_escape_and_link(self):
        p = self.root / 'input'
        p.write_bytes(b'fixture')
        rec = {'path': 'input', 'size': 7, 'sha256': r.sha(p)}
        self.assertEqual(r.check_file(self.root, rec), p)
        with self.assertRaisesRegex(ValueError, 'hash/size'):
            r.check_file(self.root, dict(rec, size=8))
        with self.assertRaisesRegex(ValueError, 'unsafe manifest'):
            r.check_file(self.ref, dict(rec, path='../input'))
        os.link(p, self.root / 'link')
        with self.assertRaisesRegex(ValueError, 'linked manifest'):
            r.check_file(self.root, rec)

    def test_generated_base_extent_reports_and_hashes(self):
        d = self.root / 'gen/main'
        d.mkdir(parents=True)
        (d / 'funcs.h').write_text('#define NXB (NX_BASE + 0x0ull)\n')
        (d / 'table.cpp').write_text('"main", NX_BASE + 0x0ull,\n 0x0, 0x10, 0x1000, 0x10, 0x2000, 0x10, 0x3000, 0x20,\n')
        (d / 'report.txt').write_text('functions 1, handled 2, unhandled 1\n1 sqshl\n')
        m = {'modules': [{'name': 'main', 'bss_size': 32, '_mod0_bss': [0x3000, 32], 'segments': [
            {'memory_offset': i * 4096, 'size': 16} for i in range(3)]}]}
        result = r.generated_evidence(d.parent, m)
        self.assertIn('sqshl', result['main']['report'])
        (d / 'funcs.h').write_text('#define NXB (NX_BASE + 0x10000000ull)\n')
        with self.assertRaisesRegex(ValueError, 'wrong generated base'):
            r.generated_evidence(d.parent, m)

    def test_reject_wrong_title_before_input_access(self):
        d = self.root / 'inputs/.wrapper'
        d.mkdir(parents=True)
        (d / 'manifest.json').write_text(json.dumps({'schema': 1, 'title_id': 'wrong'}))
        with self.assertRaisesRegex(ValueError, 'wrong input'):
            r.validate_inputs(d.parent)

    def test_actual_boot_contract_metadata_and_rejections(self):
        raw = bytearray(256)
        flat = bytearray(1024)
        struct.pack_into('<I', flat, 4, 8)
        flat[8:12] = b'MOD0'
        struct.pack_into('<iii', flat, 12, 64 - 8, 1024 - 8, 1056 - 8)
        tags = [(5, 640), (6, 512), (10, 128), (12, 48), (27, 8), (0, 0)]
        for n, entry in enumerate(tags):
            struct.pack_into('<qQ', flat, 64 + n * 16, *entry)
        struct.pack_into('<II', raw, 0x98, 256, 48)
        struct.pack_into('<IBBHQQ', flat, 536, 1, 0x12, 0, 1, 48, 16)
        flat[640:648] = b'\0nnMain\0'
        mod = {'name': 'main', 'bss_size': 32, 'segments': [
            {'memory_offset': 0, 'size': 256}, {'memory_offset': 256, 'size': 768}]}
        result = r.boot_metadata(raw, flat, mod)
        self.assertEqual(result['entry_symbol'], 'nnMain')
        self.assertEqual(result['mod0_bss'], [1024, 32])
        struct.pack_into('<Q', flat, 64 + 3 * 16 + 8, 64)
        with self.assertRaisesRegex(ValueError, 'DT_INIT'):
            r.boot_metadata(raw, flat, mod)
        struct.pack_into('<Q', flat, 64 + 3 * 16 + 8, 48)
        flat[641:647] = b'noMain'
        with self.assertRaisesRegex(ValueError, 'boot export'):
            r.boot_metadata(raw, flat, mod)

    def test_fixture_rejects_partial_or_truncated_shipped_source(self):
        self.patch.write_text('diff --git a/x.cpp b/x.cpp\n--- a/x.cpp\n+++ b/x.cpp\n'
                              '@@ -2,1 +2,1 @@\n-before\n+after\n')
        with self.assertRaisesRegex(ValueError, 'full source'):
            r.patched_source(self.patch, 'x.cpp')
        self.patch.write_text(self.patch.read_text().replace('@@ -2,1 +2,1 @@', '@@ -1,2 +1,2 @@'))
        with self.assertRaisesRegex(ValueError, 'incomplete fixture'):
            r.patched_source(self.patch, 'x.cpp')

    def test_jobs_bounded(self):
        with self.assertRaisesRegex(ValueError, '1..3'):
            r.jobs(4)
        with patch.object(r.os, 'cpu_count', return_value=2):
            self.assertLessEqual(r.jobs(3), 2)


class LoaderWeakIntegrationTests(unittest.TestCase):
    def test_actual_patched_loader(self):
        # Full-file context keeps this executable test on the shipped loader.
        # No private reference checkout, game data, or alternative resolver is used.
        root = TOOLS.parent
        loader = r.patched_source(root / 'runtime/patches/astral-bootstrap.patch', 'runtime/src/loader.cpp')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++ compiler required for actual loader integration')
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / 'nx').mkdir()
            (d / 'nx/runtime.h').write_text('// synthetic host declarations precede loader include\n')
            (d / 'platform.h').write_text('// synthetic host boundary\n')
            (d / 'loader.cpp').write_text(loader)
            build = subprocess.run([compiler, '-std=c++20', '-DNX_ASTRAL_STRICT=1',
                                    '-I', str(d), str(root / 'tests/test_loader_weak_symbols.cpp'),
                                    '-o', str(d / 'loader-test')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            for mode in ('weak', 'weak-function', 'weak-object', 'strong-data',
                         'strong-function', 'strong-notype', 'unknown', 'defined', 'export', 'hle', 'null-call', 'missing-call'):
                with self.subTest(mode=mode):
                    env = dict(os.environ, NX_LOG=str(d / (mode + '.log')))
                    result = subprocess.run([str(d / 'loader-test'), mode, str(d)],
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('PASS ' + mode, result.stdout)
                    if mode.startswith('strong'):
                        self.assertIn('strict link blocked:', result.stdout)
                    if mode == 'unknown':
                        self.assertIn('relocations=1', result.stdout)
                    if mode == 'missing-call':
                        self.assertIn('strict missing function: unimplemented', result.stdout)
                    if mode == 'null-call':
                        self.assertIn('FATAL: call to 0', result.stdout)


class SelfControllerIntegrationTests(unittest.TestCase):
    def compile_actual_kernel(self, fixture_name):
        root = TOOLS.parent
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / 'nx').mkdir()
            for name in ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp', 'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp'):
                (d / name).write_text(r.patched_source(
                    root / 'runtime/patches/astral-bootstrap.patch', 'runtime/src/' + name))
            for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h'):
                (d / name).write_text('// Unrelated host declarations are in the fixture.\n')
            service_fixture = (root / 'tests/test_self_controller.cpp').read_text()
            (d / 'language.h').write_text('// declared by fixture\n')
            # Preserve the landed endpoint fixture on disk. Its obsolete 91-fatal
            # expectation is superseded by the new actual-dispatch acceptance.
            kernel_fixture = (root / 'tests/test_kernel_events.cpp').read_text()
            self.assertEqual(kernel_fixture.count('for(uint32_t cmd:{90u,91u})'), 1)
            kernel_fixture = kernel_fixture.replace('for(uint32_t cmd:{90u,91u})',
                                                     'for(uint32_t cmd:{90u})')
            kernel_fixture = kernel_fixture.replace('strict command 90/91', 'strict command 90')
            (d / 'test_kernel_events.cpp').write_text(kernel_fixture)
            self.assertEqual(kernel_fixture.count('int main() {'), 1)
            (d / 'kernel-host.h').write_text(kernel_fixture.split('int main() {', 1)[0])
            (d / 'test_self_controller.cpp').write_text(service_fixture)
            (d / 'test_window_controller.cpp').write_text(
                (root / 'tests/test_window_controller.cpp').read_text())
            if fixture_name in ('test_parental_control.cpp', 'test_ipc_caller.cpp'):
                (d / fixture_name).write_text((root / 'tests' / fixture_name).read_text())
            if fixture_name == 'test_parental_control.cpp':
                (d / 'astral_control_context.h').write_text(
                    '#pragma once\n#if !defined(NX_TEST_NO_CONTROL)\n'
                    '#if defined(NX_TEST_BAD_CONTROL)\n#define TEST_FLAGS 2\n'
                    '#elif defined(NX_TEST_FREE_CONTROL)\n#define TEST_FLAGS 1\n#else\n#define TEST_FLAGS 0\n#endif\n'
                    '#define NX_CONTROL_CONTEXT {0x1234000000000000ull,0x1234000000000000ull,TEST_FLAGS,{0},"' +
                    'a' * 64 + '"}\n#endif\n')
            command = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1',
                       '-I', str(d), str(d / fixture_name), '-o', str(d / 'fixture')]
            print('actual kernel fixture compile argv: ' + json.dumps(command))
            build = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(d / 'fixture')], capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if fixture_name == 'test_ipc_caller.cpp':
                last = subprocess.run([str(d / 'fixture'), '--last-thread'],
                                      capture_output=True, text=True, timeout=10)
                self.assertEqual(last.returncode, 0, last.stdout + last.stderr)
                result.stdout += last.stdout
            if fixture_name == 'test_parental_control.cpp':
                for define in ('NX_TEST_NO_CONTROL', 'NX_TEST_BAD_CONTROL', 'NX_TEST_FREE_CONTROL'):
                    negative = subprocess.run(command + ['-D' + define], capture_output=True, text=True, timeout=60)
                    self.assertEqual(negative.returncode, 0, negative.stdout + negative.stderr)
                    negative = subprocess.run([str(d / 'fixture')], capture_output=True, text=True, timeout=10)
                    self.assertEqual(negative.returncode, 0, negative.stdout + negative.stderr)
                    self.assertIn('Initialize loads context' if define == 'NX_TEST_FREE_CONTROL' else 'metadata rejects', negative.stdout)
                    result.stdout += negative.stdout
            self.assertNotIn('BLOCKED', result.stdout)
            self.assertNotIn('DIAGNOSTIC', result.stdout)
            print(result.stdout, end='')
            return result.stdout

    def test_actual_dispatch_readable_event(self):
        output = self.compile_actual_kernel('test_self_controller.cpp')
        self.assertIn('PASS command 91 actual CMIF copied readable event', output)
        self.assertIn('PASS actual invalid handles, strict command 90', output)
        self.assertIn('PASS actual domain type 6 and CMIF clone', output)

    def test_actual_dispatch_focus_handling_mode(self):
        output = self.compile_actual_kernel('test_self_controller.cpp')
        for assertion in ('PASS command 13 CMIF three-byte policy',
                          'PASS command 13 domain clone, factory and applet-owned lifetime',
                          'PASS command 13 malformed payloads and targets'):
            self.assertIn(assertion, output)

    def test_actual_dispatch_domain_framing(self):
        output = self.compile_actual_kernel('test_self_controller.cpp')
        self.assertIn('PASS domain framing command 13 rejects', output)
        self.assertIn('PASS domain framing exact boolean/object boundary', output)

    def test_actual_dispatch_out_of_focus_suspending(self):
        output = self.compile_actual_kernel('test_self_controller.cpp')
        for assertion in ('PASS command 16 CMIF single-byte result-only',
                          'PASS command 16 domain clone, shared policy',
                          'PASS command 16 atomic malformed rejection',
                          'PASS command 16 domain header-only padding/object rejection'):
            self.assertIn(assertion, output)

    def test_actual_kernel_endpoint_permissions(self):
        output = self.compile_actual_kernel('test_kernel_events.cpp')
        for assertion in ('PASS actual CMIF/TIPC Close',
                          'PASS actual domain clone/subobject close',
                          'PASS actual readable SignalEvent',
                          'PASS actual bounded timeout',
                          'PASS actual unknown SVC remains fatal'):
            self.assertIn(assertion, output)


class IpcCallerTests(unittest.TestCase):
    compile_actual_kernel = SelfControllerIntegrationTests.compile_actual_kernel

    def test_actual_kernel_caller_boundary(self):
        output = self.compile_actual_kernel('test_ipc_caller.cpp')
        for assertion in ('PASS caller both SVC paths', 'PASS caller malformed atomic',
                          'PASS caller process handles', 'PASS caller lifetime',
                          'PASS caller last-thread teardown'):
            self.assertIn(assertion, output)


class ParentalControlPrerequisiteTests(unittest.TestCase):
    compile_actual_kernel = SelfControllerIntegrationTests.compile_actual_kernel

    def test_actual_initialization_prerequisite_and_strict_gate(self):
        output = self.compile_actual_kernel('test_parental_control.cpp')
        for assertion in ('PASS parental factories actual serialized objects',
                          'PASS parental Initialize loads context',
                          'PASS parental domain clone shared lifetime',
                          'PASS parental malformed framing and invalid targets'):
            self.assertIn(assertion, output)


class WindowControllerIntegrationTests(unittest.TestCase):
    # Reuse the declared host boundary, not a substitute dispatcher.
    compile_actual_kernel = SelfControllerIntegrationTests.compile_actual_kernel

    def test_actual_dispatch_foreground_rights(self):
        output = self.compile_actual_kernel('test_window_controller.cpp')
        for assertion in ('PASS foreground CMIF no-output serialization',
                          'PASS foreground domain clone and service lifetime',
                          'PASS foreground malformed targets and strict unknown commands'):
            self.assertIn(assertion, output)


if __name__ == '__main__':
    unittest.main()
