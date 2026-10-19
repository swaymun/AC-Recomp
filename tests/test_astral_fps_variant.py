"""CPU regression of the frame-rate overlay (astral-fps-variant.patch, docs/ASTRAL_60FPS.md "In-app setting").

The overlay is applied last, after astral-controls-ui.patch, on a fresh copy of the pinned public runtime. The
production input_map.cpp and launcher.cpp are compiled with a fixture: settings.ini's fps round-trips (30 by default,
anything but 60 reads as 30), 60 is exported as NX_FPS unless the environment sets it, the Settings screen's Frame rate
row toggles (and only says why when the build has one binary), window sizes are labelled relative to the render
size (1600x900, or NX_NATIVE_RES), fps_variant maps astral <-> astral-60fps only when the
sibling is executable, and reexec replaces the process with the other binary, same arguments, NX_SKIP_LAUNCHER=1. The
CMake block that adds astral-60fps is built in a small project of its own (when cmake is available): the variant links
the base executable's objects and the base main's objects except the replaced file, and only that file compiles
again. No game, GPU, window or device is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime  # noqa: E402
import test_astral_controls_ui as previous  # noqa: E402
from test_astral_launcher import sdl_lib  # noqa: E402
from test_astral_perf_hud import sdl_include, vulkan_include  # noqa: E402
import test_astral_shared_font as font  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the controls-UI overlay's, then this overlay last.
OVERLAY = 'astral-fps-variant.patch'
ORDER = (*previous.ORDER, OVERLAY)
MODIFIED = ['CMakeLists.txt', 'runtime/src/input_map.cpp', 'runtime/src/input_map.h', 'runtime/src/launcher.cpp',
            'runtime/src/launcher.h', 'runtime/src/loader.cpp', 'runtime/src/platform_mac.cpp']
CMAKE_MARK = '# Astral, SDL3 desktop hosts: a second executable'

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <nx/runtime.h>
#include "platform.h"
namespace nx {
void log(const char*, ...) {}
namespace plat {
std::string data_root() { const char* r = std::getenv("NX_DATA_ROOT"); return r ? r : "."; }
bool headless() { return true; }
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
}  // namespace plat
}  // namespace nx
#include "input_map.cpp"
#include "launcher.cpp"
#define CHECK(...) do { if (!(__VA_ARGS__)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #__VA_ARGS__); std::abort(); } } while (0)
namespace fs = std::filesystem;
using namespace nx;
using launcher::Event;
using launcher::Nav;

Event nav(Nav n) { Event e; e.kind = Event::kNav; e.nav = n; return e; }

int main(int argc, char** argv) {
    std::string mode = argv[1];
    fs::path dir = argc > 2 ? fs::path(argv[2]) : fs::path(".");
    if (mode == "settings") {
        CHECK(input::Settings().fps == 30);
        CHECK(input::parse_settings("[settings]\nfps = 60\n").fps == 60);
        CHECK(input::parse_settings("fps = 45\n").fps == 30);
        CHECK(input::parse_settings("fps = 60\nfps = 30\n").fps == 30);
        input::Settings s;
        CHECK(input::write_settings(s).find("fps = 30\n") != std::string::npos);
        s.fps = 60;
        CHECK(input::parse_settings(input::write_settings(s)) == s);
        CHECK(input::setting_text(s, input::kSetFps) == "60 (experimental)");
        CHECK(std::string(input::setting_key(input::kSetFps)) == "fps");
        CHECK(std::string(input::setting_env(input::kSetFps)) == "NX_FPS");
        CHECK(input::env_effect(input::kSetFps, "60") == "60 (experimental)");
        CHECK(input::env_effect(input::kSetFps, "30") == "30");
        CHECK(input::resolution_label("1600x900") == "1600x900 (Native)");
        CHECK(input::resolution_label("3200x1800") == "3200x1800 (2x)");
        CHECK(input::resolution_label("2560x1440") == "2560x1440 (1.6x)");
        CHECK(input::resolution_label("1920x1080") == "1920x1080 (1.2x)");
        CHECK(input::resolution_label("3840x2160") == "3840x2160 (2.4x)");
        CHECK(input::resolution_label("1280x720") == "1280x720 (0.8x)");
        CHECK(input::resolution_label("junk") == "junk");
        input::Settings r;
        CHECK(input::setting_text(r, input::kSetResolution) == "1280x720 (0.8x)");
        CHECK(input::env_effect(input::kSetResolution, "1600x900") == "1600x900 (Native)");
        setenv("NX_NATIVE_RES", "2560x1440", 1);  // a --render-res build
        CHECK(input::resolution_label("2560x1440") == "2560x1440 (Native)");
        CHECK(input::resolution_label("1280x720") == "1280x720 (0.5x)");
        unsetenv("NX_NATIVE_RES");
        std::printf("PASS settings: fps round-trips through settings.ini (default 30); window sizes labelled "
                    "relative to the render size\n");
        return 0;
    }
    if (mode == "export") {
        input::Settings s;
        s.fps = 60;
        input::export_env(s);
        const char* v = std::getenv("NX_FPS");
        std::printf("NX_FPS=%s\n", v ? v : "(unset)");
        return 0;
    }
    if (mode == "menu") {
        launcher::Menu m;
        m.handle(nav(Nav::Down), 0);
        m.handle(nav(Nav::Down), 0);
        m.handle(nav(Nav::Confirm), 0);  // SETTINGS
        CHECK(m.screen == launcher::Screen::Settings);
        for (int i = 0; i < input::kSetFps; i++) m.handle(nav(Nav::Down), 0);
        CHECK(m.cells()[input::kSetFps][0] == "Frame rate" && m.cells()[input::kSetFps][1] == "30");
        m.handle(nav(Nav::Right), 0);
        CHECK(m.settings.fps == 60 && m.settings_dirty && m.cells()[input::kSetFps][1] == "60 (experimental)");
        m.handle(nav(Nav::Left), 0);
        CHECK(m.settings.fps == 30);
        launcher::Menu one;
        one.fps_variants = false;
        one.running_fps = 60;  // a --fps 60 build; settings.ini still says 30
        one.handle(nav(Nav::Down), 0);
        one.handle(nav(Nav::Down), 0);
        one.handle(nav(Nav::Confirm), 0);
        for (int i = 0; i < input::kSetFps; i++) one.handle(nav(Nav::Down), 0);
        one.handle(nav(Nav::Right), 0);
        CHECK(one.settings.fps == 30 && one.notice.find("60 fps only") != std::string::npos);
        CHECK(one.cells()[input::kSetFps][1] == "60 (this build)");  // the running rate, not the stale setting
        one.running_fps = 30;
        one.settings.fps = 60;
        CHECK(one.cells()[input::kSetFps][1] == "30 (this build)");
#if !defined(NX_SINGLE_FPS)
        CHECK(launcher::running_fps("/x/astral-60fps") == 60 && launcher::running_fps("/x/astral") == 30);
#else
        CHECK(launcher::running_fps("/x/astral") == NX_SINGLE_FPS);
#endif
        std::printf("PASS menu: the Frame rate row toggles 30/60; a one-rate build says why it cannot\n");
        return 0;
    }
    if (mode == "variant") {
        std::string a = (dir / "astral").string(), b = (dir / "astral-60fps").string();
        CHECK(launcher::fps_variant(a, false) == a);
        CHECK(launcher::fps_variant(a, true) == b);
        CHECK(launcher::fps_variant(b, true) == b);
        CHECK(launcher::fps_variant(b, false) == a);
        CHECK(launcher::fps_variant(a + "-missing", true).empty());
        CHECK(launcher::fps_variant("", true).empty());
        fs::permissions(b, fs::perms::owner_exec | fs::perms::group_exec | fs::perms::others_exec,
                        fs::perm_options::remove);
        CHECK(launcher::fps_variant(a, true).empty());  // not executable: stay
        CHECK(!launcher::self_exe().empty() && fs::path(launcher::self_exe()).filename() == "run");
        std::printf("PASS variant: astral <-> astral-60fps only when the sibling is executable\n");
        return 0;
    }
    if (mode == "reexec") {
        launcher::reexec((dir / "astral-60fps").string(), "test");
        std::printf("returned\n");  // only when the exec failed
        return 3;
    }
    return 2;
}
'''


def run_cmake_block(test, cmake, block, work):
    """The overlay's CMake block in a small project: game_main (two files), the base executable and the variant."""
    work.mkdir()
    gen, var = work / 'gen/main', work / 'gen-60fps/main'
    gen.mkdir(parents=True)
    var.mkdir(parents=True)
    (gen / 'code_000.cpp').write_text('int f0() { return 1; }\n')
    (gen / 'code_001.cpp').write_text('int f1() { return 10; }\n')
    (var / 'code_000.cpp').write_text('int f0() { return 1; }\n')
    (var / 'code_001.cpp').write_text('int f1() { return 20; }\n')
    (work / 'main.cpp').write_text('#include <cstdio>\nint f0();\nint f1();\nint main() { std::printf("%d\\n", '
                                   'f0() + f1()); }\n')
    (work / 'variant.list').write_text(f'dir {var}\ncompile code_001.cpp\nexclude code_001.cpp\n')
    (work / 'CMakeLists.txt').write_text(
        'cmake_minimum_required(VERSION 3.20)\nproject(t CXX)\nset(NX_GAME astral)\n'
        f'add_library(game_main STATIC {gen}/code_000.cpp {gen}/code_001.cpp)\n'
        'target_compile_options(game_main PRIVATE -O2)\n'
        'add_executable(astral main.cpp)\ntarget_link_libraries(astral PRIVATE game_main)\n' + block)
    gen_args = ['-G', 'Ninja', f'-DCMAKE_MAKE_PROGRAM={shutil.which("ninja")}'] if shutil.which('ninja') else []
    cfg = subprocess.run([cmake, '-S', str(work), '-B', str(work / 'b'), *gen_args,
                          f'-DNX_MAIN_VARIANT_LIST={work / "variant.list"}'], capture_output=True, text=True,
                         timeout=120)
    test.assertEqual(cfg.returncode, 0, cfg.stdout + cfg.stderr)
    b = subprocess.run([cmake, '--build', str(work / 'b'), '--target', 'astral', 'astral-60fps', '--verbose'],
                       capture_output=True, text=True, timeout=300)
    test.assertEqual(b.returncode, 0, b.stdout + b.stderr)
    test.assertEqual(subprocess.check_output([str(work / 'b/astral')], text=True), '11\n')
    test.assertEqual(subprocess.check_output([str(work / 'b/astral-60fps')], text=True), '21\n')
    compiled = [l for l in b.stdout.splitlines() if ' -c ' in l]
    test.assertEqual(sum(f'{var}/code_001.cpp' in l for l in compiled), 1)
    test.assertFalse(any(f'{var}/code_000.cpp' in l for l in compiled))  # shared, not compiled again
    test.assertEqual(sum('main.cpp' in l and 'gen' not in l for l in compiled), 1)  # the runtime objects are shared
    print('PASS cmake: astral-60fps shares the runtime and unchanged main objects; only the changed file compiles')


