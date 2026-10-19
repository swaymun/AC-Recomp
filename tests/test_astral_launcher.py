"""CPU regression of the launcher and input remapping overlay (astral-launcher.patch).

The overlay is applied last in the native overlay order (after astral-perf-hud.patch and astral-audio-dump.patch) on
a fresh copy of the pinned public runtime. The production input_map.cpp and launcher.cpp are compiled with a fixture
and linked with SDL3 (no SDL_Init, no window, no display, no device): controls.ini and settings.ini round trips and
error handling; the default bindings against an independent copy of the hosts' former fixed mapping on random
synthetic gamepad + keyboard frames; remapped bindings; synthetic SDL events translated to menu events; the menu state
machine (navigate, rebind by key and by gamepad, timeout, reset, settings, environment locks, mouse hit tests, start,
quit); and start() with NX_SKIP_LAUNCHER / NX_HEADLESS against settings.ini and the environment. The changed
translation units get strict syntax checks in the Mac profile and the default profile must preprocess identically;
Linux's additions are checked textually to be strict-only. No game, window or network is used.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime
import test_astral_shared_font as font
from test_nvn_window_depth import preprocessed
from test_astral_perf_hud import sdl_include, vulkan_include

# The native overlay order: font.ORDER (through astral-nvn-cube-storage), then these, then this overlay last.
BEFORE = ('astral-shared-font.patch', 'astral-swkbd.patch', 'astral-perf-hud.patch', 'astral-audio-dump.patch')
OVERLAY = 'astral-launcher.patch'
ORDER = (*font.ORDER, *BEFORE, OVERLAY)
NEW = ['runtime/src/input_map.cpp', 'runtime/src/input_map.h', 'runtime/src/launcher.cpp', 'runtime/src/launcher.h',
       'runtime/src/third_party/stb_image.h', 'runtime/src/third_party/stb_truetype.h']
ASSETS = ROOT / 'assets/launcher'
MODIFIED = ['CMakeLists.txt', 'runtime/src/loader.cpp', 'runtime/src/platform_linux.cpp',
            'runtime/src/platform_mac.cpp']

FIXTURE = r'''
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <random>
#include <string>
#include <nx/runtime.h>
#include "platform.h"
namespace nx {
void log(const char*, ...) {}
namespace plat {
std::string data_root() { const char* r = std::getenv("NX_DATA_ROOT"); return r ? r : "private/astral"; }
bool headless() { return std::getenv("NX_HEADLESS") != nullptr; }
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
}  // namespace plat
}  // namespace nx
#include "input_map.cpp"
#include "launcher.cpp"
#define CHECK(...) do { if (!(__VA_ARGS__)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #__VA_ARGS__); std::abort(); } } while (0)

using namespace nx;
using namespace nx::plat;
using input::Source;
using launcher::Event;
using launcher::Nav;

// The hosts' former fixed mapping (platform_mac.cpp / platform_linux.cpp before this overlay), on a Frame.
PadState former(const input::Frame& f) {
    PadState p;
    if (f.has_pad) {
        struct Map { SDL_GamepadButton b; uint64_t bit; };
        static const Map map[] = {
            {SDL_GAMEPAD_BUTTON_EAST, kA},           {SDL_GAMEPAD_BUTTON_SOUTH, kB},
            {SDL_GAMEPAD_BUTTON_NORTH, kX},          {SDL_GAMEPAD_BUTTON_WEST, kY},
            {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER, kL},  {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, kR},
            {SDL_GAMEPAD_BUTTON_START, kPlus},       {SDL_GAMEPAD_BUTTON_BACK, kMinus},
            {SDL_GAMEPAD_BUTTON_LEFT_STICK, kStickL}, {SDL_GAMEPAD_BUTTON_RIGHT_STICK, kStickR},
            {SDL_GAMEPAD_BUTTON_DPAD_LEFT, kLeft},   {SDL_GAMEPAD_BUTTON_DPAD_UP, kUp},
            {SDL_GAMEPAD_BUTTON_DPAD_RIGHT, kRight}, {SDL_GAMEPAD_BUTTON_DPAD_DOWN, kDown},
        };
        for (const Map& m : map) if (f.buttons[m.b]) p.buttons |= m.bit;
        if (f.axes[SDL_GAMEPAD_AXIS_LEFT_TRIGGER] > 12000) p.buttons |= kZL;
        if (f.axes[SDL_GAMEPAD_AXIS_RIGHT_TRIGGER] > 12000) p.buttons |= kZR;
        auto axis = [&](SDL_GamepadAxis a, bool invert) {
            int v = f.axes[a];
            if (v > -7849 && v < 7849) return 0;
            v = std::clamp(v, -kStickMax, kStickMax);
            return invert ? -v : v;
        };
        p.lx = axis(SDL_GAMEPAD_AXIS_LEFTX, false);
        p.ly = axis(SDL_GAMEPAD_AXIS_LEFTY, true);
        p.rx = axis(SDL_GAMEPAD_AXIS_RIGHTX, false);
        p.ry = axis(SDL_GAMEPAD_AXIS_RIGHTY, true);
    }
    if (const bool* k = f.keys) {
        if (k[SDL_SCANCODE_A] || k[SDL_SCANCODE_LEFT]) p.lx = -kStickMax, p.buttons |= kLeft;
        if (k[SDL_SCANCODE_D] || k[SDL_SCANCODE_RIGHT]) p.lx = kStickMax, p.buttons |= kRight;
        if (k[SDL_SCANCODE_W] || k[SDL_SCANCODE_UP]) p.ly = kStickMax, p.buttons |= kUp;
        if (k[SDL_SCANCODE_S] || k[SDL_SCANCODE_DOWN]) p.ly = -kStickMax, p.buttons |= kDown;
        if (k[SDL_SCANCODE_SPACE]) p.buttons |= kA;
        if (k[SDL_SCANCODE_LSHIFT] || k[SDL_SCANCODE_RSHIFT]) p.buttons |= kB;
        if (k[SDL_SCANCODE_J]) p.buttons |= kX;
        if (k[SDL_SCANCODE_K]) p.buttons |= kY;
        if (k[SDL_SCANCODE_Q]) p.buttons |= kL;
        if (k[SDL_SCANCODE_E]) p.buttons |= kR;
        if (k[SDL_SCANCODE_Z]) p.buttons |= kZL;
        if (k[SDL_SCANCODE_C]) p.buttons |= kZR;
        if (k[SDL_SCANCODE_RETURN]) p.buttons |= kPlus;
        if (k[SDL_SCANCODE_ESCAPE]) p.buttons |= kMinus;
    }
    return p;
}

bool same(const PadState& a, const PadState& b) {
    return a.buttons == b.buttons && a.lx == b.lx && a.ly == b.ly && a.rx == b.rx && a.ry == b.ry;
}

Event nav(Nav n) { Event e; e.kind = Event::kNav; e.nav = n; return e; }
SDL_Event key(SDL_Scancode s, bool repeat = false) {
    SDL_Event e{}; e.type = SDL_EVENT_KEY_DOWN; e.key.scancode = s; e.key.repeat = repeat; return e;
}
SDL_Event button(SDL_GamepadButton b) { SDL_Event e{}; e.type = SDL_EVENT_GAMEPAD_BUTTON_DOWN; e.gbutton.button = Uint8(b); return e; }
SDL_Event axis(SDL_GamepadAxis a, int v) { SDL_Event e{}; e.type = SDL_EVENT_GAMEPAD_AXIS_MOTION; e.gaxis.axis = Uint8(a); e.gaxis.value = Sint16(v); return e; }
SDL_Event click(float x, float y) {
    SDL_Event e{}; e.type = SDL_EVENT_MOUSE_BUTTON_DOWN; e.button.button = SDL_BUTTON_LEFT; e.button.x = x; e.button.y = y; return e;
}

void unit(const std::string& dir) {
    // ---- controls.ini ----
    input::Controls d = input::default_controls();
    std::string text = input::write_controls(d);
    std::ofstream(dir + "/defaults.ini") << text;
    CHECK(input::parse_controls(text) == d && input::parse_controls("") == d);
    input::Controls c = d;
    c.pad[input::kActA] = {Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_SOUTH}};  // Xbox-style: swap A and B
    c.pad[input::kActB] = {Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_EAST}};
    c.pad[input::kActZL] = {Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_LEFT_PADDLE1},
                            Source{Source::kAxis, -1, SDL_GAMEPAD_AXIS_RIGHTY}};
    c.keys[input::kActA] = {SDL_SCANCODE_KP_ENTER};
    c.keys[input::kActLStick] = {SDL_SCANCODE_LCTRL, SDL_SCANCODE_GRAVE};
    c.keys[input::kActB].clear();
    c.pad[input::kActRSUp].clear();
    CHECK(input::parse_controls(input::write_controls(c)) == c);
    std::vector<std::string> errors;
    input::Controls e = input::parse_controls(
        "# comment\n[GamePad]\n a = SOUTH \nB = nonsense\nX = none\nWHAT = east\n[keyboard]\nY = Left Shift|  k \n"
        "L = NoSuchKey | Q\nR =\nZL = NoSuchKey\nnot an entry\n[other]\nA = west\n", &errors);
    CHECK(e.pad[input::kActA] == std::vector<Source>{Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_SOUTH}});
    CHECK(e.pad[input::kActB] == d.pad[input::kActB] && e.pad[input::kActX].empty());
    CHECK(e.keys[input::kActY] == (std::vector<SDL_Scancode>{SDL_SCANCODE_LSHIFT, SDL_SCANCODE_K}));
    CHECK(e.keys[input::kActL] == std::vector<SDL_Scancode>{SDL_SCANCODE_Q} && e.keys[input::kActR].empty());
    CHECK(e.keys[input::kActZL] == d.keys[input::kActZL]);
    CHECK(errors.size() == 6);  // nonsense, WHAT, NoSuchKey (twice), not an entry, [other]
    Source s;
    CHECK(input::parse_source("+LeftTrigger", s) && s == (Source{Source::kAxis, 1, SDL_GAMEPAD_AXIS_LEFT_TRIGGER}));
    CHECK(input::parse_source("-leftx", s) && input::source_name(s) == "-leftx");
    CHECK(!input::parse_source("a", s) && !input::parse_source("+nothing", s) && !input::parse_source("", s));
    std::cout << "PASS controls.ini: defaults and custom round trip, comments, case, none, bad names keep defaults\n";

    // ---- the defaults are the former fixed mapping, on random synthetic frames ----
    std::mt19937 rng(1234);
    const int edges[] = {-32768, -32767, -20000, -12001, -12000, -7849, -7848, -1, 0, 1, 7848, 7849, 12000, 12001, 32767};
    const SDL_Scancode used[] = {SDL_SCANCODE_A, SDL_SCANCODE_D, SDL_SCANCODE_W, SDL_SCANCODE_S, SDL_SCANCODE_LEFT,
        SDL_SCANCODE_RIGHT, SDL_SCANCODE_UP, SDL_SCANCODE_DOWN, SDL_SCANCODE_SPACE, SDL_SCANCODE_LSHIFT,
        SDL_SCANCODE_RSHIFT, SDL_SCANCODE_J, SDL_SCANCODE_K, SDL_SCANCODE_Q, SDL_SCANCODE_E, SDL_SCANCODE_Z,
        SDL_SCANCODE_C, SDL_SCANCODE_RETURN, SDL_SCANCODE_ESCAPE, SDL_SCANCODE_X, SDL_SCANCODE_F3};
    std::vector<bool> keybuf(SDL_SCANCODE_COUNT);
    bool keys[SDL_SCANCODE_COUNT];
    for (int n = 0; n < 50000; n++) {
        input::Frame f;
        f.has_pad = rng() % 5 != 0;
        for (auto& b : f.buttons) b = rng() % 4 == 0;
        for (auto& a : f.axes) a = int16_t(rng() % 2 ? edges[rng() % 15] : int(rng() % 65536) - 32768);
        std::memset(keys, 0, sizeof keys);
        for (SDL_Scancode k : used) keys[k] = rng() % 6 == 0;
        f.keys = rng() % 4 ? keys : nullptr;
        PadState a = input::map(d, f), b = former(f);
        if (!same(a, b)) {
            std::cerr << "mismatch at " << n << ": " << a.buttons << " " << b.buttons << " " << a.lx << " " << b.lx
                      << " " << a.ly << " " << b.ly << "\n";
            std::abort();
        }
    }
    std::cout << "PASS defaults: identical to the former fixed mapping on 50000 random gamepad + keyboard frames\n";

    // ---- remapped ----
    input::Frame f;
    f.has_pad = true;
    f.buttons[SDL_GAMEPAD_BUTTON_SOUTH] = true;
    PadState p = input::map(c, f);
    CHECK(p.buttons == kA);  // south is now A
    f.buttons[SDL_GAMEPAD_BUTTON_SOUTH] = false;
    f.buttons[SDL_GAMEPAD_BUTTON_LEFT_PADDLE1] = true;
    CHECK(input::map(c, f).buttons == kZL);
    f.buttons[SDL_GAMEPAD_BUTTON_LEFT_PADDLE1] = false;
    f.axes[SDL_GAMEPAD_AXIS_RIGHTY] = -12001;  // right stick up: ZL (above 12000), the stick's own up is unbound
    p = input::map(c, f);
    CHECK(p.buttons == kZL && p.ry == 0);
    f.axes[SDL_GAMEPAD_AXIS_RIGHTY] = 30000;  // down still moves the stick
    CHECK(input::map(c, f).ry == -30000 && input::map(c, f).buttons == 0);
    f.axes[SDL_GAMEPAD_AXIS_LEFT_TRIGGER] = 32767;  // the trigger no longer presses ZL
    CHECK(!(input::map(c, f).buttons & kZL));
    std::memset(keys, 0, sizeof keys);
    keys[SDL_SCANCODE_KP_ENTER] = keys[SDL_SCANCODE_GRAVE] = keys[SDL_SCANCODE_LSHIFT] = true;
    input::Frame k;
    k.keys = keys;
    CHECK(input::map(c, k).buttons == (kA | kStickL));  // shift no longer B
    input::Controls stick = d;  // a stick direction on a button: full deflection
    stick.pad[input::kActLSUp] = {Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_NORTH}};
    input::Frame g;
    g.has_pad = true;
    g.buttons[SDL_GAMEPAD_BUTTON_NORTH] = true;
    CHECK(input::map(stick, g).ly == kStickMax && input::map(stick, g).buttons == kX);  // north is still X too
    std::cout << "PASS remap: buttons, paddles, axes as buttons, unbound directions, keys, stick from a button\n";

    // ---- settings.ini ----
    input::Settings st;
    CHECK(input::parse_settings(input::write_settings(st)) == st);
    st.perf_hud = st.mute = true, st.resolution = "2560x1440";
    CHECK(input::parse_settings(input::write_settings(st)) == st);
    input::Settings odd = input::parse_settings("fullscreen = on\nmute=yes\nperf_hud = 0\nresolution = 12x3\n");
    CHECK(odd.fullscreen && odd.mute && !odd.perf_hud && odd.resolution == "1280x720");
    CHECK(input::parse_settings("resolution = 1920x1080junk\n").resolution == "1280x720");
    CHECK(input::parse_settings("resolution = 1920x1080\n").resolution == "1920x1080");
    std::cout << "PASS settings.ini: round trip, on/yes/1, bad resolutions ignored\n";

    // ---- SDL events -> menu events ----
    launcher::StickLatch latch;
    auto tr = [&](const SDL_Event& ev, bool capturing = false, const input::Controls& with = input::default_controls()) {
        return launcher::translate(ev, with, capturing, latch);
    };
    CHECK(tr(key(SDL_SCANCODE_UP)).nav == Nav::Up && tr(key(SDL_SCANCODE_S)).nav == Nav::Down);
    CHECK(tr(key(SDL_SCANCODE_RETURN)).nav == Nav::Confirm && tr(key(SDL_SCANCODE_RETURN, true)).kind == Event::kNone);
    CHECK(tr(key(SDL_SCANCODE_ESCAPE)).nav == Nav::Back && tr(key(SDL_SCANCODE_F5)).kind == Event::kNone);
    CHECK(tr(button(SDL_GAMEPAD_BUTTON_EAST)).nav == Nav::Confirm && tr(button(SDL_GAMEPAD_BUTTON_SOUTH)).nav == Nav::Back);
    CHECK(tr(button(SDL_GAMEPAD_BUTTON_DPAD_LEFT)).nav == Nav::Left && tr(button(SDL_GAMEPAD_BUTTON_START)).kind == Event::kNone);
    CHECK(tr(button(SDL_GAMEPAD_BUTTON_SOUTH), false, c).nav == Nav::Confirm);  // A rebound to south confirms
    CHECK(tr(button(SDL_GAMEPAD_BUTTON_EAST), false, c).nav == Nav::Back);
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_LEFTY, 25000)).nav == Nav::Down);
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_LEFTY, 30000)).kind == Event::kNone);  // held: once
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_LEFTY, 9000)).kind == Event::kNone);   // not back at rest yet
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_LEFTY, 100)).kind == Event::kNone);
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_LEFTY, -25000)).nav == Nav::Up && tr(axis(SDL_GAMEPAD_AXIS_LEFTX, 21000)).nav == Nav::Right);
    Event cap = tr(key(SDL_SCANCODE_ESCAPE), true);
    CHECK(cap.kind == Event::kKey && cap.key == SDL_SCANCODE_ESCAPE && tr(key(SDL_SCANCODE_J, true), true).kind == Event::kNone);
    cap = tr(button(SDL_GAMEPAD_BUTTON_DPAD_UP), true);
    CHECK(cap.kind == Event::kPad && cap.pad == (Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_DPAD_UP}));
    CHECK(tr(axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, 20000), true).kind == Event::kNone);
    cap = tr(axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, 30000), true);
    CHECK(cap.kind == Event::kPad && cap.pad == (Source{Source::kAxis, 1, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER}));
    Event ck = tr(click(320, 200));
    CHECK(ck.kind == Event::kClick && ck.x == 320 && ck.y == 200);
    SDL_Event q{}; q.type = SDL_EVENT_QUIT;
    CHECK(tr(q).kind == Event::kQuit);
    std::cout << "PASS events: keys, repeats, gamepad A/B follow the bindings, stick latch, capture, mouse, quit\n";

    // ---- the menu ----
    launcher::Menu m;
    CHECK(m.screen == launcher::Screen::Main && m.count() == 4 && m.rows()[0] == "PLAY");
    m.handle(nav(Nav::Up), 0);
    CHECK(m.cursor == 3);
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Down), 0);
    CHECK(m.cursor == 1);
    m.handle(nav(Nav::Confirm), 0);
    CHECK(m.screen == launcher::Screen::Controls && m.cursor == 0 && m.count() == input::kActionCount + 2);
    m.handle(nav(Nav::Confirm), 100);
    CHECK(m.capturing == 0 && m.capture_until == 100 + launcher::kCaptureMs);
    Event moved; moved.kind = Event::kMove; moved.x = 300, moved.y = 100;
    m.handle(moved, 200);
    m.handle(nav(Nav::Down), 200);  // ignored while capturing
    CHECK(m.capturing == 0 && m.cursor == 0);
    Event kk; kk.kind = Event::kKey; kk.key = SDL_SCANCODE_L;
    m.handle(kk, 300);
    CHECK(m.capturing == -1 && m.controls_dirty && m.controls.keys[input::kActA] == std::vector<SDL_Scancode>{SDL_SCANCODE_L});
    CHECK(m.rows()[0].size() > 4 && m.rows()[0].substr(m.rows()[0].size() - 2) == " L");
    m.controls_dirty = false;
    m.handle(nav(Nav::Down), 300), m.handle(nav(Nav::Confirm), 300);
    Event pk; pk.kind = Event::kPad; pk.pad = Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_NORTH};
    m.handle(pk, 400);
    CHECK(m.controls.pad[input::kActB] == std::vector<Source>{pk.pad} && m.controls_dirty);
    m.handle(nav(Nav::Confirm), 1000);
    m.tick(5999);
    CHECK(m.capturing == 1);
    m.tick(6000);
    CHECK(m.capturing == -1 && m.notice == "Rebinding timed out");
    m.handle(nav(Nav::Confirm), 7000);
    Event cl; cl.kind = Event::kClick; cl.x = 1, cl.y = 1;
    m.handle(cl, 7001);
    CHECK(m.capturing == -1 && m.notice == "Rebinding cancelled" && m.controls.pad[input::kActB] == std::vector<Source>{pk.pad});
    // Scrolling: the last row (Back) brings the list down; the first rows leave the screen.
    m.handle(nav(Nav::Up), 0), m.handle(nav(Nav::Up), 0);
    CHECK(m.cursor == input::kActionCount + 1 && m.scroll == input::kActionCount + 2 - launcher::kControlsVisible);
    CHECK(m.row_rect(0).w == 0 && m.hit(100, m.row_rect(m.cursor).y + 2) == m.cursor);
    m.handle(nav(Nav::Up), 0);  // Reset to defaults
    m.handle(nav(Nav::Confirm), 0);
    CHECK(m.controls == input::default_controls() && m.notice == "Controls reset to defaults");
    m.handle(nav(Nav::Back), 0);
    CHECK(m.screen == launcher::Screen::Main && m.cursor == 1);
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Confirm), 0);
    CHECK(m.screen == launcher::Screen::Settings && m.count() == input::kSettingCount + 1);
    m.settings_dirty = false;
    m.handle(nav(Nav::Confirm), 0);
    CHECK(m.settings.perf_hud && m.settings_dirty);
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Right), 0);
    CHECK(m.settings.fullscreen);
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Right), 0);
    CHECK(m.settings.resolution == "1600x900");
    m.handle(nav(Nav::Left), 0), m.handle(nav(Nav::Left), 0);
    CHECK(m.settings.resolution == "3840x2160");
    m.env.set[input::kSetMute] = true, m.env.value[input::kSetMute] = "1";
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Confirm), 0);
    CHECK(!m.settings.mute && m.notice == "Set by NX_MUTE in the environment");
    CHECK(m.rows()[input::kSetMute].find("(set by NX_MUTE)") != std::string::npos);
    CHECK(m.rows()[input::kSetPerfHud].find("On") != std::string::npos);
    m.handle(nav(Nav::Down), 0), m.handle(nav(Nav::Confirm), 0);
    CHECK(m.screen == launcher::Screen::Main && m.cursor == 2 && m.result == launcher::Result::None);
    SDL_FRect quit = m.row_rect(3);
    m.handle(launcher::translate(click(quit.x + quit.w / 2, quit.y + quit.h / 2), m.controls, false, latch), 0);
    CHECK(m.result == launcher::Result::Quit);
    launcher::Menu go;
    SDL_FRect start = go.row_rect(0);
    CHECK(go.hit(start.x - 1, start.y + 1) == -1 && go.hit(start.x + 1, start.y + start.h) == -1);
    go.handle(launcher::translate(click(start.x + 1, start.y + 1), go.controls, false, latch), 0);
    CHECK(go.result == launcher::Result::Start);
    launcher::Menu closed;
    closed.handle(launcher::translate(q, closed.controls, false, latch), 0);
    CHECK(closed.result == launcher::Result::Quit);
    std::cout << "PASS menu: navigate and wrap, rebind by key and gamepad, timeout, click cancels, scroll, reset, "
                 "settings and env locks, mouse start/quit, window close\n";

    // ---- status text ----
    CHECK(!launcher::game_data_present(dir + "/nothing"));
    std::filesystem::create_directories(dir + "/game/analysis");
    std::filesystem::create_directories(dir + "/game/extract/romfs");
    std::ofstream(dir + "/game/analysis/main.bin") << "x";
    CHECK(!launcher::game_data_present(dir + "/game/analysis"));
    CHECK(launcher::game_data_present(dir + "/game"));
    CHECK(launcher::fit(std::string(200, 'p'), 72).size() == 72 && launcher::fit("abc", 72) == "abc");
    CHECK(launcher::pad_text({Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_EAST}}, SDL_GAMEPAD_TYPE_XBOXONE) == "east (B)");
    CHECK(launcher::pad_text({Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_EAST}}, SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO) == "east (A)");
    CHECK(launcher::pad_text({Source{Source::kButton, 1, SDL_GAMEPAD_BUTTON_SOUTH}}, SDL_GAMEPAD_TYPE_PS5) == "south (Cross)");
    CHECK(launcher::pad_text({}, SDL_GAMEPAD_TYPE_PS5) == "none");
    std::cout << "PASS status: game data found / missing, long text cut, controller-specific button labels\n";

    // ---- key names: the separator, duplicate and empty names round trip by number ----
    input::Controls kn = d;
    kn.keys[input::kActA] = {SDL_SCANCODE_KP_VERTICALBAR, SDL_SCANCODE_KP_DBLVERTICALBAR};
    kn.keys[input::kActB] = {SDL_SCANCODE_RETURN2, SDL_SCANCODE_RETURN};
    SDL_Scancode nameless = SDL_SCANCODE_UNKNOWN;
    for (int k = 1; k < SDL_SCANCODE_COUNT && !nameless; k++)
        if (!*SDL_GetScancodeName(SDL_Scancode(k))) nameless = SDL_Scancode(k);
    CHECK(nameless != SDL_SCANCODE_UNKNOWN);
    kn.keys[input::kActX] = {nameless};
    CHECK(input::parse_controls(input::write_controls(kn)) == kn);
    CHECK(input::key_name(SDL_SCANCODE_KP_VERTICALBAR).rfind("sc:", 0) == 0 && input::key_name(SDL_SCANCODE_RETURN) == "Return");
    CHECK(input::key_name(SDL_SCANCODE_RETURN2) == "sc:" + std::to_string(int(SDL_SCANCODE_RETURN2)));
    CHECK(input::parse_key("sc:0") == SDL_SCANCODE_UNKNOWN && input::parse_key("sc:99999") == SDL_SCANCODE_UNKNOWN &&
          input::parse_key("sc:4x") == SDL_SCANCODE_UNKNOWN && input::parse_key("SC:4") == SDL_SCANCODE_A);
    std::cout << "PASS key names: Keypad | and ||, Return2, nameless keys round trip as sc:<number>\n";

    // ---- what the environment does, shown truthfully ----
    CHECK(input::env_effect(input::kSetMute, "0") == "On" && input::env_effect(input::kSetMute, "") == "On");
    CHECK(input::env_effect(input::kSetPerfHud, "0") == "Off" && input::env_effect(input::kSetPerfHud, "2") == "On" &&
          input::env_effect(input::kSetPerfHud, "") == "Off");
    CHECK(input::env_effect(input::kSetFullscreen, "1") == "On" && input::env_effect(input::kSetFullscreen, "yes") == "Off");
    CHECK(input::env_effect(input::kSetResolution, "800x600") == "800x600");
    setenv("NX_MUTE", "0", 1);
    input::EnvOverrides ov = input::env_overrides();
    CHECK(ov.set[input::kSetMute] && ov.value[input::kSetMute] == "On" && !ov.set[input::kSetPerfHud]);
    unsetenv("NX_MUTE");
    std::cout << "PASS environment: NX_MUTE=0 still mutes and shows On; NX_PERF_HUD / NX_FULLSCREEN as the runtime reads them\n";
}

int main(int argc, char** argv) {
    std::string mode = argv[1], dir = argc > 2 ? argv[2] : ".";
    if (mode == "unit") {
        unit(dir);
        return 0;
    }
    if (mode == "hudrestart") {  // macOS: restart when the launcher's HUD setting differs from what Metal loaded
        using R = launcher::MetalHudRestart;
        CHECK(launcher::metal_hud_restart(false, true, false, false) == R::On);    // switched on in the launcher
        CHECK(launcher::metal_hud_restart(true, false, false, false) == R::Off);   // switched off in the launcher
        CHECK(launcher::metal_hud_restart(true, true, false, false) == R::None);   // as loaded
        CHECK(launcher::metal_hud_restart(false, false, false, false) == R::None);
        CHECK(launcher::metal_hud_restart(false, true, true, false) == R::None);   // MTL_HUD_ENABLED set by the player
        CHECK(launcher::metal_hud_restart(true, false, true, false) == R::None);
        CHECK(launcher::metal_hud_restart(false, true, false, true) == R::None);   // already the restart: no loop
        CHECK(launcher::metal_hud_restart(true, false, false, true) == R::None);
        std::cout << "PASS hud restart: on/off when the setting differs; never for MTL_HUD_ENABLED or twice\n";
        return 0;
    }
    if (mode == "active") {  // the bindings sample_input uses: controls.ini when there is one
        input::Frame f;
        f.has_pad = true;
        f.buttons[SDL_GAMEPAD_BUTTON_SOUTH] = true;
        std::cout << "south=" << input::map(input::active(), f).buttons << "\n";
        return 0;
    }
    if (mode == "assetdir") {
        std::cout << launcher::asset_dir() << "\n";
        return 0;
    }
    if (mode == "readcap") {
        std::string data;
        bool ok = input::read_file(dir, data);
        std::cout << "read=" << ok << " size=" << data.size() << "\n";
        return 0;
    }
    if (mode == "skipped") {
        std::cout << "skipped=" << launcher::skipped() << "\n";
        return 0;
    }
    if (mode == "assets") {  // the shipped font and art: found through NX_ASSET_DIR, readable
        std::string d = launcher::asset_dir();
        float w = launcher::font_text_width(d + "/Baloo2-Bold.ttf", "AC Recomp", 84);
        float w2 = launcher::font_text_width(d + "/Baloo2-Bold.ttf", "AC Recomp", 42);
        std::string jpg;
        int iw = 0, ih = 0, n = 0;
        bool img = input::read_file(d + "/title-bg.jpg", jpg) &&
                   stbi_info_from_memory(reinterpret_cast<const unsigned char*>(jpg.data()), int(jpg.size()), &iw, &ih, &n);
        CHECK(w > 200 && w < 600 && std::abs(w - 2 * w2) < 1.0f);
        CHECK(launcher::font_text_width(d + "/missing.ttf", "x", 10) < 0);
        std::cout << "dir=" << d << "\nimage=" << img << " " << iw << "x" << ih << "\n";
        return 0;
    }
    if (mode == "start") {  // main()'s call with the launcher skipped: settings.ini exported, env wins
        bool go = launcher::start();
        for (int k = 0; k < input::kSettingCount; k++) {
            const char* v = std::getenv(input::setting_env(k));
            std::cout << input::setting_env(k) << "=" << (v ? v : "<unset>") << "\n";
        }
        std::cout << "start=" << go << "\n";
        return 0;
    }
    return 2;
}
'''


def sdl_lib(include):
    for d in (os.environ.get('NX_SDL3_LIB', ''), str(Path(include).parent / 'lib'), '/usr/lib', '/usr/lib/x86_64-linux-gnu'):
        if d and any((Path(d) / n).exists() for n in ('libSDL3.dylib', 'libSDL3.so')):
            return d
    return None


def strip_strict(text):
    """The source as the default profile sees it: #if defined(NX_ASTRAL_STRICT) blocks dropped (their #else kept).
    Only that one condition is interpreted; nested conditionals inside such a block are kept as text."""
    out, stack = [], []  # stack entries: None (other #if) or [strict, in_else]
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s == '#if defined(NX_ASTRAL_STRICT)':
            stack.append([True, False])
            continue
        if re.match(r'#\s*if', s):
            stack.append(None)
        elif s.startswith('#else') and stack and stack[-1] is not None:
            stack[-1][1] = True
            continue
        elif s.startswith('#endif') and stack:
            if stack.pop() is not None:
                continue
        if all(e is None or e[1] for e in stack):
            out.append(line)
    return ''.join(out)


class AstralLauncherTests(unittest.TestCase):
    def test_overlay_bindings_menu_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        sdl = sdl_include()
        if not sdl:
            self.skipTest('SDL3 headers required (NX_SDL3_INCLUDE)')
        lib = sdl_lib(sdl)
        if not lib:
            self.skipTest('SDL3 library required (NX_SDL3_LIB)')
        out, source, _ = font.stack_source(self, 'astral-launcher')
        for name in BEFORE:
            font.apply(self, source, name)
        stacked = runtime.source_fingerprint(source)
        before = {p: (source / p).read_text() for p in MODIFIED}
        patch = font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         sorted(NEW + MODIFIED))
        text = patch.read_text()
        for name, first in (('stb_truetype.h', '// stb_truetype.h - v1.26 - public domain'),
                            ('stb_image.h', '/* stb_image - v2.30 - public domain image loader')):
            self.assertTrue((source / 'runtime/src/third_party' / name).read_text().startswith(first), name)
        self.assertNotRegex(text, r'(?i)nintendo co|platinum')  # no game or vendor material, only the layout name
        src = source / 'runtime/src'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(src)]

        # CMake: the two TUs for Astral on the SDL3 desktop hosts, after the performance HUD.
        cmake = (source / 'CMakeLists.txt').read_text()
        listing = ('if(NX_GAME STREQUAL "astral" AND NOT ANDROID AND NOT IOS AND NOT WIN32)\n'
                   '    list(APPEND NX_RUNTIME_SOURCES runtime/src/input_map.cpp runtime/src/launcher.cpp)\nendif()')
        self.assertIn(listing, cmake)
        self.assertGreater(cmake.index(listing), cmake.index('runtime/src/perf_hud.cpp'))
        # Both hosts: the launcher runs in main() after SDL_Init and before any thread (memory guard, game).
        for host in ('platform_mac.cpp', 'platform_linux.cpp'):
            main = (src / host).read_text().split('\nint main() {')[1]
            self.assertLess(main.index('SDL_Init('), main.index('nx::launcher::start()'))
            self.assertLess(main.index('nx::launcher::start()'), main.index('start_memory_guard()'))
            self.assertLess(main.index('nx::launcher::start()'), main.index('start_thread('))
            if host == 'platform_linux.cpp':
                # NX_PERF_HUD: MangoHud's environment once the launcher exported the settings, before any thread.
                self.assertLess(main.index('nx::launcher::start()'), main.index('nx::hud::prepare_native_overlay();'))
                self.assertLess(main.index('nx::hud::prepare_native_overlay();'), main.index('start_memory_guard()'))
            else:
                # macOS decides Apple's Metal HUD before SDL_Init (astral-perf-hud.patch), not here.
                self.assertNotIn('prepare_native_overlay', main)
                # ... and restarts when the launcher's HUD setting differs from it, before any thread exists.
                self.assertLess(main.index('nx::launcher::start()'), main.index('metal_hud::after_launcher();'))
                self.assertLess(main.index('metal_hud::after_launcher();'), main.index('start_memory_guard()'))
                text = (src / host).read_text()
                after = text.split('void after_launcher() {')[1].split('\n}\n')[0]
                for needle in ('nx::launcher::metal_hud_restart(g_loaded, wanted, g_user, restarted)',
                               'setenv("NX_SKIP_LAUNCHER", "1", 1);', 'setenv("NX_METAL_HUD_RESTARTED", "1", 1);',
                               'unsetenv("MTL_HUD_ENABLED");', 'execv(path, argv);', '*_NSGetArgv()',
                               '_NSGetExecutablePath(path, &size)', 'setenv("NX_PERF_HUD", "0", 1);',
                               'else unsetenv("MTL_HUD_ENABLED"), setenv("NX_PERF_HUD", "0", 1);'):
                    self.assertIn(needle, after)
                self.assertLess(after.index('setenv("NX_SKIP_LAUNCHER"'), after.index('execv('))
                self.assertLess(after.index('capture_run'), after.index('execv('))  # capture runs never restart
                self.assertIn('builtin_forced()', after.split('\n')[1])  # NX_PERF_HUD=ac keeps the built-in HUD
                # Apple's HUD takes NX_PERF_HUD and F3 in every windowed run that is not a capture run, loaded or
                # not: the built-in HUD is never shown on macOS unless NX_PERF_HUD=ac or a capture run.
                self.assertIn('if (!headless() && !nx::hud::capture_run(data_root())) nx::hud::use_native('
                              'metal_hud::show, "Apple Metal HUD");', text)
                self.assertNotIn('metal_hud::g_loaded) nx::hud::use_native', text)
                self.assertIn('if (on == g_loaded) return true;', text.split('bool show(bool on) {')[1])
                # The restarted process continues the session's nx.log (appends; no .prev rotation).
                logger = (src / 'loader.cpp').read_text().split('void log(const char* fmt, ...) {')[1].split('\n}\n')[0]
                self.assertIn('getenv("NX_METAL_HUD_RESTARTED")', logger)
                self.assertIn('if (!restarted) {', logger)
                self.assertIn('std::fopen(file.c_str(), restarted ? "a" : "w")', logger)
                self.assertLess(logger.index('if (!restarted) {'), logger.index('std::rename('))
                # Without NX_ASTRAL_STRICT, loader.cpp is exactly the source before this overlay.
                self.assertEqual(strip_strict((src / 'loader.cpp').read_text()),
                                 strip_strict(before['runtime/src/loader.cpp']))
            # Window events of any other window (the launcher's, gone) never touch the game window's state.
            loop = main.split('switch (e.type) {')[1].split('case SDL_EVENT_KEY_DOWN:')[0]
            self.assertEqual(loop.count('if (!g_window || e.window.windowID != SDL_GetWindowID(g_window)) break;'), 3)
            for case in ('g_minimized = true;', 'g_minimized = false;', 'g_pixel_w = uint32_t(e.window.data1)'):
                block = loop.split(case)[0].rsplit('case ', 1)[1]
                self.assertIn('SDL_GetWindowID(g_window)', block, case)
            sample = (src / host).read_text().split('static void sample_input() {')[1].split('\n}\n')[0]
            self.assertIn('nx::input::map(nx::input::active()', sample)
            # Without NX_ASTRAL_STRICT, exactly the source before this overlay (Linux cannot be preprocessed here).
            self.assertEqual(strip_strict((src / host).read_text()), strip_strict(before['runtime/src/' + host]), host)
        print('PASS layout: CMake listing, launcher before every thread, sample_input remapped, strict-only blocks')

        # The fixture: config files, the former mapping, remaps, events, menu, start().
        work = out / 'fixture'
        work.mkdir()
        (work / 'fixture.cpp').write_text(FIXTURE)
        build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Wno-unused-parameter',
                                '-Wno-missing-field-initializers', '-DNX_ASTRAL_STRICT=1', *includes, '-I', sdl,
                                str(work / 'fixture.cpp'), '-L', lib, '-lSDL3', '-Wl,-rpath,' + lib,
                                '-o', str(work / 'run')], capture_output=True, text=True, timeout=180)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        clean = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}

        def run(*args, env=None):
            r = subprocess.run([str(work / 'run'), *map(str, args)], cwd=work, capture_output=True, text=True,
                               timeout=120, env={**clean, **(env or {})})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return r.stdout

        result = run('unit', work)
        self.assertEqual(result.count('PASS'), 9, result)
        print(result, end='')
        self.assertIn('PASS hud restart', run('hudrestart'))
        defaults = (work / 'defaults.ini').read_text().splitlines()
        for line in ('[gamepad]', 'A = east', 'B = south', 'X = north', 'Y = west', 'ZL = +lefttrigger',
                     'PLUS = start', 'MINUS = back', 'DUP = dpup', 'LS_UP = -lefty', 'RS_RIGHT = +rightx',
                     '[keyboard]', 'A = Space', 'B = Left Shift | Right Shift', 'ZR = C', 'PLUS = Return',
                     'MINUS = Escape', 'LSTICK = none', 'DUP = W | Up', 'LS_LEFT = A | Left'):
            self.assertIn(line, defaults)

        # sample_input's bindings: the defaults without controls.ini (south is B), the file's with one.
        root = work / 'root'
        root.mkdir()
        self.assertEqual(run('active', env={'NX_DATA_ROOT': str(root)}), 'south=2\n')
        (root / 'controls.ini').write_text('[gamepad]\nA = south\nB = east\n')
        self.assertEqual(run('active', env={'NX_DATA_ROOT': str(root)}), 'south=1\n')
        # start() skipped (NX_SKIP_LAUNCHER=1, NX_HEADLESS): nothing exported without settings.ini; with one, its
        # non-default values, never over the environment. No window is opened (SDL video is never initialised).
        fresh = work / 'fresh'
        fresh.mkdir()
        unset = 'NX_PERF_HUD=<unset>\nNX_FULLSCREEN=<unset>\nNX_RESOLUTION=<unset>\nNX_MUTE=<unset>\nstart=1\n'
        self.assertEqual(run('start', env={'NX_DATA_ROOT': str(fresh), 'NX_HEADLESS': '1'}), unset)
        self.assertEqual(run('start', env={'NX_DATA_ROOT': str(fresh), 'NX_SKIP_LAUNCHER': '1'}), unset)
        (root / 'settings.ini').write_text('[settings]\nperf_hud = 1\nfullscreen = 0\nresolution = 1920x1080\nmute = 1\n')
        self.assertEqual(run('start', env={'NX_DATA_ROOT': str(root), 'NX_SKIP_LAUNCHER': '1', 'NX_RESOLUTION': '800x600'}),
                         'NX_PERF_HUD=1\nNX_FULLSCREEN=<unset>\nNX_RESOLUTION=800x600\nNX_MUTE=1\nstart=1\n')
        self.assertEqual(run('start', env={'NX_DATA_ROOT': str(root), 'NX_HEADLESS': '1', 'NX_PERF_HUD': '0'}),
                         'NX_PERF_HUD=0\nNX_FULLSCREEN=<unset>\nNX_RESOLUTION=1920x1080\nNX_MUTE=1\nstart=1\n')
        self.assertEqual(sorted(p.name for p in fresh.iterdir()), [])  # skipped: nothing written
        print('PASS start: skipped launcher, controls.ini and settings.ini applied, environment wins, nothing written')

        # Headless and scripted runs never wait at the launcher; the player's own recorded session still sees it.
        cases = [({}, 0), ({'NX_HEADLESS': '1'}, 1), ({'NX_SKIP_LAUNCHER': '1'}, 1), ({'NX_SKIP_LAUNCHER': '0'}, 0),
                 ({'NX_SKIP_LAUNCHER': ''}, 0), ({'NX_INPUT_SCRIPT': '5:A:0.1'}, 1), ({'NX_DUMP_FRAMES': '30'}, 1),
                 ({'NX_AUDIO_DUMP': '1'}, 1), ({'NX_INPUT_RECORD': '1'}, 0), ({'NX_INPUT_SCRIPT': ''}, 0),
                 ({'NX_DUMP_FRAMES': '0'}, 0), ({'NX_AUDIO_DUMP': '0'}, 0), ({'NX_DUMP_FRAMES': ''}, 0)]
        for env, want in cases:
            self.assertEqual(run('skipped', env=env), f'skipped={want}\n', env)
        print('PASS skipped: NX_HEADLESS, NX_SKIP_LAUNCHER, NX_INPUT_SCRIPT, NX_DUMP_FRAMES, NX_AUDIO_DUMP; not NX_INPUT_RECORD')

        # The shipped assets: found through NX_ASSET_DIR; the font measures, the art is a 16:9 JPEG within budget.
        out_assets = run('assets', env={'NX_ASSET_DIR': str(ASSETS)})
        self.assertEqual(out_assets, f'dir={ASSETS}\nimage=1 1600x900\n')
        self.assertLessEqual((ASSETS / 'title-bg.jpg').stat().st_size, 400 * 1024)
        self.assertLessEqual((ASSETS / 'Baloo2-Bold.ttf').stat().st_size, 64 * 1024)
        self.assertIn('SIL OPEN FONT LICENSE', (ASSETS / 'OFL.txt').read_text())
        notice = (ROOT / 'runtime/patches/astral-launcher.NOTICE').read_text()
        for name in ('stb_truetype', 'stb_image', 'Baloo 2', 'public domain'):
            self.assertIn(name, notice)
        print('PASS assets: NX_ASSET_DIR, font metrics, 1600x900 JPEG within 400 KB, OFL and notices')

        # A folder with both the font and a background wins over an earlier partial one; a partial one over nothing.
        pick = work / 'pick'
        (pick / 'partial').mkdir(parents=True)
        shutil.copy(ASSETS / 'Baloo2-Bold.ttf', pick / 'partial')
        (pick / 'assets/launcher').mkdir(parents=True)
        for name in ('Baloo2-Bold.ttf', 'title-bg.jpg'):
            shutil.copy(ASSETS / name, pick / 'assets/launcher')

        def where(cwd, env):
            r = subprocess.run([str(work / 'run'), 'assetdir'], cwd=cwd, capture_output=True, text=True, timeout=60,
                               env={**clean, **env})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return r.stdout

        self.assertEqual(where(pick, {'NX_ASSET_DIR': str(pick / 'partial')}), 'assets/launcher\n')
        self.assertEqual(where(work, {'NX_ASSET_DIR': str(pick / 'partial')}), f'{pick / "partial"}\n')
        self.assertEqual(where(work, {}), '\n')
        # Reads are capped at 16 MiB.
        (pick / 'big.bin').write_bytes(b'\0' * ((16 << 20) + 1))
        (pick / 'edge.bin').write_bytes(b'\0' * (16 << 20))
        self.assertEqual(run('readcap', pick / 'big.bin'), 'read=0 size=0\n')
        self.assertEqual(run('readcap', pick / 'edge.bin'), f'read=1 size={16 << 20}\n')
        print('PASS asset folder: complete before partial, none; file reads capped at 16 MiB')

        # Strict syntax, Mac profile, and the default profile.
        vulkan = vulkan_include()
        mac = ['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1']
        tus = ['input_map.cpp', 'launcher.cpp']
        host = []
        if sys.platform == 'darwin' and (vulkan / 'vulkan/vulkan.h').is_file():
            host = ['platform_mac.cpp']
        extra = ['-I', sdl, '-I', str(vulkan)]
        for flags in (mac, []):
            for name in tus + host:
                warn = ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter'] if name in tus else []
                check = subprocess.run([compiler, '-std=c++20', *warn, *flags, *includes, *extra, '-fsyntax-only',
                                        str(src / name)], capture_output=True, text=True, timeout=120)
                self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        print('PASS strict (Mac profile) and default syntax: ' + ', '.join(tus + host))
        for name in tus:
            empty = subprocess.run([compiler, '-std=c++20', '-E', '-P', *includes, *extra, str(src / name)],
                                   capture_output=True, text=True, timeout=60, check=True).stdout
            self.assertEqual(empty.strip(), '', name)
        patched = {n: preprocessed(compiler, includes + extra, src / n) for n in host}
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        for n in host:
            self.assertEqual(patched[n], preprocessed(compiler, includes + extra, src / n), n + ': default profile differs')
        print('PASS default profile: new TUs empty; ' + (', '.join(host) or 'no host TU') + ' preprocess identically')

        # The Windows policy overlay still applies on top of this one.
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-launcher.patch')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
