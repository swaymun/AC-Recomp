"""CPU regression of the CONTROLS screen overlay (astral-controls-ui.patch, docs/ASTRAL_LAUNCHER.md "CONTROLS").

The overlay is applied last, after astral-save-profiles.patch, on a fresh copy of the pinned public runtime. It changes
only launcher.{h,cpp}: input_map (the bindings model, controls.ini) is untouched. The production input_map.cpp and
launcher.cpp are compiled with a fixture that checks the layout (every Switch control exactly once in a panel, the
right-stick rows included, every item on screen at 1280x720 without scrolling, no two items overlapping, mouse hit
tests), the geometric navigation (each item reachable from the first; the expected neighbours), the tab and rebind
state machine (the selected tab's device binds, the other device / a click / the timeout cancel, reset, back), and an
offscreen software render of the real drawing code (the focused control lit on the drawn controller, at 1x and 2x,
with and without the font). Strict syntax of the changed TU in the Mac profile; the default profile preprocesses to
nothing. No game, window, GPU or device is used.
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
import test_astral_save_profiles as saves  # noqa: E402
from test_astral_launcher import sdl_lib  # noqa: E402
from test_astral_perf_hud import sdl_include, vulkan_include  # noqa: E402
import test_astral_shared_font as font  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the save-profile overlay's, then this overlay last.
OVERLAY = 'astral-controls-ui.patch'
ORDER = (*saves.ORDER, OVERLAY)
MODIFIED = ['runtime/src/launcher.cpp', 'runtime/src/launcher.h']
ASSETS = ROOT / 'assets/launcher'

FIXTURE = r'''
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <set>
#include <string>
#include <nx/runtime.h>
#include "platform.h"
namespace nx {
void log(const char*, ...) {}
namespace plat {
std::string data_root() { return "."; }
bool headless() { return true; }
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
}  // namespace plat
}  // namespace nx
#include "input_map.cpp"
#include "launcher.cpp"
#define CHECK(...) do { if (!(__VA_ARGS__)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #__VA_ARGS__); std::abort(); } } while (0)
using namespace nx;
using launcher::Event;
using launcher::Nav;
using launcher::Screen;
using launcher::ControlsTab;
using input::Source;

Event nav(Nav n) { Event e; e.kind = Event::kNav; e.nav = n; return e; }
Event at(Event::Kind k, const SDL_FRect& r) { Event e; e.kind = k; e.x = r.x + r.w / 2; e.y = r.y + r.h / 2; return e; }
bool inside(const SDL_FRect& in, const SDL_FRect& out) {
    return in.x >= out.x && in.y >= out.y && in.x + in.w <= out.x + out.w && in.y + in.h <= out.y + out.h;
}
bool overlap(const SDL_FRect& a, const SDL_FRect& b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}
launcher::Menu controls() {
    launcher::Menu m;
    m.handle(nav(Nav::Down), 0);
    m.handle(nav(Nav::Confirm), 0);  // CONTROLS
    CHECK(m.screen == Screen::Controls && m.cursor == 0);
    return m;
}

int main(int argc, char** argv) {
    std::string mode = argv[1];
    if (mode == "layout") {
        launcher::Menu m = controls();
        CHECK(m.count() == launcher::kCtlItems && launcher::kCtlItems == input::kActionCount + 4);
        auto cells = m.cells();
        CHECK(int(cells.size()) == m.count());
        // Every action exactly once in the panels; the panels hold their rows and stay apart.
        std::multiset<int> seen;
        const SDL_FRect screen{0, 0, launcher::kWidth, 650};  // above the notice and hint lines
        const auto& panels = launcher::controls_panels();
        CHECK(panels.size() == 5);
        for (const auto& p : panels) {
            SDL_FRect pr = launcher::controls_panel_rect(p);
            CHECK(inside(pr, screen) && !overlap(pr, launcher::controls_diagram_rect()));
            for (const auto& q : panels)
                if (&q != &p) CHECK(!overlap(pr, launcher::controls_panel_rect(q)));
            for (int a : p.actions) {
                seen.insert(a);
                CHECK(inside(m.row_rect(a), pr));
                CHECK(std::string(launcher::control_row_label(a)).size() > 0);
            }
        }
        CHECK(inside(launcher::controls_diagram_rect(), screen));
        for (int a = 0; a < input::kActionCount; a++) CHECK(seen.count(a) == 1);
        CHECK(std::string(panels[3].title) == "Right Stick");
        CHECK(panels[3].actions == (std::vector<int>{input::kActRStick, input::kActRSUp, input::kActRSDown,
                                                     input::kActRSLeft, input::kActRSRight}));
        // All items on screen at once, none overlapping, each hit by the mouse at its centre.
        for (int i = 0; i < m.count(); i++) {
            SDL_FRect r = m.row_rect(i);
            CHECK(r.w > 0 && r.h > 0 && inside(r, screen));
            for (int j = 0; j < i; j++) CHECK(!overlap(r, m.row_rect(j)));
            CHECK(m.hit(r.x + r.w / 2, r.y + r.h / 2) == i);
            CHECK(cells[i].size() == (i < input::kActionCount ? 3u : 1u));
        }
        CHECK(cells[launcher::kCtlReset][0] == "Reset to defaults" && cells[launcher::kCtlBack][0] == "Back");
        CHECK(cells[launcher::kCtlTabPad][0] == "Gamepad" && cells[launcher::kCtlTabKeys][0] == "Keyboard");
        CHECK(cells[input::kActRSRight][0] == "R stick right" && cells[input::kActRSRight][1] == "+rightx");
        CHECK(cells[input::kActA][1] == "east" && cells[input::kActA][2] == "Space");
        std::cout << "PASS layout: 24 controls once each in 5 panels (Right Stick included), 28 items on screen, "
                     "no overlap, mouse hits\n";
        return 0;
    }
    if (mode == "nav") {
        using namespace input;
        launcher::Menu m = controls();
        auto go = [&](std::initializer_list<Nav> ns) { for (Nav n : ns) m.handle(nav(n), 0); return m.cursor; };
        CHECK(go({Nav::Down, Nav::Down, Nav::Down, Nav::Down, Nav::Down}) == kActMinus);
        CHECK(go({Nav::Down}) == kActDUp && go({Nav::Down, Nav::Down, Nav::Down}) == kActDRight);
        CHECK(go({Nav::Right}) == kActRSRight);  // the bug: the right stick rows are there and reachable
        CHECK(go({Nav::Up}) == kActRSLeft && go({Nav::Up, Nav::Up, Nav::Up}) == kActRStick);
        CHECK(go({Nav::Up}) == kActLSRight && go({Nav::Left}) == kActPlus);
        m.cursor = kActA;
        CHECK(go({Nav::Right}) == kActLStick && go({Nav::Right}) == kActL && go({Nav::Right}) == kActR);
        CHECK(go({Nav::Right}) == kActR);  // nothing further: stays
        CHECK(go({Nav::Down}) == kActZR && go({Nav::Left}) == kActZL && go({Nav::Down}) == launcher::kCtlReset);
        CHECK(go({Nav::Right}) == launcher::kCtlBack && go({Nav::Up}) == kActZR);
        m.cursor = kActLStick;
        CHECK(go({Nav::Up}) == launcher::kCtlTabPad && go({Nav::Right}) == launcher::kCtlTabKeys);
        CHECK(go({Nav::Left}) == launcher::kCtlTabPad && go({Nav::Down}) == kActLStick);
        // Every item is reachable from the first.
        std::set<int> reached{0};
        std::vector<int> todo{0};
        while (!todo.empty()) {
            m.cursor = todo.back();
            todo.pop_back();
            int from = m.cursor;
            for (Nav n : {Nav::Up, Nav::Down, Nav::Left, Nav::Right}) {
                m.cursor = from;
                m.handle(nav(n), 0);
                if (reached.insert(m.cursor).second) todo.push_back(m.cursor);
            }
        }
        CHECK(int(reached.size()) == launcher::kCtlItems);
        CHECK(m.scroll == 0 && m.screen == Screen::Controls);
        std::cout << "PASS nav: nearest item per direction, the right stick reachable, every item reachable, no scroll\n";
        return 0;
    }
    if (mode == "rebind") {
        using namespace input;
        launcher::Menu m = controls();
        const Controls d = default_controls();
        Event key; key.kind = Event::kKey; key.key = SDL_SCANCODE_ESCAPE;
        Event pad; pad.kind = Event::kPad; pad.pad = Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_NORTH};
        // Gamepad tab: a key cancels, a gamepad input binds the gamepad binding.
        CHECK(m.tab == ControlsTab::Gamepad);
        m.handle(nav(Nav::Confirm), 100);
        CHECK(m.capturing == kActA && m.capture_until == 100 + launcher::kCaptureMs);
        CHECK(m.cells()[kActA][1] == "Press a button..." && m.cells()[kActA][2] == "Space");
        m.handle(nav(Nav::Down), 150);  // ignored while capturing
        CHECK(m.cursor == kActA && m.capturing == kActA);
        m.handle(key, 200);
        CHECK(m.capturing == -1 && m.notice == "Rebinding cancelled" && !m.controls_dirty && m.controls == d);
        m.handle(nav(Nav::Confirm), 300);
        m.handle(pad, 400);
        CHECK(m.capturing == -1 && m.controls_dirty && m.controls.pad[kActA] == std::vector<Source>{pad.pad});
        CHECK(m.controls.keys == d.keys && m.notice == "A: gamepad north");
        // Keyboard tab (by mouse): a gamepad input cancels, a key (Esc too) binds the keyboard binding.
        m.controls_dirty = false;
        m.handle(at(Event::kClick, m.row_rect(launcher::kCtlTabKeys)), 500);
        CHECK(m.tab == ControlsTab::Keyboard && m.cursor == launcher::kCtlTabKeys && m.capturing == -1);
        m.handle(at(Event::kMove, m.row_rect(kActRSRight)), 600);
        CHECK(m.cursor == kActRSRight);
        m.handle(at(Event::kClick, m.row_rect(kActRSRight)), 700);
        CHECK(m.capturing == kActRSRight && m.cells()[kActRSRight][2] == "Press a key...");
        m.handle(pad, 800);
        CHECK(m.capturing == -1 && m.notice == "Rebinding cancelled" && !m.controls_dirty);
        m.handle(nav(Nav::Confirm), 900);
        m.handle(key, 1000);
        CHECK(m.controls.keys[kActRSRight] == std::vector<SDL_Scancode>{SDL_SCANCODE_ESCAPE} && m.controls_dirty);
        CHECK(m.controls.pad[kActRSRight] == d.pad[kActRSRight]);
        // A click cancels; the timeout cancels.
        m.controls_dirty = false;
        m.handle(nav(Nav::Confirm), 2000);
        m.handle(at(Event::kClick, m.row_rect(kActA)), 2001);
        CHECK(m.capturing == -1 && m.notice == "Rebinding cancelled" && !m.controls_dirty);
        m.handle(nav(Nav::Confirm), 3000);
        m.tick(3000 + launcher::kCaptureMs - 1);
        CHECK(m.capturing == kActRSRight);
        m.tick(3000 + launcher::kCaptureMs);
        CHECK(m.capturing == -1 && m.notice == "Rebinding timed out");
        // Back to the Gamepad tab by keyboard; Reset to defaults restores both devices.
        m.cursor = launcher::kCtlTabPad;
        m.handle(nav(Nav::Confirm), 4000);
        CHECK(m.tab == ControlsTab::Gamepad && m.capturing == -1);
        m.cursor = launcher::kCtlReset;
        m.handle(nav(Nav::Confirm), 4000);
        CHECK(m.controls == d && m.controls_dirty && m.notice == "Controls reset to defaults");
        // controls.ini is the same format: the defaults round-trip.
        CHECK(parse_controls(write_controls(m.controls)) == d);
        // Back: the item and the Back input return to the main menu on CONTROLS.
        m.cursor = launcher::kCtlBack;
        m.handle(nav(Nav::Confirm), 5000);
        CHECK(m.screen == Screen::Main && m.cursor == 1);
        launcher::Menu b = controls();
        b.handle(nav(Nav::Back), 0);
        CHECK(b.screen == Screen::Main && b.cursor == 1 && b.result == launcher::Result::None);
        std::cout << "PASS rebind: tab device binds, other device / click / timeout cancel, tabs, reset, back\n";
        return 0;
    }
    if (mode == "render") {  // argv[2]: the asset folder ("" for none), argv[3]: scale
        std::string assets = argv[2];
        int k = std::atoi(argv[3]);
        SDL_Surface* surf = SDL_CreateSurface(1280 * k, 720 * k, SDL_PIXELFORMAT_RGBA32);
        SDL_Renderer* r = surf ? SDL_CreateSoftwareRenderer(surf) : nullptr;
        CHECK(r != nullptr);
        launcher::Art* art = launcher::art_open(r, assets);
        CHECK(launcher::art_has_font(art) == !assets.empty());
        launcher::Status s;
        s.controller = "Test pad";
        auto pixel = [&](float x, float y) {  // layout -> surface pixel
            const uint8_t* p = static_cast<const uint8_t*>(surf->pixels) + int(y * k) * surf->pitch + int(x * k) * 4;
            return std::array<int, 3>{p[0], p[1], p[2]};
        };
        SDL_FRect d = launcher::controls_diagram_rect();
        const float rx = d.x + d.w / 2 + 52, ry = d.y + 190 + 18;  // the right stick's cap
        for (int focus : {int(input::kActRStick), int(input::kActA)}) {
            launcher::Menu m = controls();
            m.cursor = focus;
            launcher::draw(r, art, m, s);
            SDL_RenderPresent(r);
            auto c = pixel(rx, ry);
            bool lit = c[0] == 255 && c[1] == 226 && c[2] == 170;
            CHECK(lit == (focus == input::kActRStick));
        }
        launcher::art_close(art);
        SDL_DestroyRenderer(r);
        SDL_DestroySurface(surf);
        std::cout << "PASS render: the drawn controller lights the focused control\n";
        return 0;
    }
    return 1;
}
'''


class AstralControlsUiTests(unittest.TestCase):
    def test_overlay_layout_nav_rebind_render_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
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
        vulkan = vulkan_include()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        source = out / 'source'
        runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in ORDER[:-1]])
        stacked = runtime.source_fingerprint(source)
        patch = font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         sorted(MODIFIED))  # input_map (bindings, controls.ini) untouched
        text = patch.read_text()
        self.assertNotRegex(text, r'(?i)nintendo co|platinum')
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
        for args in (['layout'], ['nav'], ['rebind'], ['render', str(ASSETS), '1'], ['render', str(ASSETS), '2'],
                     ['render', '', '1']):
            r = subprocess.run([str(work / 'run'), *args], cwd=work, capture_output=True, text=True, timeout=120,
                               env=clean)
            self.assertEqual(r.returncode, 0, ' '.join(args) + ': ' + r.stdout + r.stderr)
            self.assertIn('PASS', r.stdout)
            print(r.stdout, end='')

        # Strict syntax (Mac profile, warnings as errors) and default syntax; without NX_ASTRAL_STRICT, nothing.
        for flags in (['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1'], []):
            check = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                                    *flags, *includes, '-I', sdl, '-fsyntax-only', str(src / 'launcher.cpp')],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        empty = subprocess.run([compiler, '-std=c++20', '-E', '-P', *includes, '-I', sdl, str(src / 'launcher.cpp')],
                               capture_output=True, text=True, timeout=60, check=True).stdout
        self.assertEqual(empty.strip(), '')
        print('PASS strict and default syntax; default profile: launcher.cpp empty')
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-controls-ui.patch')


if __name__ == '__main__':
    unittest.main()
