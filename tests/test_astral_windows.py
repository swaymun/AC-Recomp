"""Windows x64 overlay (astral-windows.patch, docs/ASTRAL_WINDOWS.md): the series, the overlay applying after
series.linux and windows-native.patch on the pinned runtime, the Windows-only reach of every change, and, on a
Windows host with clang-cl, the Win32-fiber host continuation (first entry, resumption, preserved callee-saved and
floating-point control state). No game, GPU or window is used."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import acr_build as acr  # noqa: E402
import prepare_runtime as runtime  # noqa: E402
from test_astral_touch import added_file  # noqa: E402

PATCHES = ROOT / 'runtime/patches'
OVERLAY = PATCHES / 'astral-windows.patch'
FIBER = 'runtime/src/hle_fiber.cpp'


def section(text: str, path: str) -> str:
    return text.split(f'+++ b/{path}\n', 1)[1].split('\ndiff --git ', 1)[0]


def windows_fiber_block() -> str:
    """The Windows HostContext and nx_fiber_swap, as hle_fiber.cpp has them after the overlay."""
    body = added_file(OVERLAY, FIBER)
    start = body.index('#if defined(_WIN32)\n// Windows x64: each continuation')
    host = body[start:body.index('#elif defined(__aarch64__)', start)] + '#endif\n'
    swap = body[body.index('void WINAPI fiber_main'):body.index('#else\nextern "C" void nx_fiber_swap')]
    return host + swap


HARNESS = r'''
#include <windows.h>
#include <cassert>
#include <cfenv>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
namespace {
[[noreturn]] void fatal(const char* m) { std::fprintf(stderr, "%s\n", m); std::abort(); }
[[noreturn]] void enter(void*);
@BLOCK@
HostContext root, fiber;
int entries = 0, resumes = 0;
[[noreturn]] void enter(void* arg) {
    assert(arg == nullptr);
    alignas(16) volatile char probe[16];
    assert(reinterpret_cast<uintptr_t>(probe) % 16 == 0);
    entries++;
    for (;;) {
        std::fesetround(FE_UPWARD);  // the fiber's own rounding mode
        nx_fiber_swap(&fiber, &root);
        assert(std::fegetround() == FE_UPWARD);
        resumes++;
    }
}
}  // namespace
int main() {
    fiber.fiber = CreateFiberEx(64 * 1024, 1 << 20, FIBER_FLAG_FLOAT_SWITCH, &fiber_main, nullptr);
    assert(fiber.fiber);
    std::fesetround(FE_TOWARDZERO);
    volatile uint64_t keep[6] = {1, 2, 3, 4, 5, 6};
    uint64_t sum = 0;
    for (int k = 0; k < 5; k++) {
        uint64_t a = keep[k % 6] * 7 + k, b = a ^ 0x5a5a;  // live across the switch in callee-saved registers
        double d = double(a) / 3.0;                      // and in xmm6-xmm15
        nx_fiber_swap(&root, &fiber);
        assert(std::fegetround() == FE_TOWARDZERO);
        assert(d == double(a) / 3.0);
        sum += a + b;
        assert(b == (a ^ 0x5a5a));
    }
    assert(entries == 1 && resumes == 4);
    DeleteFiber(fiber.fiber);
    std::printf("PASS fiber: 1 entry, 4 resumes, sum %llu\n", (unsigned long long)sum);
    return 0;
}
'''


class WindowsSeriesTest(unittest.TestCase):
    def test_windows_series_is_the_linux_series_then_the_windows_overlays(self):
        linux = acr.read_series(PATCHES / 'series.linux')
        windows = acr.read_series(PATCHES / 'series.windows')
        self.assertEqual(windows, [*linux, 'windows-native.patch', OVERLAY.name])

    def test_overlay_is_public_and_limited(self):
        text = OVERLAY.read_text()
        self.assertNotRegex(text, r'/(?:Users|home|work)/|[A-Z]:[\\/]')
        files = re.findall(r'^diff --git a/(\S+) ', text, re.M)
        self.assertEqual(files, ['CMakeLists.txt', FIBER, 'runtime/src/kernel.cpp', 'runtime/src/nvn/nvn_caps.cpp',
                                 'runtime/src/platform_win.cpp'])
        # platform_win.cpp is built on Windows only; its sleep uses a high-resolution waitable timer.
        self.assertIn('CREATE_WAITABLE_TIMER_HIGH_RESOLUTION', section(text, 'runtime/src/platform_win.cpp'))

    def test_every_change_is_windows_only(self):
        text = OVERLAY.read_text()
        # CMake: the Windows (else) branch gains hle_fiber.cpp; hwopus takes libopus's CMake package on WIN32 only.
        cmake = section(text, 'CMakeLists.txt')
        self.assertIn('+if(NX_HWOPUS AND WIN32)\n', cmake)
        self.assertIn('+elseif(NX_HWOPUS)\n', cmake)
        self.assertIn('+    target_link_libraries(${NX_GAME} PRIVATE Opus::opus)\n', cmake)
        self.assertIn('+        runtime/src/hle_fiber.cpp)\n', cmake)
        self.assertNotIn('fiber_context', cmake)
        # The fiber bridge: Win32 fibers with floating-point state switching, the root converted once.
        fiber = section(text, FIBER)
        for needle in ('CreateFiberEx(64*1024,host_stack_bytes,FIBER_FLAG_FLOAT_SWITCH,&fiber_main,nullptr)',
                       'ConvertThreadToFiberEx(nullptr, FIBER_FLAG_FLOAT_SWITCH)', 'SwitchToFiber(to->fiber)',
                       'DeleteFiber(allocation)', 'IsThreadAFiber()'):
            self.assertIn(needle, fiber)
        removed = [l for l in fiber.splitlines() if l.startswith('-') and not l.startswith('---')]
        self.assertEqual(len(removed), 4, removed)  # the #error guard, the aarch64 #if, enter's declaration: re-added
        # Linux-and-Windows defaults: same condition on Linux as before, extended by || defined(_WIN32).
        for path in ('runtime/src/kernel.cpp', 'runtime/src/nvn/nvn_caps.cpp'):
            part = section(text, path)
            minus = [l[1:] for l in part.splitlines() if l.startswith('-') and not l.startswith('---')]
            plus = [l[1:] for l in part.splitlines() if l.startswith('+') and not l.startswith('+++')]
            self.assertTrue(minus and len(minus) == len(plus), path)
            for old, new in zip(minus, plus):
                if old.startswith('#if'):
                    self.assertIn('|| defined(_WIN32)', new, path)
                    for token in re.findall(r'!?defined\(\w+\)', old):
                        self.assertIn(token, new, path)

    def test_build_series_covers_the_windows_overlay(self):
        patches = {p.name for p in PATCHES.glob('*.patch')}
        self.assertLessEqual(set(acr.read_series(PATCHES / 'series.windows')), patches)

    def test_overlay_applies_after_series_linux(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not (reference / '.git').exists():
            self.skipTest('private pinned upstream reference unavailable')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source'
            runtime.prepare_source(reference, source,
                                   [PATCHES / n for n in acr.read_series(PATCHES / 'series.windows')])
            fiber = (source / FIBER).read_text()
            self.assertIn('d->host.fiber=d->allocation;', fiber)
            self.assertIn('prepare_entry(d->host,start+host_stack_bytes);', fiber)
            self.assertIn('|| defined(_WIN32)) && \\', (source / 'runtime/src/kernel.cpp').read_text())
            self.assertIn('find_package(Opus 1.3 CONFIG REQUIRED)', (source / 'CMakeLists.txt').read_text())


class WindowsFiberTest(unittest.TestCase):
    def test_first_entry_resume_and_preserved_state_on_windows(self):
        if sys.platform != 'win32':
            self.skipTest('needs a Windows x64 host')
        cxx = shutil.which('clang-cl')
        if not cxx:
            self.skipTest('clang-cl unavailable')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'harness.cpp'
            source.write_text(HARNESS.replace('@BLOCK@', windows_fiber_block()))
            exe = Path(d) / 'harness.exe'
            r = subprocess.run([cxx, '/nologo', '/std:c++20', '/O2', '/EHsc', '/UNDEBUG', str(source), f'/Fe{exe}',
                                f'/Fo{Path(d) / "harness.obj"}'], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('PASS fiber: 1 entry, 4 resumes', r.stdout)


if __name__ == '__main__':
    unittest.main()
