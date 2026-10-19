"""Game-free policy integration checks; real Mach VM calls run only on Darwin.

Set APPLE_MEMORY_SOURCE to an ignored checkout at the documented Wonder pin.
The source-dependent checks skip explicitly when that optional dependency is absent.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
SOURCE = Path(os.environ.get('APPLE_MEMORY_SOURCE', str(
    ROOT / '.local/orchestrate/2026-10-18/apple-preflight/source')))
PATCH = ROOT / 'runtime/patches/apple-memory.patch'
FILES = ('runtime/src/platform_mac.cpp', 'runtime/include/nx/cpu.h',
         'runtime/include/nx/runtime.h', 'runtime/include/nx/module.h')


def command(args, **kwargs):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          timeout=60, **kwargs)


class LauncherTests(unittest.TestCase):
    def test_invalid_mode_stops_before_any_command(self):
        result = command(['bash', ROOT / 'scripts/check-apple-memory', '--invalid'])
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage:', result.stderr)

    def test_embedded_driver_compiles(self):
        script = (ROOT / 'scripts/check-apple-memory').read_text()
        driver = script.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        compile(driver, 'check-apple-memory embedded Python', 'exec')


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'),
                     'requires native Apple Mach VM and Clang')
class NativePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.exists():
            raise unittest.SkipTest('pinned source unavailable; set APPLE_MEMORY_SOURCE')
        pin = command(['git', '-C', SOURCE, 'rev-parse', 'HEAD'])
        if pin.returncode or pin.stdout.strip() != PIN:
            raise AssertionError('source must be exactly the documented pin')
        cls.temp = tempfile.TemporaryDirectory(prefix='acs-memory-test-')
        cls.work = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        result = command(['git', 'init', cls.work])
        if result.returncode:
            raise AssertionError(result.stderr)
        for name in FILES:
            result = command(['git', '-C', SOURCE, 'show', PIN + ':' + name])
            if result.returncode:
                raise AssertionError(result.stderr)
            target = cls.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.stdout)
        for flags in (['--check'], []):
            result = command(['git', '-C', cls.work, 'apply', *flags, PATCH])
            if result.returncode:
                raise AssertionError(result.stderr)
        text = (cls.work / FILES[0]).read_text()
        memory = text[text.index('bool reserve('):text.index('// ---- threads and time')]
        cls.header = cls.work / 'patched_memory.h'
        cls.header.write_text('namespace nx::plat {\n' + memory + '\n}\n')
        cls.binary = cls.work / 'high'
        result = command(['xcrun', 'clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                          '-DAPPLE_MEMORY_HIGH_PROFILE',
                          '-DAPPLE_MEMORY_PATCH_HEADER="' + str(cls.header) + '"',
                          ROOT / 'probes/apple_memory.cpp', '-o', cls.binary])
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_actual_patched_memory_in_five_fresh_processes(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                result = command([self.binary])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('memory_profile=apple-high-v1', result.stdout)
                for name in ('modules', 'heap', 'alias', 'stack', 'kernel', 'thunk'):
                    lines = [line for line in result.stdout.splitlines()
                             if line.startswith('reserve name=' + name + ' ') and 'collision_test=0' in line]
                    self.assertEqual(len(lines), 1)
                    self.assertIn('exact=1', lines[0])
                self.assertIn('occupied_range_rejected=1 original_byte_intact=1', result.stdout)
                self.assertIn('fixed_partial zero=1 neighbors_preserved=1 protection=3', result.stdout)
                self.assertIn('fixed_mixed whole_pages_zero=1 neighbors_preserved=1 guard_none=1 guard_read_denied=1 recommit=1', result.stdout)
                self.assertIn('fixed_whole all_bytes_zero=1 guard_none=1 recommit=1', result.stdout)
                self.assertIn('RESULT status=PASS exit_code=0', result.stdout)

    def test_headers_preserve_default_and_generated_pointer_contract(self):
        fixture = self.work / 'contract.cpp'
        fixture.write_text('''#include <nx/runtime.h>
#ifdef NX_APPLE_HIGH_MEMORY
static_assert(NX_BASE == 0x7000000000ull);
static_assert(nx::kHeapBase == 0x7100000000ull);
static_assert(nx::kAliasBase == 0x7300000000ull);
static_assert(nx::kStackBase == 0x7800000000ull);
static_assert(nx::kKernelBase == 0x7900000000ull);
static_assert(nx::kThunkBase == 0x7B00000000ull);
#else
static_assert(NX_BASE == 0x300000000ull);
static_assert(nx::kHeapBase == 0x400000000ull);
#endif
// Same module offset expression emitted by recomp; SDK is main + 256 MiB.
constexpr uint64_t generated_sdk = NX_BASE + (0x4010000000ull - 0x4000000000ull);
static_assert(generated_sdk == nx::kModuleBase + 0x10000000ull);
static_assert(nx::kThunkBase + nx::kThunkSize <= nx::kAddressSpaceBase + nx::kAddressSpaceSize);
''')
        for flags in ([], ['-DNX_APPLE_HIGH_MEMORY']):
            result = command(['xcrun', 'clang++', '-std=c++20', '-fsyntax-only',
                              '-I' + str(self.work / 'runtime/include'), *flags, fixture])
            self.assertEqual(result.returncode, 0, result.stderr)
        result = command(['xcrun', 'clang++', '-std=c++20', '-fsyntax-only',
                          '-I' + str(self.work / 'runtime/include'), '-DNX_APPLE_HIGH_MEMORY',
                          '-DNX_BASE=0x300000000ull', fixture])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires its profile NX_BASE', result.stderr)

    def test_unmodified_profile_still_reports_baseline(self):
        binary = self.work / 'baseline'
        result = command(['xcrun', 'clang++', '-std=c++17', ROOT / 'probes/apple_memory.cpp', '-o', binary])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = command([binary])
        self.assertIn('memory_profile=upstream-baseline', result.stdout)
        self.assertIn('reserve name=modules base=0x300000000', result.stdout)
        self.assertIn('full_decommit madvise_rc=', result.stdout)
        self.assertNotIn('fixed_whole', result.stdout)
        self.assertIn('RESULT status=', result.stdout)
        # Default occupancy is process/OS dependent; a future free default layout
        # must not make this test demand an artificial failure.
        self.assertIn(result.returncode, (0, 1))


if __name__ == '__main__':
    unittest.main()
