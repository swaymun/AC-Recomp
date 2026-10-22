"""Game-free regression tests for the Windows changed-word write-back overlay.

Compile the production functions extracted from full-context hunks. AVX2 executes
natively on Windows/x86-64, or through Rosetta on Apple silicon; that is separately
identified from real Windows gameplay measurements in ASTRAL_WINDOWS_PERF.md.
"""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'runtime/patches/astral-windows-perf.patch'
PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'


def function(path, signature):
    section = PATCH.read_text().split('+++ b/' + path + '\n', 1)[1].split('\ndiff --git ', 1)[0]
    source = ''.join(('\n' if not line else line[1:] + '\n') for line in section.splitlines()
                     if not line or line.startswith((' ', '+')))
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth and end < len(source):
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    if depth:
        raise ValueError('function needs full-context patch hunk')
    return source[start:end]


HARNESS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <random>
#include <vector>
#ifdef _WIN32
#define TEST_REAL_WIN 1
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif
#ifdef TEST_SIMD
#include <immintrin.h>
#ifndef _WIN32
#define _WIN32 1
#endif
#ifndef _M_X64
#define _M_X64 1
#endif
#define NX_ASTRAL_STRICT 1
#endif
struct WriteBack {
    uint8_t* from;
    uint8_t* to;
    uint64_t size;
    std::shared_ptr<std::vector<uint8_t>> before;
};
@FUNCTION@
struct Guarded {
    uint8_t* base;
    size_t page;
    Guarded() {
#ifdef TEST_REAL_WIN
        SYSTEM_INFO info{}; GetSystemInfo(&info); page = info.dwPageSize;
        base = static_cast<uint8_t*>(VirtualAlloc(nullptr, page * 2, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        assert(base); DWORD old; assert(VirtualProtect(base + page, page, PAGE_NOACCESS, &old));
#else
        page = size_t(sysconf(_SC_PAGESIZE));
        base = static_cast<uint8_t*>(mmap(nullptr, page * 2, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0));
        assert(base != MAP_FAILED); assert(mprotect(base + page, page, PROT_NONE) == 0);
#endif
    }
    void readonly(bool on) {
#ifdef TEST_REAL_WIN
        DWORD old; assert(VirtualProtect(base, page, on ? PAGE_READONLY : PAGE_READWRITE, &old));
#else
        assert(mprotect(base, page, on ? PROT_READ : PROT_READ | PROT_WRITE) == 0);
#endif
    }
    ~Guarded() {
#ifdef TEST_REAL_WIN
        VirtualFree(base, 0, MEM_RELEASE);
#else
        munmap(base, page * 2);
#endif
    }
};
void guard_pages(bool whole) {
    Guarded source, destination;
    for (size_t n = 0; n <= 129; ++n) {
        uint8_t* from = source.base + source.page - n;
        uint8_t* to = destination.base + destination.page - n;
        std::fill_n(from, n, uint8_t(0)); std::fill_n(to, n, uint8_t(0x55));
        auto before = std::make_shared<std::vector<uint8_t>>(n, uint8_t(0));
        if (!whole) {
            // Even a masked write to unchanged guest words must be suppressed.
            destination.readonly(true);
            apply_write_back({from, to, n, before});
            destination.readonly(false);
            for (size_t k = 0; k < n; ++k) assert(to[k] == 0x55);
        }
        if (n) from[n - 1] = 7;
        apply_write_back({from, to, n, before});
        if (n) assert(to[n - 1] == 7);  // the inaccessible page immediately after the range catches overrun
    }
}
int main() {
    std::mt19937 random(1977);
    const bool whole = std::getenv("NX_WRITE_BACK_WHOLE") != nullptr;
    guard_pages(whole);
    unsigned cases = 0;
    std::vector<size_t> sizes;
    for (size_t n = 0; n <= 160; ++n) sizes.push_back(n);
    for (size_t n : {257, 1023, 4097}) sizes.push_back(n);
    for (size_t n : sizes) for (size_t offset = 0; offset < 32; ++offset) {
        const size_t dst_offset = 32 + offset, src_offset = 32 + (offset * 7) % 32;
        std::vector<uint8_t> src(n + 128), dst(n + 128);
        auto before = std::make_shared<std::vector<uint8_t>>(n);
        for (auto& b : src) b = uint8_t(random());
        for (auto& b : dst) b = uint8_t(random());  // concurrent guest contents differ from both snapshots
        std::copy_n(src.data() + src_offset, n, before->data());
        for (size_t i = 0; i < n; ++i)
            if (random() % 9 == 0) src[src_offset + i] ^= uint8_t(1 + random() % 255);
        std::vector<uint8_t> expected = dst;
        // Contract: changed complete 32-bit words in the 8-byte-aligned prefix, then changed tail bytes only.
        const size_t words = (n / 8) * 2;
        for (size_t word = 0; word < words; ++word) {
            const size_t at = word * 4;
            if (whole || !std::equal(before->begin() + at, before->begin() + at + 4, src.begin() + src_offset + at))
                std::copy_n(src.data() + src_offset + at, 4, expected.data() + dst_offset + at);
        }
        for (size_t at = words * 4; at < n; ++at)
            if (whole || (*before)[at] != src[src_offset + at]) expected[dst_offset + at] = src[src_offset + at];
        WriteBack w{src.data() + src_offset, dst.data() + dst_offset, n, before};
        apply_write_back(w);
        assert(dst == expected);  // includes unchanged guest words and untouched guards
        // Missing/short snapshots preserve the pre-existing full-copy fallback.
        w.before.reset();
        apply_write_back(w);
        assert(std::equal(src.begin() + src_offset, src.begin() + src_offset + n, dst.begin() + dst_offset));
        w.before = std::make_shared<std::vector<uint8_t>>(n ? n - 1 : 0);
        apply_write_back(w);
        assert(std::equal(src.begin() + src_offset, src.begin() + src_offset + n, dst.begin() + dst_offset));
        ++cases;
    }
    // Explicit unchanged lanes: updating one lane must preserve all seven other guest words.
    alignas(32) uint32_t was[8] = {}, from[8] = {}, guest[8];
    std::fill_n(guest, 8, 0x12345678u); from[3] = 42;
    auto before = std::make_shared<std::vector<uint8_t>>(32);
    std::memcpy(before->data(), was, 32);
    apply_write_back({reinterpret_cast<uint8_t*>(from), reinterpret_cast<uint8_t*>(guest), 32, before});
    for (unsigned k = 0; k < 8; ++k) assert(guest[k] == (whole ? from[k] : k == 3 ? 42 : 0x12345678u));
    std::printf("PASS writeback %u cases, unaligned ranges, changed words, tails, guards, snapshot fallbacks\n", cases);
}
'''


class WindowsPerfTest(unittest.TestCase):
    def test_scope_and_windows_only_guards(self):
        text = PATCH.read_text()
        self.assertEqual(re.findall(r'^diff --git a/(\S+) ', text, re.M),
                         ['runtime/src/nvn/nvn_written.cpp', 'runtime/src/frame_stats.cpp', 'runtime/src/nvn/nvn_vk.cpp', 'runtime/src/platform_win.cpp'])
        self.assertNotRegex(text, r'/(?:Users|home)/|[A-Z]:[\\/]')
        self.assertIn('#if defined(NX_ASTRAL_STRICT) && defined(_WIN32) && defined(_M_X64)', text)
        self.assertIn('#if defined(_WIN32) && defined(NX_ASTRAL_STRICT)', text)

    def test_enabled_only_after_full_windows_series(self):
        windows = (ROOT / 'runtime/patches/series.windows').read_text().splitlines()
        self.assertEqual(windows.count(PATCH.name), 1)
        self.assertGreater(windows.index(PATCH.name), windows.index('astral-windows-desktop.patch'))
        for platform_name in ('macos', 'linux'):
            self.assertNotIn(PATCH.name, (ROOT / ('runtime/patches/series.' + platform_name)).read_text())
        telemetry = function('runtime/src/frame_stats.cpp', 'void frame_presented()')
        self.assertIn('defined(__APPLE__) || defined(_WIN32)', telemetry)
        self.assertIn('std::getenv("NX_FRAME_LOG")', telemetry)
        self.assertIn('interval_ms=%.6f', telemetry)
        # Enabling interval logging must not activate the Apple-only pipeline prewarm on Windows.
        vk_section = PATCH.read_text().split('+++ b/runtime/src/nvn/nvn_vk.cpp\n', 1)[1]
        self.assertNotIn('shader_prewarm', vk_section)

    def test_windows_sdl_gamepad_lifetime(self):
        main = PATCH.read_text().split('+++ b/runtime/src/platform_win.cpp\n', 1)[1]
        self.assertLess(main.index('if (!nx::launcher::start())'), main.index('+    quit_launcher_gamepads();'))
        self.assertLess(main.index('+    quit_launcher_gamepads();'), main.index('nx::plat::start_memory_guard()'))
        if os.name != 'nt' or not os.environ.get('SDL3_TEST_ROOT'):
            self.skipTest('native Windows SDL lifecycle fixture requires SDL3_TEST_ROOT')
        sdk = Path(os.environ['SDL3_TEST_ROOT'])
        cxx = shutil.which('clang-cl')
        self.assertIsNotNone(cxx)
        body = function('runtime/src/platform_win.cpp', 'void quit_launcher_gamepads()')
        code = r"""
#include <cassert>
#include <cstdlib>
#include <cstdio>
#define SDL_MAIN_HANDLED 1
#include <SDL3/SDL.h>
@BODY@
int main() {
    assert(SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD));
    assert(SDL_WasInit(SDL_INIT_GAMEPAD) && SDL_WasInit(SDL_INIT_JOYSTICK));
    const SDL_Scancode key = SDL_GetScancodeFromKey(SDLK_A, nullptr);
    assert(key != SDL_SCANCODE_UNKNOWN);
    quit_launcher_gamepads();
    assert(SDL_WasInit(SDL_INIT_VIDEO) && SDL_WasInit(SDL_INIT_EVENTS));
    assert(SDL_GetScancodeFromKey(SDLK_A, nullptr) == key);
    const bool keep = std::getenv("NX_WIN_KEEP_SDL_GAMEPAD") != nullptr;
    assert(bool(SDL_WasInit(SDL_INIT_GAMEPAD)) == keep);
    assert(bool(SDL_WasInit(SDL_INIT_JOYSTICK)) == keep);
    SDL_Quit();
    std::puts("PASS SDL launcher gamepad lifetime; video retained, dependency released, escape respected");
}
""".replace('@BODY@', body)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); source = td / 'sdl.cpp'; source.write_text(code); exe = td / 'sdl.exe'
            cmd = [cxx, '/nologo', '/O2', '/std:c++20', '/EHsc', '/UNDEBUG', str(source),
                   '/I' + str(sdk / 'include'), '/Fe' + str(exe), '/Fo' + str(td / 'sdl.obj'),
                   '/link', '/LIBPATH:' + str(sdk / 'lib/x64'), 'SDL3.lib']
            built = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            for value in (None, '1', '0'):
                env = dict(os.environ, SDL_VIDEODRIVER='dummy', PATH=str(sdk / 'lib/x64') + os.pathsep + os.environ['PATH'])
                env.pop('NX_WIN_KEEP_SDL_GAMEPAD', None)
                if value is not None: env['NX_WIN_KEEP_SDL_GAMEPAD'] = value
                ran = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(ran.returncode, 0, str(value) + ran.stdout + ran.stderr)
                self.assertIn('PASS SDL launcher gamepad lifetime', ran.stdout)

    def compile_writeback(self, simd):
        cxx = shutil.which('clang-cl' if os.name == 'nt' else 'clang++')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / 'writeback.cpp'
            source.write_text(HARNESS.replace('@FUNCTION@', function('runtime/src/nvn/nvn_written.cpp',
                                                                    'void apply_write_back(')))
            exe = td / ('writeback.exe' if os.name == 'nt' else 'writeback')
            if os.name == 'nt':
                cmd = [cxx, '/nologo', '/O2', '/std:c++20', '/EHsc', '/UNDEBUG', '/D_CRT_SECURE_NO_WARNINGS',
                       '/arch:AVX2', str(source), '/Fe' + str(exe), '/Fo' + str(td / 'writeback.obj')]
                if simd:
                    cmd += ['/DTEST_SIMD=1']
                runner = [str(exe)]
            else:
                cmd = [cxx, '-std=c++20', '-O2', '-UNDEBUG', str(source), '-o', str(exe)]
                runner = [str(exe)]
                if simd:
                    cmd += ['-DTEST_SIMD=1', '-mavx2']
                    if platform.system() == 'Darwin':
                        cmd += ['-arch', 'x86_64']
                        if platform.machine() == 'arm64':
                            runner = ['/usr/bin/arch', '-x86_64', str(exe)]
                    elif platform.machine() not in ('x86_64', 'AMD64'):
                        self.skipTest('AVX2 fixture requires x86-64 or Rosetta')
            built = subprocess.run(cmd, capture_output=True, text=True, cwd=td, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            for flags in ({}, {'NX_WIN_SCALAR_WRITEBACK': '1'}, {'NX_WRITE_BACK_WHOLE': '1'}):
                env = {k: v for k, v in os.environ.items() if not k.startswith(('NX_WRITE_BACK_', 'NX_WIN_SCALAR_'))}
                env.update(flags)
                ran = subprocess.run(runner, capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(ran.returncode, 0, str(flags) + ran.stdout + ran.stderr)
                self.assertIn('PASS writeback 5248 cases', ran.stdout)

    def test_scalar_contract(self):
        self.compile_writeback(False)

    def test_windows_avx2_contract(self):
        self.compile_writeback(True)

    def test_thread_cpu_100ns_conversion_and_failure(self):
        body = function('runtime/src/frame_stats.cpp', 'uint64_t thread_cpu_ns()')
        cxx = shutil.which('clang++') or shutil.which('clang-cl')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        code = r'''
#include <cassert>
#include <cstdint>
#define NX_ASTRAL_STRICT 1
#ifndef _WIN32
#define _WIN32 1
#endif
struct FILETIME { uint32_t dwLowDateTime, dwHighDateTime; };
bool success = true;
void* GetCurrentThread() { return reinterpret_cast<void*>(17); }
bool GetThreadTimes(void* t, FILETIME*, FILETIME*, FILETIME* k, FILETIME* u) {
    assert(t == reinterpret_cast<void*>(17));
    *k = {0xffffffffu, 1}; *u = {3, 2}; return success;
}
@BODY@
int main() {
    assert(thread_cpu_ns() == ((uint64_t(1) << 32) + 0xffffffffu + (uint64_t(2) << 32) + 3) * 100);
    success = false; assert(thread_cpu_ns() == 0);
}
'''.replace('@BODY@', body)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / 'cpu.cpp'
            source.write_text(code)
            exe = td / ('cpu.exe' if os.name == 'nt' else 'cpu')
            if Path(cxx).stem == 'clang-cl':
                cmd = [cxx, '/nologo', '/std:c++20', '/EHsc', '/UNDEBUG', str(source), '/Fe' + str(exe),
                       '/Fo' + str(td / 'cpu.obj')]
            else:
                cmd = [cxx, '-std=c++20', '-UNDEBUG', str(source), '-o', str(exe)]
            built = subprocess.run(cmd, capture_output=True, text=True, cwd=td, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertEqual(subprocess.run([str(exe)], timeout=30).returncode, 0)

    def test_applies_after_current_windows_series(self):
        override = os.environ.get('NVN_REFERENCE')
        if override:
            reference = Path(override)
        else:
            git = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True)
            if git.returncode:
                self.skipTest('optional pinned upstream reference unavailable outside Git checkout')
            common = Path(git.stdout.strip())
            if not common.is_absolute():
                common = (ROOT / common).resolve()
            reference = common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        if not (reference / '.git').exists():
            self.skipTest('optional pinned upstream reference unavailable')
        self.assertEqual(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=reference, text=True).strip(), PIN)
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'runtime'
            subprocess.run(['git', 'clone', '--no-hardlinks', '--quiet', '--no-checkout', str(reference), str(source)],
                           check=True, capture_output=True, timeout=60)
            subprocess.run(['git', 'checkout', '--quiet', '--detach', PIN], cwd=source, check=True, timeout=30)
            names = [line.strip() for line in (ROOT / 'runtime/patches/series.windows').read_text().splitlines()
                     if line.strip() and not line.lstrip().startswith('#')]
            self.assertEqual(names.count(PATCH.name), 1)
            for name in names:
                result = subprocess.run(['git', 'apply', str(ROOT / 'runtime/patches' / name)], cwd=source,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, name + result.stdout + result.stderr)
            for path, signature in [('runtime/src/nvn/nvn_written.cpp', 'void apply_write_back('),
                                    ('runtime/src/frame_stats.cpp', 'uint64_t thread_cpu_ns()')]:
                applied = (source / path).read_text()
                if 'nvn_written' in path:
                    # The following resident overlay adds accounting to this function. Its combined
                    # scalar/SIMD byte contract executes in test_astral_windows_resident.
                    self.assertIn(signature, applied)
                    self.assertIn('_mm256_maskstore_epi32', applied)
                else:
                    self.assertIn(function(path, signature), applied)


if __name__ == '__main__':
    unittest.main()
