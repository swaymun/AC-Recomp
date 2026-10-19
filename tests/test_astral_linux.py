"""Linux overlay (astral-linux.patch, docs/ASTRAL_LINUX.md): the series, the overlay applying after series.macos on
the pinned runtime, and the Linux fiber context switch (fiber_context_linux.S with hle_fiber.cpp's prepare_entry),
assembled for x86-64 and arm64 ELF and, on a Linux host, run through first entry, resumption and the preserved
callee-saved/floating-point control state. No game, GPU or window is used."""
import os
import platform
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
OVERLAY = PATCHES / 'astral-linux.patch'
ASM = 'runtime/src/fiber_context_linux.S'
FIBER = 'runtime/src/hle_fiber.cpp'


def prepare_entry_block() -> str:
    """HostContext, the assembly entry points and prepare_entry, as hle_fiber.cpp has them after the overlay."""
    body = added_file(OVERLAY, FIBER)
    start = body.index('#if defined(__aarch64__)\nstruct alignas(16) HostContext')
    end = body.index('\n}\n', body.index('void prepare_entry(')) + 3
    return body[start:end]


HARNESS = r'''
#include <cassert>
#include <cfenv>
#include <cstdint>
#include <cstdio>
#include <cstddef>
#include <sys/mman.h>
struct alignas(16) V128 { uint64_t lo, hi; };
namespace {
@BLOCK@
HostContext root, fiber;
int entries = 0, resumes = 0;
volatile uintptr_t entry_sp = 0;
[[noreturn]] void enter(void* arg) {
    assert(arg == nullptr);
    alignas(16) volatile char probe[16];
    entry_sp = reinterpret_cast<uintptr_t>(probe);
    assert(entry_sp % 16 == 0);
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
    const size_t bytes = 1 << 20;
    void* stack = mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(stack != MAP_FAILED);
    const uintptr_t top = reinterpret_cast<uintptr_t>(stack) + bytes;
    prepare_entry(fiber, top);
    std::fesetround(FE_TOWARDZERO);
    volatile uint64_t keep[6] = {1, 2, 3, 4, 5, 6};
    uint64_t sum = 0;
    for (int k = 0; k < 5; k++) {
        uint64_t a = keep[k % 6] * 7 + k, b = a ^ 0x5a5a;  // live across the swap in callee-saved registers
        nx_fiber_swap(&root, &fiber);
        assert(std::fegetround() == FE_TOWARDZERO);
        sum += a + b;
        assert(b == (a ^ 0x5a5a));
    }
    assert(entries == 1 && resumes == 4);
    assert(entry_sp > top - 4096 && entry_sp < top);
    std::printf("PASS fiber: 1 entry, 4 resumes, sum %llu\n", (unsigned long long)sum);
    return 0;
}
'''


class LinuxSeriesTest(unittest.TestCase):
    def test_linux_series_is_the_macos_series_then_the_overlay(self):
        macos = acr.read_series(PATCHES / 'series.macos')
        linux = acr.read_series(PATCHES / 'series.linux')
        self.assertEqual(linux, [*macos, OVERLAY.name])

    def test_overlay_is_public_and_limited(self):
        text = OVERLAY.read_text()
        self.assertNotRegex(text, r'/(?:Users|home|work)/')
        files = re.findall(r'^diff --git a/(\S+) ', text, re.M)
        self.assertEqual(files, ['CMakeLists.txt', ASM, FIBER, 'runtime/src/kernel.cpp', 'runtime/src/nvn/nvn_caps.cpp',
                                 'runtime/src/nvn/nvn_vk.cpp'])
        # The host-cached upload ring default is Linux-only; other hosts keep NX_RING_CACHED opt-in.
        caps = text.split('+++ b/runtime/src/nvn/nvn_caps.cpp', 1)[1].split('\ndiff --git ', 1)[0]
        self.assertIn('+#if defined(__linux__) && !defined(__ANDROID__)\n', caps)
        self.assertIn('+    if (!e) e = "1";\n', caps)
        # The Linux branch of CMakeLists.txt gains the fiber sources; the Apple branch is untouched.
        cmake = text.split('diff --git a/CMakeLists.txt', 1)[1].split('\ndiff --git ', 1)[0]
        self.assertIn('@@ -248,7 +248,9 @@ elseif(UNIX)', cmake)
        self.assertIn('+        runtime/src/hle_fiber.cpp runtime/src/fiber_context_linux.S)', cmake)

    def test_overlay_applies_after_series_macos(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not (reference / '.git').exists():
            self.skipTest('private pinned upstream reference unavailable')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source'
            runtime.prepare_source(reference, source, [PATCHES / n for n in acr.read_series(PATCHES / 'series.linux')])
            fiber = (source / FIBER).read_text()
            self.assertIn('prepare_entry(d->host,start+host_stack_bytes);', fiber)
            self.assertIn('(defined(__linux__) && !defined(__ANDROID__))', (source / 'runtime/src/kernel.cpp').read_text())
            self.assertIn('!plat::headless()', (source / 'runtime/src/nvn/nvn_vk.cpp').read_text())
            self.assertEqual((source / ASM).read_text(), added_file(OVERLAY, ASM).rstrip('\n') + '\n')


class LinuxFiberContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.asm = self.tmp / 'fiber_context_linux.S'
        self.asm.write_text(added_file(OVERLAY, ASM))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assembles_for_linux_x86_64_and_arm64(self):
        clang = shutil.which('clang')
        if not clang:
            self.skipTest('clang unavailable')
        for target, symbols in (('x86_64-linux-gnu', 2), ('aarch64-linux-gnu', 2)):
            obj = self.tmp / f'{target}.o'
            r = subprocess.run([clang, '--target=' + target, '-c', str(self.asm), '-o', str(obj)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(obj.read_bytes()[:4], b'\x7fELF')

    def test_first_entry_resume_and_preserved_state_on_linux(self):
        if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'aarch64'):
            self.skipTest('needs a Linux x86-64 or arm64 host')
        cxx = shutil.which('clang++') or shutil.which('c++')
        source = self.tmp / 'harness.cpp'
        source.write_text(HARNESS.replace('@BLOCK@', prepare_entry_block()))
        exe = self.tmp / 'harness'
        r = subprocess.run([cxx, '-std=c++20', '-O2', '-Wall', str(source), str(self.asm), '-o', str(exe)],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('PASS fiber: 1 entry, 4 resumes', r.stdout)


if __name__ == '__main__':
    unittest.main()