class AstralFpsVariantTests(unittest.TestCase):
    def test_cmake_block_in_a_small_project(self):
        cmake = os.environ.get('CMAKE') or shutil.which('cmake')
        if not cmake:
            self.skipTest('cmake is absent')
        text = (ROOT / 'runtime/patches' / OVERLAY).read_text().split('+++ b/CMakeLists.txt')[1]
        hunk = text.split('\ndiff --git')[0]
        block = '\n'.join(l[1:] for l in hunk.splitlines() if l.startswith('+'))
        self.assertIn(CMAKE_MARK, block)
        with tempfile.TemporaryDirectory() as d:
            run_cmake_block(self, cmake, block[block.index(CMAKE_MARK):] + '\n', Path(d) / 'p')

    def test_overlay_settings_menu_variant_and_reexec(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        vulkan = vulkan_include()
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        common = common if common.is_absolute() else (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(
            common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not reference.is_dir():
            self.skipTest('the private pinned upstream is absent')
        sdl = sdl_include()
        lib = sdl_lib(sdl) if sdl else None
        if not (sdl and lib):
            self.skipTest('SDL3 is absent')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        source = out / 'source'
        runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in ORDER[:-1]])
        stacked = runtime.source_fingerprint(source)
        font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         sorted(MODIFIED))
        src = source / 'runtime/src'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(src), '-I', str(vulkan)]
        work = out / 'fixture'
        work.mkdir()
        (work / 'fixture.cpp').write_text(FIXTURE)
        build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wno-unused-parameter', '-DNX_ASTRAL_STRICT=1',
                                *includes, '-I', sdl, str(work / 'fixture.cpp'), '-L', lib, '-lSDL3',
                                '-Wl,-rpath,' + lib, '-o', str(work / 'run')], capture_output=True, text=True,
                               timeout=240)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('NX_', 'MTL_'))}

        def run(*args, env=None, code=0):
            r = subprocess.run([str(work / 'run'), *args], cwd=work, capture_output=True, text=True, timeout=60,
                               env={**clean, **(env or {})})
            self.assertEqual(r.returncode, code, ' '.join(args) + ': ' + r.stdout + r.stderr)
            print(''.join(l + '\n' for l in r.stdout.splitlines() if l.startswith('PASS')), end='')
            return r.stdout

        run('settings')
        run('menu')
        self.assertIn('NX_FPS=60', run('export'))
        self.assertIn('NX_FPS=30', run('export', env={'NX_FPS': '30'}))  # the environment wins
        bins = out / 'bin'
        bins.mkdir()
        for name in ('astral', 'astral-60fps'):
            (bins / name).write_text('#!/bin/sh\necho "ran $0 args:$* skip:$NX_SKIP_LAUNCHER/$NX_REEXEC '
                                     'hud:${MTL_HUD_ENABLED:-}"\n')
            (bins / name).chmod(0o755)
        got = run('reexec', str(bins), env={'NX_METAL_HUD_AUTO': '1', 'MTL_HUD_ENABLED': '1'})
        self.assertEqual(got, f'ran {bins / "astral-60fps"} args:reexec {bins} skip:1/1 hud:\n')
        got = run('reexec', str(bins), env={'MTL_HUD_ENABLED': '1'})  # the player's own setting stays
        self.assertIn('skip:1/1 hud:1', got)
        print('PASS reexec: the other binary, same arguments, NX_SKIP_LAUNCHER=1, an automatic Metal HUD decided again')
        run('variant', str(bins))

        launcher = (src / 'launcher.cpp').read_text()
        start = launcher.split('bool start() {')[1]
        self.assertIn('if (!want.empty() && want != self) reexec(want, want60 ? "60 fps" : "30 fps");', start)
        self.assertIn('setenv("NX_METAL_HUD_AUTO", "1", 1);', (src / 'platform_mac.cpp').read_text())
        # The re-exec continues the session: nx.log is appended (NX_REEXEC), as after a Metal HUD restart.
        log = (src / 'loader.cpp').read_text()
        self.assertIn('const bool restarted = on("NX_METAL_HUD_RESTARTED") || on("NX_REEXEC");', log)
        self.assertIn('g_log_file = std::fopen(file.c_str(), restarted ? "a" : "w");', log)
        # A one-rate build compiles its rate into the launcher (acr_build passes NX_SINGLE_FPS).
        cmake = (source / 'CMakeLists.txt').read_text()
        self.assertIn('APPEND PROPERTY COMPILE_DEFINITIONS NX_SINGLE_FPS=${NX_SINGLE_FPS})', cmake)
        single = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wno-unused-parameter', '-DNX_ASTRAL_STRICT=1',
                                 '-DNX_SINGLE_FPS=60', *includes, '-I', sdl, str(work / 'fixture.cpp'), '-L', lib,
                                 '-lSDL3', '-Wl,-rpath,' + lib, '-o', str(work / 'run60')], capture_output=True,
                                text=True, timeout=240)
        self.assertEqual(single.returncode, 0, single.stdout + single.stderr)
        r = subprocess.run([str(work / 'run60'), 'menu'], cwd=work, capture_output=True, text=True, timeout=60,
                           env=clean)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        print('PASS one-rate build: the Frame rate row shows the running rate (NX_SINGLE_FPS); nx.log appended '
              'after a re-exec')
        for flags in (['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1'], []):
            for name in ('input_map.cpp', 'launcher.cpp'):
                check = subprocess.run([compiler, '-std=c++20', *flags, *includes, '-I', sdl, '-fsyntax-only',
                                        str(src / name)], capture_output=True, text=True, timeout=120)
                self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        print('PASS strict (Mac profile) and default syntax: input_map.cpp, launcher.cpp')
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-fps-variant.patch')


if __name__ == '__main__':
    unittest.main()
