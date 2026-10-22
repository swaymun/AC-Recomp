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


DESKTOP_FIXTURE = r'''
#include <cassert>
#include <cstdio>
#include <fstream>
#include <nx/runtime.h>
#include "input_map.cpp"
#include "launcher.cpp"
namespace nx {
void log(const char*, ...) {}
namespace plat {
std::string data_root() { return "fixture-data"; }
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
bool headless() { return false; }
}}
int main(int argc, char** argv) {
 using namespace nx;
 if (argc > 1 && std::string(argv[1]) == "--child-minus-one") return -1;
 if (argc > 1 && std::string(argv[1]) == "--reexec-test") {
     launcher::reexec(argv[2], "exit forwarding regression");
     std::puts("FAIL: reexec fell back after child exit");
     return 42;
 }
 input::Settings s;
 assert(input::save_settings(s)); s.fullscreen=true; s.fps=60;
 assert(input::save_settings(s)); assert(input::load_settings()==s);
 auto c=input::default_controls(); assert(input::save_controls(c));
 c.pad[input::kActA]={{input::Source::kButton,1,SDL_GAMEPAD_BUTTON_SOUTH}};
 assert(input::save_controls(c));
 std::string text; assert(input::read_file(input::controls_path(),text)); assert(input::parse_controls(text)==c);
 std::string self=launcher::self_exe(); assert(!self.empty()); assert(launcher::running_fps(self)==30);
 auto other=std::filesystem::u8path(self); other.replace_filename("desktop_fixture-60fps.exe");
 std::ofstream(other).put('x');
 auto variant=launcher::fps_variant(self,true); assert(!variant.empty()); assert(launcher::running_fps(variant)==60);
 assert(launcher::fps_variant(variant,false)==self);
 setenv("NX_VALIDATION_ENV","first",1); setenv("NX_VALIDATION_ENV","second",0);
 assert(std::string(std::getenv("NX_VALIDATION_ENV"))=="first");
 setenv("NX_VALIDATION_ENV","second",1); assert(std::string(std::getenv("NX_VALIDATION_ENV"))=="second");
 std::puts("PASS native Windows: repeated settings/controls save, reload, .exe variants and environment precedence");
}
'''


class WindowsSeriesTest(unittest.TestCase):
    def test_windows_series_is_the_linux_series_then_the_windows_overlays(self):
        linux = acr.read_series(PATCHES / 'series.linux')
        windows = acr.read_series(PATCHES / 'series.windows')
        from test_astral_shader_cache import WINDOWS_ORDER
        self.assertEqual(windows, list(WINDOWS_ORDER))
        self.assertEqual(windows[:len(linux)], linux)


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


