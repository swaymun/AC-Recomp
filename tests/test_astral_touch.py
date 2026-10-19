"""Touch screen (astral-touch.patch), the iOS input bridge touch points and the iOS subgroup rewrite
(ios-astral-parity.patch), compiled from the shipped patch/host bytes with synthetic stubs. CPU only."""
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
import test_astral_launcher as launcher  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the launcher's, then this overlay last.
OVERLAY = 'astral-touch.patch'
ORDER = (*launcher.ORDER, OVERLAY)
TOUCH = ROOT / 'runtime/patches/astral-touch.patch'
PARITY = ROOT / 'runtime/patches/ios-astral-parity.patch'


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

BRIDGE_FIXTURE = r'''
#include "InputBridge.h"
#include <cassert>
#include <cmath>
int main() {
    ACSTouchPoint p[ACS_TOUCH_MAX + 4];
    acs_input_release_all();
    assert(acs_touch_poll(p, ACS_TOUCH_MAX) == 0);
    assert(acs_touch_begin(1, 0.25f, 0.75f));
    assert(!acs_touch_begin(1, 0.5f, 0.5f));  // duplicate id
    assert(!acs_touch_begin(2, NAN, 0.5f));
    assert(acs_touch_begin(3, -1.0f, 2.0f));  // clamped
    assert(acs_touch_poll(p, ACS_TOUCH_MAX) == 2);
    assert(p[0].id == 1 && p[0].x == 0.25f && p[0].y == 0.75f && p[1].id == 3 && p[1].x == 0 && p[1].y == 1);
    acs_touch_move(1, 0.5f, 0.5f);
    acs_touch_move(99, 0.1f, 0.1f);  // unknown: harmless
    acs_touch_end(3);
    assert(acs_touch_poll(p, ACS_TOUCH_MAX) == 1 && p[0].x == 0.5f);
    for (uint64_t k = 10; k < 10 + ACS_TOUCH_MAX; ++k) acs_touch_begin(k, 0.5f, 0.5f);
    assert(acs_touch_poll(p, ACS_TOUCH_MAX + 4) == ACS_TOUCH_MAX);  // capacity
    // Touch points and controls are independent; both show in active_touches; release_all clears both.
    assert(acs_input_begin(500, ACS_DPAD_LEFT, 0, 0));
    assert(acs_input_begin(501, ACS_STICK_L_CLICK, 0, 0));
    ACSInputState s = acs_input_poll();
    assert(s.abi_version == ACS_INPUT_ABI_VERSION && s.active_touches == ACS_TOUCH_MAX + 2);
    assert(s.buttons == (ACS_BUTTON(ACS_DPAD_LEFT) | ACS_BUTTON(ACS_STICK_L_CLICK)));
    acs_input_release_all();
    assert(acs_touch_poll(p, ACS_TOUCH_MAX) == 0 && acs_input_poll().buttons == 0);
    return 0;
}
'''

SUBGROUP_DRIVER = r'''
#include <cstdint>
#include <cstdio>
#include <vector>
namespace nx::nvn { bool scalarize_subgroups(const std::vector<uint32_t>&, std::vector<uint32_t>&); }
int main(int, char** v) {
    FILE* f = std::fopen(v[1], "rb");
    std::vector<uint32_t> in;
    uint32_t w;
    while (std::fread(&w, 4, 1, f) == 1) in.push_back(w);
    std::fclose(f);
    std::vector<uint32_t> out;
    if (!nx::nvn::scalarize_subgroups(in, out)) return 3;
    f = std::fopen(v[2], "wb");
    std::fwrite(out.data(), 4, out.size(), f);
    std::fclose(f);
}
'''

