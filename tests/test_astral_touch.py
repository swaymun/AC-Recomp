"""Desktop touch screen patch, compiled with synthetic platform stubs. CPU only."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import test_astral_launcher as launcher  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the launcher's, then this overlay last.
OVERLAY = 'astral-touch.patch'
ORDER = (*launcher.ORDER, OVERLAY)
TOUCH = ROOT / 'runtime/patches/astral-touch.patch'


def added_file(patch: Path, path: str) -> str:
    """The new side (context and '+' lines) of one file's hunks."""
    text = patch.read_text()
    part = text.split(f'+++ b/{path}\n', 1)[1].split('\ndiff --git ', 1)[0]
    return '\n'.join(l[1:] for l in part.splitlines() if l[:1] in ('+', ' ', '')) + '\n'


def touch_block() -> str:
    body = added_file(TOUCH, 'runtime/src/hle_hid.cpp')
    start = body.index('// nn::hid::TouchScreenState<N>')
    end = body.index('void GetTouchScreenState(CPU& c)')
    return body[start:end]


TOUCH_FIXTURE = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <vector>
namespace nx::plat {
struct TouchPoint { uint64_t id; float x, y; };
std::vector<TouchPoint> g_points;
uint32_t g_w = 2622, g_h = 1206;
uint64_t g_now = 1000;
size_t read_touches(TouchPoint* out, size_t max) {
    size_t n = std::min(max, g_points.size());
    std::copy(g_points.begin(), g_points.begin() + n, out);
    return n;
}
void window_size(uint32_t& w, uint32_t& h) { w = g_w; h = g_h; }
uint64_t monotonic_ns() { return g_now; }
}
namespace nx { namespace {
using namespace plat;
BLOCK
}
void fill(uint8_t* p) { fill_touch_state(p, 16); }
}
template <class T> T at(const uint8_t* p, size_t off) { T v; std::memcpy(&v, p + off, sizeof v); return v; }
int main() {
    using namespace nx::plat;
    uint8_t s[0x290];
    std::memset(s, 0xcc, sizeof s);
    nx::fill(s);  // nothing held
    assert(at<int64_t>(s, 0) == 1 && at<int32_t>(s, 8) == 0 && at<uint32_t>(s, 0xc) == 0);
    for (size_t k = 0x10; k < sizeof s; ++k) assert(s[k] == 0);
    // 2622x1206 is wider than 16:9: the picture is 2144 wide, centred; the window centre is the screen centre.
    g_points = {{77, 0.5f, 0.5f}, {78, 0.0f, 1.0f}};
    g_now = 5000;
    nx::fill(s);
    assert(at<int64_t>(s, 0) == 2 && at<int32_t>(s, 8) == 2);
    const uint8_t* t0 = s + 0x10;
    const uint8_t* t1 = s + 0x10 + 0x28;
    assert(at<int64_t>(t0, 0) == 0 && at<uint32_t>(t0, 8) == 1 && at<uint32_t>(t0, 0xc) == 0);
    assert(at<uint32_t>(t0, 0x10) == 640 && at<uint32_t>(t0, 0x14) == 360);
    assert(at<uint32_t>(t0, 0x18) == 15 && at<uint32_t>(t0, 0x1c) == 15 && at<int32_t>(t0, 0x20) == 0);
    assert(at<uint32_t>(t1, 0xc) == 1 && at<uint32_t>(t1, 0x10) == 0 && at<uint32_t>(t1, 0x14) == 719);  // bar clamps
    // Held: no start attribute, delta time since the first sample, same finger.
    g_points = {{77, 0.6f, 0.25f}, {78, 0.0f, 1.0f}};
    g_now = 9000;
    nx::fill(s);
    assert(at<uint32_t>(t0, 8) == 0 && at<int64_t>(t0, 0) == 4000 && at<uint32_t>(t0, 0xc) == 0);
    assert(at<int64_t>(s, 0) == 2);  // same 60 Hz period, same contacts: the sampling number does not advance
    assert(at<uint32_t>(t0, 0x14) == 180);
    // Contact 77 lifts: reported once with the end attribute at its last position, then its finger id is free.
    g_points = {{78, 0.0f, 1.0f}};
    nx::fill(s);
    assert(at<int32_t>(s, 8) == 2);
    assert(at<uint32_t>(t0, 0xc) == 1 && at<uint32_t>(t0, 8) == 0);
    assert(at<uint32_t>(t1, 0xc) == 0 && at<uint32_t>(t1, 8) == 2 && at<uint32_t>(t1, 0x14) == 180);
    g_points = {{78, 0.0f, 1.0f}, {90, 0.5f, 0.5f}};
    nx::fill(s);
    assert(at<int32_t>(s, 8) == 2 && at<uint32_t>(t1, 0xc) == 0 && at<uint32_t>(t1, 8) == 1);  // lowest free id reused
    // A 4:3 window (iPad): bars above and below.
    g_w = 2048, g_h = 1536;
    g_points = {{90, 0.5f, 0.5f}, {78, 0.5f, 0.0f}};
    nx::fill(s);
    assert(at<uint32_t>(t0, 0x10) == 640 && at<uint32_t>(t0, 0x14) == 360);
    assert(at<uint32_t>(t1, 0x14) == 0);
    // The sampling number follows host time (60 Hz), never per call and never backwards.
    int64_t before = at<int64_t>(s, 0);
    nx::fill(s);
    assert(at<int64_t>(s, 0) == before);
    g_now = 100ull * 16666667ull + 5;
    nx::fill(s);
    assert(at<int64_t>(s, 0) == 101);
    g_now = 50;  // a clock read earlier than the last one
    nx::fill(s);
    assert(at<int64_t>(s, 0) == 101);
    // At most 16 contacts.
    g_points.clear();
    for (uint64_t k = 0; k < 20; ++k) g_points.push_back({100 + k, 0.5f, 0.5f});
    nx::fill(s);
    nx::fill(s);
    assert(at<int32_t>(s, 8) == 16);
    return 0;
}
'''

class TouchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.cxx = shutil.which('clang++')
        if not self.cxx:
            self.skipTest('C++ compiler unavailable')

    def tearDown(self):
        self.tmp.cleanup()

    def build_and_run(self, source, *extra, name='fixture'):
        src = self.d / f'{name}.cpp'
        src.write_text(source)
        exe = self.d / name
        subprocess.run([self.cxx, '-std=c++20', '-pthread', '-O1', *extra, str(src), '-o', str(exe)],
                       check=True, capture_output=True, text=True, timeout=120)
        return exe

    def test_touch_screen_state_layout_attributes_fingers_and_letterbox(self):
        exe = self.build_and_run(TOUCH_FIXTURE.replace('BLOCK', touch_block()))
        subprocess.run([str(exe)], check=True, timeout=30)

    def test_touch_hook_is_registered_for_the_sdk_symbol_and_platforms_implement_it(self):
        text = TOUCH.read_text()
        self.assertIn('+NX_HLE("_ZN2nn3hid19GetTouchScreenStateILm16EEEvPNS0_16TouchScreenStateIXT_EEE", '
                      'GetTouchScreenState);', text)
        for path in ('platform_mac.cpp', 'platform_linux.cpp', 'platform_win.cpp', 'platform_android_input.cpp'):
            self.assertIn('size_t read_touches(TouchPoint', added_file(TOUCH, f'runtime/src/{path}'))
        mac = added_file(TOUCH, 'runtime/src/platform_mac.cpp')
        self.assertIn('SDL_BUTTON_LMASK', mac)
        self.assertNotIn('int main', mac)  # the hunk stays out of main() (the launcher patch owns it)


if __name__ == '__main__':
    unittest.main()