class WindowsDesktopTest(unittest.TestCase):
    def test_composed_xinput_mapping_and_persistence(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not (reference / '.git').exists():
            self.skipTest('private pinned upstream reference unavailable')
        from test_astral_perf_hud import sdl_include
        from test_astral_launcher import sdl_lib
        inc = sdl_include()
        lib = sdl_lib(inc) if inc else None
        if not inc or not lib or sys.platform == 'win32':
            self.skipTest('portable CPU fixture requires c++ and SDL3; native Windows build checked separately')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source'
            runtime.prepare_source(reference, source, [PATCHES / n for n in acr.read_series(PATCHES / 'series.windows')])
            host = (source / 'runtime/src/platform_win.cpp').read_text()
            block = host.split('    input::Frame frame;', 1)[1].split('    bool keys[SDL_SCANCODE_COUNT]', 1)[0]
            guard_start = host.index('    // Headless test runs')
            guard_end = host.index('\n', host.index('    if (headless() ||', guard_start)) + 1
            audio_guard = host[guard_start:guard_end]
            fixture = r"""
#include <algorithm>
#include <cstdarg>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <nx/runtime.h>
#include "input_map.cpp"
namespace nx {
void log(const char*, ...) {}
namespace plat {
std::string data_root() { return "."; }
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
}}
using namespace nx;
using WORD = unsigned short;
using DWORD = unsigned long;
constexpr int ERROR_SUCCESS=0, XUSER_MAX_COUNT=4;
constexpr WORD XINPUT_GAMEPAD_DPAD_UP=1, XINPUT_GAMEPAD_DPAD_DOWN=2,
 XINPUT_GAMEPAD_DPAD_LEFT=4, XINPUT_GAMEPAD_DPAD_RIGHT=8, XINPUT_GAMEPAD_START=16,
 XINPUT_GAMEPAD_BACK=32, XINPUT_GAMEPAD_LEFT_THUMB=64, XINPUT_GAMEPAD_RIGHT_THUMB=128,
 XINPUT_GAMEPAD_LEFT_SHOULDER=256, XINPUT_GAMEPAD_RIGHT_SHOULDER=512,
 XINPUT_GAMEPAD_A=4096, XINPUT_GAMEPAD_B=8192, XINPUT_GAMEPAD_X=16384, XINPUT_GAMEPAD_Y=32768;
struct XINPUT_GAMEPAD { WORD wButtons{}; unsigned char bLeftTrigger{},bRightTrigger{};
 short sThumbLX{},sThumbLY{},sThumbRX{},sThumbRY{}; } pad;
struct XINPUT_STATE { unsigned packet{}; XINPUT_GAMEPAD Gamepad; };
int XInputGetState(DWORD slot, XINPUT_STATE* s) {
 if (slot != 0 && slot != 2) return 1167;
 s->Gamepad=slot==0 ? XINPUT_GAMEPAD{} : pad; return ERROR_SUCCESS;
}
input::Frame sample() { input::Frame frame; @BLOCK@ return frame; }
bool test_headless=false;
bool headless() { return test_headless; }
bool audio_enabled() { @AUDIO_GUARD@ return true; }
int main() {
 unsetenv("NX_MUTE"); assert(audio_enabled());
 setenv("NX_MUTE","0",1); assert(audio_enabled());
 setenv("NX_MUTE","",1); assert(audio_enabled());
 setenv("NX_MUTE","1",1); assert(!audio_enabled());
 unsetenv("NX_MUTE"); test_headless=true; assert(!audio_enabled()); test_headless=false;
 auto controls=input::default_controls();
 const WORD masks[]={4096,8192,16384,32768,256,512,16,32,64,128,1,2,4,8};
 const uint64_t bits[]={plat::kB,plat::kA,plat::kY,plat::kX,plat::kL,plat::kR,
 plat::kPlus,plat::kMinus,plat::kStickL,plat::kStickR,plat::kUp,plat::kDown,plat::kLeft,plat::kRight};
 for (unsigned i=0;i<std::size(masks);i++) { pad={}; pad.wButtons=masks[i];
   auto frame=sample(); assert(frame.has_pad); assert(input::map(controls,frame).buttons==bits[i]); }
 pad={}; pad.sThumbLY=-32768; pad.sThumbRY=32767; pad.sThumbLX=32767; pad.sThumbRX=-32768;
 pad.bLeftTrigger=255; pad.bRightTrigger=255;
 auto p=input::map(controls,sample());
 assert(p.ly<0 && p.ry>0 && p.lx>0 && p.rx<0); assert(p.buttons & plat::kZL); assert(p.buttons & plat::kZR);
 controls.pad[input::kActA]={{input::Source::kButton,1,SDL_GAMEPAD_BUTTON_SOUTH}};
 controls.pad[input::kActB].clear(); pad={}; pad.wButtons=4096;
 assert(input::map(controls,sample()).buttons==plat::kA);
 assert(input::save_controls(controls));
 auto parsed=input::parse_controls(input::write_controls(controls)); assert(parsed==controls);
 input::Settings settings; assert(input::save_settings(settings)); settings.fullscreen=true;
 assert(input::save_settings(settings)); assert(input::load_settings().fullscreen);
 std::puts("PASS: XInput slot 2 with idle slot 0, all buttons, stick polarity/extremes, triggers, remap and repeated settings save");
}
""".replace('@BLOCK@', block).replace('@AUDIO_GUARD@', audio_guard)
            path = Path(d) / 'fixture.cpp'
            path.write_text(fixture)
            exe = Path(d) / 'fixture'
            cmd = [shutil.which('c++'), '-std=c++20', '-DNX_ASTRAL_STRICT=1', '-I'+str(inc),
                   '-I'+str(source/'runtime/src'), '-I'+str(source/'runtime/include'), str(path), '-L'+str(lib), '-lSDL3', '-o', str(exe)]
            built = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
            result = subprocess.run([str(exe)], cwd=d, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PASS: XInput slot 2', result.stdout)
            text=(PATCHES/'astral-windows-desktop.patch').read_text()
            self.assertIn('return _putenv_s(name, value)', text)
            self.assertIn('_wspawnv(_P_NOWAIT', text)
            self.assertIn('p.extension().string()', text)


class WindowsFiberTest(unittest.TestCase):
    def test_native_windows_settings_and_variant_paths(self):
        if sys.platform != 'win32':
            self.skipTest('needs a Windows x64 host')
        inc = Path(os.environ.get('NX_SDL3_INCLUDE', 'missing'))
        lib = Path(os.environ.get('NX_SDL3_LIB', 'missing'))
        cxx = shutil.which('clang-cl')
        if not cxx or not (inc/'SDL3/SDL.h').is_file() or not (lib/'SDL3.lib').is_file():
            self.skipTest('needs clang-cl and NX_SDL3_INCLUDE / NX_SDL3_LIB (DLL on PATH)')
        reference = Path(os.environ.get('NVN_REFERENCE', 'missing'))
        if not (reference/'.git').exists():
            self.skipTest('needs the private pinned upstream reference')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)/'source'
            runtime.prepare_source(reference, source, [PATCHES/n for n in acr.read_series(PATCHES/'series.windows')])
            path = Path(d)/'desktop_fixture.cpp'
            path.write_text(DESKTOP_FIXTURE)
            exe = Path(d)/'desktop_fixture.exe'
            built = subprocess.run([cxx, '/nologo', '/std:c++20', '/EHsc', '/UNDEBUG', '/DNX_ASTRAL_STRICT=1',
                '/DNOMINMAX', '/D_CRT_SECURE_NO_WARNINGS', '/I'+str(inc), '/I'+str(source/'runtime/src'),
                '/I'+str(source/'runtime/include'), str(path), '/Fe'+str(exe), '/Fo'+str(Path(d)/'fixture.obj'),
                '/link', str(lib/'SDL3.lib'), 'shell32.lib'], capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
            result = subprocess.run([str(exe)], cwd=d, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PASS native Windows', result.stdout)
            child = Path(d)/'exit-minus-one.exe'
            shutil.copy2(exe, child)
            # own_args is retained across reexec: the probe child must ignore the parent's arguments.
            child_cpp = Path(d)/'child.cpp'
            child_cpp.write_text(r'''#include <string>
int main(int n,char** a){
 if(n != 5 || std::string(a[1]) != "--reexec-test" || std::string(a[3]) != "space and quote\"" || std::string(a[4]) != "tail\\") return 23;
 return -1;
}
''')
            built = subprocess.run([cxx,'/nologo',str(child_cpp),'/Fe'+str(child),'/Fo'+str(Path(d)/'child.obj')],
                                   capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            # The installation path and arguments must survive UTF-8 -> UTF-16 and CRT quoting.
            unicode_dir = Path(d)/'player space-\u96ea'
            unicode_dir.mkdir()
            unicode_exe = unicode_dir/exe.name
            shutil.copy2(exe, unicode_exe)
            result = subprocess.run([str(unicode_exe)], cwd=d, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            forwarded = subprocess.run([str(unicode_exe),'--reexec-test',str(child),'space and quote"','tail\\'],cwd=d,capture_output=True,text=True,timeout=30)
            self.assertEqual(forwarded.returncode & 0xffffffff,0xffffffff,forwarded.stdout+forwarded.stderr)
            self.assertNotIn('fell back',forwarded.stdout)

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