# A synthetic compute shader with the operations the translated shaders use (original test input).
SUBGROUP_ASM = '''
               OpCapability Shader
               OpCapability GroupNonUniform
               OpCapability GroupNonUniformBallot
               OpCapability GroupNonUniformShuffle
               OpCapability GroupNonUniformVote
               OpMemoryModel Logical GLSL450
               OpEntryPoint GLCompute %main "main" %lane %lt
               OpExecutionMode %main LocalSize 32 1 1
               OpDecorate %lane BuiltIn SubgroupLocalInvocationId
               OpDecorate %lt BuiltIn SubgroupLtMask
               OpDecorate %buf DescriptorSet 0
               OpDecorate %buf Binding 0
               OpDecorate %Out Block
               OpMemberDecorate %Out 0 Offset 0
               OpDecorate %arr ArrayStride 4
       %void = OpTypeVoid
         %fn = OpTypeFunction %void
       %bool = OpTypeBool
       %uint = OpTypeInt 32 0
      %float = OpTypeFloat 32
    %ptr_in_u = OpTypePointer Input %uint
       %lane = OpVariable %ptr_in_u Input
     %v4uint = OpTypeVector %uint 4
   %ptr_in_v4 = OpTypePointer Input %v4uint
         %lt = OpVariable %ptr_in_v4 Input
     %uint_0 = OpConstant %uint 0
     %uint_3 = OpConstant %uint 3
    %float_1 = OpConstant %float 1
        %arr = OpTypeRuntimeArray %float
        %Out = OpTypeStruct %arr
    %ptr_sb = OpTypePointer StorageBuffer %Out
        %buf = OpVariable %ptr_sb StorageBuffer
   %ptr_sb_f = OpTypePointer StorageBuffer %float
      %int_0 = OpConstant %uint 0
       %main = OpFunction %void None %fn
      %entry = OpLabel
          %l = OpLoad %uint %lane
        %ltp = OpAccessChain %ptr_in_u %lt %uint_0
        %ltx = OpLoad %uint %ltp
          %c = OpIEqual %bool %l %uint_0
          %b = OpGroupNonUniformBallot %v4uint %uint_3 %c
         %bx = OpCompositeExtract %uint %b 0
         %bm = OpBitwiseAnd %uint %bx %ltx
         %e = OpGroupNonUniformElect %bool %uint_3
         %a = OpGroupNonUniformAll %bool %uint_3 %e
          %s = OpGroupNonUniformShuffle %float %uint_3 %float_1 %bm
         %sx = OpGroupNonUniformShuffleXor %float %uint_3 %s %uint_3
         %sel = OpSelect %float %a %sx %float_1
          %p = OpAccessChain %ptr_sb_f %buf %int_0 %l
               OpStore %p %sel
               OpReturn
               OpFunctionEnd
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
        self.assertIn('size_t read_touches(TouchPoint* out', added_file(PARITY, 'runtime/src/platform_ios.mm'))

    def test_ios_bridge_touch_points(self):
        exe = self.build_and_run(BRIDGE_FIXTURE, '-I' + str(ROOT / 'ports/ios'), str(ROOT / 'ports/ios/InputBridge.cpp'))
        subprocess.run([str(exe)], check=True, timeout=30)

    def test_overlay_routes_off_control_touches_to_the_touch_screen(self):
        app = (ROOT / 'ports/ios/App.mm').read_text()
        self.assertIn('acs_touch_begin(identity, p.x / size.width, p.y / size.height)', app)
        for control in ('ACS_DPAD_UP', 'ACS_DPAD_DOWN', 'ACS_DPAD_LEFT', 'ACS_DPAD_RIGHT', 'ACS_STICK_L_CLICK',
                        'ACS_STICK_R_CLICK', 'ACS_ZL', 'ACS_ZR', 'ACS_PLUS', 'ACS_MINUS'):
            self.assertRegex(app, re.escape(f'_regions[{control}]'))
        self.assertIn('NX_IOS_OVERLAY', app)
        self.assertIn('controls-hidden', app)

    def test_subgroup_rewrite_produces_a_valid_module_without_subgroup_operations(self):
        tools = [shutil.which(t) for t in ('spirv-as', 'spirv-val', 'spirv-dis')]
        if not all(tools):
            self.skipTest('SPIRV-Tools unavailable')
        impl = self.d / 'nvn_spirv_subgroup.cpp'
        impl.write_text(added_file(PARITY, 'runtime/src/nvn/nvn_spirv_subgroup.cpp'))
        exe = self.build_and_run(SUBGROUP_DRIVER, '-DNX_ASTRAL_STRICT=1', '-DNX_IOS_RUNTIME=1', str(impl), name='sub')
        (self.d / 'in.spvasm').write_text(SUBGROUP_ASM)
        subprocess.run([tools[0], '--target-env', 'vulkan1.1', str(self.d / 'in.spvasm'), '-o', str(self.d / 'in.spv')],
                       check=True, capture_output=True, timeout=30)
        subprocess.run([tools[1], '--target-env', 'vulkan1.1', str(self.d / 'in.spv')], check=True, timeout=30)
        subprocess.run([str(exe), str(self.d / 'in.spv'), str(self.d / 'out.spv')], check=True, timeout=30)
        subprocess.run([tools[1], '--target-env', 'vulkan1.1', str(self.d / 'out.spv')], check=True, timeout=30)
        dis = subprocess.run([tools[2], str(self.d / 'out.spv')], check=True, capture_output=True, text=True,
                             timeout=30).stdout
        self.assertNotRegex(dis, r'GroupNonUniform|BuiltIn Subgroup')
        self.assertIn('Private', dis)
        # Unhandled operations leave the module alone.
        (self.d / 'q.spvasm').write_text(SUBGROUP_ASM.replace(
            '%sx = OpGroupNonUniformShuffleXor %float %uint_3 %s %uint_3',
            '%sx = OpGroupNonUniformFAdd %float %uint_3 Reduce %s').replace(
            'OpCapability GroupNonUniformVote', 'OpCapability GroupNonUniformVote\n               OpCapability GroupNonUniformArithmetic'))
        subprocess.run([tools[0], '--target-env', 'vulkan1.1', str(self.d / 'q.spvasm'), '-o', str(self.d / 'q.spv')],
                       check=True, capture_output=True, timeout=30)
        self.assertEqual(subprocess.run([str(exe), str(self.d / 'q.spv'), str(self.d / 'q2.spv')], timeout=30).returncode, 3)


if __name__ == '__main__':
    unittest.main()
