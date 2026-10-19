"""CPU regression of the save-profile overlay (astral-save-profiles.patch, docs/ASTRAL_LAUNCHER.md "Save profiles").

The overlay is applied last, after astral-upscale.patch, on a fresh copy of the pinned public runtime. The production
save_profile.h is compiled with a fixture that checks the path mapping (Default is <data root>/user/save; every other
profile <data root>/user/profiles/<name>/save, never outside the data root), name validation, the listing of a
temporary data root (symlinked or invalid folders ignored, last-modified times) and the next free "Profile N" name.
The production input_map.cpp and launcher.cpp are compiled too: PLAY opens the picker on the profile used last,
choosing one saves it to settings.ini and starts, New profile adds one, Back returns, mouse clicks pick rows, and
a valid NX_SAVE_PROFILE in the environment skips the
picker (an invalid one is warned about and replaced by the choice). hle_fs.cpp's MountSaveData reads NX_SAVE_PROFILE through
save_profile.h. The changed translation units get strict syntax checks, and the default profile's preprocessed
hle_fs.cpp must be unchanged. No game, GPU, window or device is used.
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
import test_astral_upscale as upscale  # noqa: E402
from test_astral_launcher import sdl_lib  # noqa: E402
from test_astral_perf_hud import sdl_include, vulkan_include  # noqa: E402
from test_nvn_window_depth import preprocessed  # noqa: E402
import test_astral_shared_font as font  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the upscale overlay's, then this overlay last.
OVERLAY = 'astral-save-profiles.patch'
ORDER = (*upscale.ORDER, OVERLAY)
NEW = ['runtime/src/save_profile.h']
MODIFIED = ['runtime/src/hle_fs.cpp', 'runtime/src/input_map.cpp', 'runtime/src/input_map.h', 'runtime/src/launcher.cpp',
            'runtime/src/launcher.h']

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
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
using launcher::Screen;
using launcher::Result;

Event nav(Nav n) { Event e; e.kind = Event::kNav; e.nav = n; return e; }

void touch(const fs::path& p) {
    fs::create_directories(p.parent_path());
    std::ofstream(p) << "x";
}

int main(int argc, char** argv) {
    std::string mode = argv[1];
    fs::path root = argc > 2 ? fs::path(argv[2]) : fs::path(".");
    if (mode == "paths") {
        CHECK(saves::save_dir(root, "Default") == root / "user" / "save");
        CHECK(saves::save_dir(root, "default") == root / "user" / "save");
        CHECK(saves::save_dir(root, "") == root / "user" / "save");
        CHECK(saves::save_dir(root, "Alex 2") == root / "user" / "profiles" / "Alex 2" / "save");
        for (const char* bad : {"..", ".", "../x", "a/b", "a\\b", "/abs", " lead", "trail ", "C:", "a:b", "x.y",
                                "\xc3\xa9", "0123456789012345678901234567890123"}) {
            CHECK(!saves::valid_name(bad));
            CHECK(saves::normalise(bad) == "Default");
            CHECK(saves::save_dir(root, bad) == root / "user" / "save");  // never outside the data root
        }
        for (const char* good : {"Alex", "Profile 2", "speed-run_1", "a", "01234567890123456789012345678901"})
            CHECK(saves::valid_name(good) && saves::normalise(good) == good);
        CHECK(saves::normalise(nullptr) == "Default");
        std::cout << "PASS paths: Default is user/save, others user/profiles/<name>/save; bad names are Default\n";
        return 0;
    }
    if (mode == "list") {  // root: an empty temporary data root
        auto l = saves::list(root);
        CHECK(l.size() == 1 && l[0].name == "Default" && l[0].modified == 0);
        CHECK(saves::modified_text(0) == "No saves yet");
        touch(root / "user/save/SlotData_0.dat");
        touch(root / "user/profiles/Zed/save/GameData.dat");
        fs::create_directories(root / "user/profiles/Alex/save");
        fs::create_directories(root / "user/profiles/bad.name/save");
        fs::create_directories(root / "user/profiles/default/save");  // Default is user/save only
        fs::create_directories(root / "elsewhere/save");
        fs::create_directory_symlink(root / "elsewhere", root / "user/profiles/Linked");
        touch(root / "user/profiles/file");
        l = saves::list(root);
        CHECK(l.size() == 3 && l[0].name == "Default" && l[1].name == "Alex" && l[2].name == "Zed");
        CHECK(l[0].modified > 1600000000 && l[1].modified == 0 && l[2].modified > 1600000000);
        CHECK(saves::modified_text(l[0].modified).rfind("Last played 20", 0) == 0);
        CHECK(saves::next_name(l) == "Profile 2");
        l.push_back({"profile 2", 0});
        CHECK(saves::next_name(l) == "Profile 3");
        std::cout << "PASS list: Default first, valid folders by name, links and bad names skipped, times\n";
        return 0;
    }
    if (mode == "settings") {
        input::Settings s;
        CHECK(s.save_profile == "Default");
        CHECK(input::write_settings(s).find("save_profile = Default\n") != std::string::npos);
        s.save_profile = "Alex 2";
        CHECK(input::parse_settings(input::write_settings(s)) == s);
        CHECK(input::parse_settings("save_profile = ../../x\n").save_profile == "Default");
        unsetenv("NX_SAVE_PROFILE");
        input::export_env(input::Settings());
        CHECK(std::string(std::getenv("NX_SAVE_PROFILE")) == "Default");  // Default too: a restart keeps it
        unsetenv("NX_SAVE_PROFILE");
        input::export_env(s);
        CHECK(std::string(std::getenv("NX_SAVE_PROFILE")) == "Alex 2");
        setenv("NX_SAVE_PROFILE", "Mine", 1);
        input::export_env(s);
        CHECK(std::string(std::getenv("NX_SAVE_PROFILE")) == "Mine");  // the environment wins
        std::cout << "PASS settings: save_profile round-trips, bad names read as Default, always exported unless set\n";
        return 0;
    }
    if (mode == "menu") {
        launcher::Menu m;
        m.profiles = {{"Default", 0}, {"Alex", 5}, {"Zed", 0}};
        m.settings.save_profile = "Zed";
        m.handle(nav(Nav::Confirm), 0);  // PLAY
        CHECK(m.screen == Screen::Profiles && m.cursor == 2 && m.result == Result::None);  // on the last used
        CHECK(m.count() == 5);
        auto cells = m.cells();
        CHECK(cells[0][0] == "Default" && cells[1][1].rfind("Last played", 0) == 0 && cells[2][1] == "No saves yet");
        CHECK(cells[3][0] == "New profile" && cells[4][0] == "Back");
        m.handle(nav(Nav::Back), 0);
        CHECK(m.screen == Screen::Main && m.cursor == 0 && m.result == Result::None);
        m.handle(nav(Nav::Confirm), 0);
        m.handle(nav(Nav::Down), 0);
        m.handle(nav(Nav::Down), 0);
        m.handle(nav(Nav::Down), 0);  // wraps past Back to Default
        CHECK(m.cursor == 0);
        m.handle(nav(Nav::Up), 0);
        m.handle(nav(Nav::Up), 0);  // New profile
        CHECK(m.cursor == 3);
        m.handle(nav(Nav::Confirm), 0);
        CHECK(m.profiles.size() == 4 && m.profiles[3].name == "Profile 2" && m.cursor == 3 && m.result == Result::None);
        CHECK(!m.settings_dirty);
        m.handle(nav(Nav::Confirm), 0);  // play with it
        CHECK(m.result == Result::Start && m.settings.save_profile == "Profile 2" && m.settings_dirty);
        // The mouse: a click on a row picks it.
        launcher::Menu c;
        c.profiles = {{"Default", 0}, {"Alex", 0}};
        c.handle(nav(Nav::Confirm), 0);
        CHECK(c.screen == Screen::Profiles && c.cursor == 0);
        SDL_FRect r = c.row_rect(1);
        Event click;
        click.kind = Event::kClick, click.x = r.x + 5, click.y = r.y + 5;
        c.handle(click, 0);
        CHECK(c.result == Result::Start && c.settings.save_profile == "Alex");
        // Back on the last row; Back key.
        launcher::Menu b;
        b.handle(nav(Nav::Confirm), 0);
        b.handle(nav(Nav::Up), 0);
        b.handle(nav(Nav::Confirm), 0);
        CHECK(b.screen == Screen::Main && b.result == Result::None);
        // NX_SAVE_PROFILE set: PLAY starts at once.
        launcher::Menu e;
        e.profile_env = true;
        e.handle(nav(Nav::Confirm), 0);
        CHECK(e.result == Result::Start && e.screen == Screen::Main);
        // Many profiles scroll.
        launcher::Menu s;
        for (int k = 2; k < 20; k++) s.profiles.push_back({"P" + std::to_string(k), 0});
        s.settings.save_profile = "P19";
        s.handle(nav(Nav::Confirm), 0);
        CHECK(s.cursor == 18 && s.row_rect(18).w > 0 && s.row_rect(0).w == 0);
        std::cout << "PASS menu: picker on the last used, choose/new/back, mouse, scroll, NX_SAVE_PROFILE skips it\n";
        return 0;
    }
    return 1;
}
'''


class AstralSaveProfilesTests(unittest.TestCase):
    def test_overlay_paths_picker_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        vulkan = vulkan_include()
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required; no downloads')
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
        patch = font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         sorted(NEW + MODIFIED))
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
        clean = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
        data = out / 'data'
        data.mkdir()
        for mode in ('paths', 'list', 'settings', 'menu'):
            r = subprocess.run([str(work / 'run'), mode, str(data)], cwd=work, capture_output=True, text=True,
                               timeout=60, env=clean)
            self.assertEqual(r.returncode, 0, mode + ': ' + r.stdout + r.stderr)
            self.assertIn('PASS', r.stdout)
            print(r.stdout, end='')

        # The runtime: MountSaveData maps the profile through save_profile.h and keeps the beneath() confinement.
        fs_src = (src / 'hle_fs.cpp').read_text()
        mount = fs_src.split('void MountSaveData(CPU& c) {')[1].split('\n}\n')[0]
        strict = mount.split('#if defined(NX_ASTRAL_STRICT)')[1].split('#else')[0]
        self.assertIn('const char* requested = std::getenv("NX_SAVE_PROFILE");', strict)
        self.assertIn('saves::normalise(requested)', strict)
        self.assertIn('saves::save_dir(root, profile)', strict)
        self.assertIn('if (ec || !beneath(root, p)) { c.x[0] = kPathNotFound; return; }', mount.split('#endif')[1])
        # The launcher lists the profiles and honours NX_SAVE_PROFILE.
        start = (src / 'launcher.cpp').read_text().split('bool start() {')[1]
        self.assertIn('m.profiles = saves::list(plat::data_root());', start)
        # Only a valid NX_SAVE_PROFILE skips the picker; an invalid one warns, shows it, and the choice replaces it.
        self.assertIn('m.profile_env = chosen && saves::valid_name(chosen);', start)
        self.assertIn('m.notice = "NX_SAVE_PROFILE is not a valid profile name: choose a profile";', start)
        self.assertIn('if (!m.profile_env) setenv("NX_SAVE_PROFILE", s.save_profile.c_str(), 1);', start)
        self.assertLess(start.index('setenv("NX_SAVE_PROFILE"'), start.index('input::export_env(s);'))
        self.assertIn('is not a valid profile name (letters, digits, space, - or _, up to 32): Default', strict)

        # Strict syntax (Mac profile) and default syntax of the changed TUs; the default profile is unchanged.
        tus = ['hle_fs.cpp', 'input_map.cpp', 'launcher.cpp']
        for flags in (['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1'], []):
            for name in tus:
                check = subprocess.run([compiler, '-std=c++20', *flags, *includes, '-I', sdl, '-fsyntax-only',
                                        str(src / name)], capture_output=True, text=True, timeout=120)
                self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        empty = subprocess.run([compiler, '-std=c++20', '-E', '-P', '-x', 'c++', *includes, str(src / 'save_profile.h')],
                               capture_output=True, text=True, timeout=60, check=True).stdout
        self.assertEqual(empty.strip(), '')
        after = preprocessed(compiler, includes, src / 'hle_fs.cpp')
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        self.assertEqual(after, preprocessed(compiler, includes, src / 'hle_fs.cpp'), 'default profile differs')
        print('PASS default profile: save_profile.h empty; hle_fs.cpp preprocesses identically')
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-save-profiles.patch')


if __name__ == '__main__':
    unittest.main()
