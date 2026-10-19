"""CPU regression of the optional performance HUD overlay (astral-perf-hud.patch).

The overlay is applied after the native overlay stack, astral-shared-font.patch and astral-swkbd.patch on a fresh copy
of the pinned public runtime. The production perf_hud.cpp and nvn/nvn_hud.cpp are compiled with a fixture: the 8x8
text rasteriser draws known strings and every pixel of a glyph is checked against an independent copy of the font's
documented 'A'; the scale rule, top-right placement and dump compositing are checked on synthetic buffers; the 1 s
statistics window runs on a fake clock; the Vulkan copy onto the swapchain image is recorded through fake command
functions; the hand-over to native overlays (Apple's Metal HUD on macOS, MangoHud on Linux) is checked with fake
show functions, temporary layer-manifest directories and the environment it sets. The changed translation units get
strict syntax checks in the Mac profile, and the default profile's preprocessed source must be unchanged. No game,
GPU, window or device is used.
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

# The native overlay order: test_nvn_window_depth.NATIVE_ORDER, astral-nvn-window-depth, -bc-zero-fill,
# -cube-storage (font.ORDER), then the shared font and software keyboard, then this overlay.
BEFORE = ('astral-shared-font.patch', 'astral-swkbd.patch')
OVERLAY = 'astral-perf-hud.patch'
ORDER = (*font.ORDER, *BEFORE, OVERLAY)
NEW = ['runtime/src/font8x8_basic.h', 'runtime/src/nvn/nvn_hud.cpp', 'runtime/src/perf_hud.cpp',
       'runtime/src/perf_hud.h']
MODIFIED = ['CMakeLists.txt', 'runtime/src/nvn/nvn_debug.cpp', 'runtime/src/nvn/nvn_queue.cpp',
            'runtime/src/nvn/nvn_vk.cpp', 'runtime/src/nvn/nvn_vk.h', 'runtime/src/platform_linux.cpp',
            'runtime/src/platform_mac.cpp', 'runtime/src/platform_win.cpp']

FIXTURE = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <nx/runtime.h>
#include "platform.h"
namespace nx {
void log(const char*, ...) {}
namespace plat {
uint64_t fake_ns = 1'000'000'000;
uint64_t monotonic_ns() { return fake_ns; }
}  // namespace plat
}  // namespace nx
#include "perf_hud.cpp"
#include "nvn/nvn_hud.cpp"

// ---- fake Vulkan recording ----
struct Barrier { VkImageLayout from, to; VkImage image; };
std::vector<Barrier> barriers;
std::vector<VkBufferImageCopy> copies;
VkImageLayout copy_layout = VK_IMAGE_LAYOUT_UNDEFINED;
VKAPI_ATTR void VKAPI_CALL fake_barrier(VkCommandBuffer, VkPipelineStageFlags, VkPipelineStageFlags, VkDependencyFlags,
    uint32_t, const VkMemoryBarrier*, uint32_t, const VkBufferMemoryBarrier*, uint32_t n, const VkImageMemoryBarrier* b) {
    for (uint32_t k = 0; k < n; k++) barriers.push_back({b[k].oldLayout, b[k].newLayout, b[k].image});
}
VKAPI_ATTR void VKAPI_CALL fake_copy(VkCommandBuffer, VkBuffer, VkImage, VkImageLayout layout, uint32_t n,
                                     const VkBufferImageCopy* r) {
    copy_layout = layout;
    for (uint32_t k = 0; k < n; k++) copies.push_back(r[k]);
}
namespace nx::vk {
PFN_vkCmdPipelineBarrier p_vkCmdPipelineBarrier = fake_barrier;
PFN_vkCmdCopyBufferToImage p_vkCmdCopyBufferToImage = fake_copy;
}  // namespace nx::vk
std::vector<uint8_t> ring(1 << 24);
uint64_t ring_used = 0;
namespace nx::nvn {
Upload upload_alloc(uint64_t size, uint64_t align) {
    uint64_t at = (ring_used + 3 + align - 1) & ~(align - 1);  // never at 0: the offset must be passed on
    ring_used = at + size;
    return {reinterpret_cast<VkBuffer>(uintptr_t(0xb0f)), at, ring.data() + at};
}
}  // namespace nx::nvn

using namespace nx;
using hud::Bitmap;
// The font's documented 'A' (README of dhepper/font8x8), independent of the table in font8x8_basic.h.
const char* kA[8] = {"..XX....", ".XXXX...", "XX..XX..", "XX..XX..", "XXXXXX..", "XX..XX..", "XX..XX..", "........"};
const uint8_t BG[4] = {0x10, 0x10, 0x18, 0xff}, FG[4] = {0xff, 0xff, 0xff, 0xff}, BG_BGRA[4] = {0x18, 0x10, 0x10, 0xff};
bool px_is(const Bitmap& b, uint32_t x, uint32_t y, const uint8_t* c) { return !std::memcmp(&b.px[(size_t(y) * b.width + x) * 4], c, 4); }
bool glyph_a_at(const Bitmap& b, uint32_t x0, uint32_t y0, uint32_t s) {
    for (uint32_t y = 0; y < 8 * s; y++)
        for (uint32_t x = 0; x < 8 * s; x++)
            if (!px_is(b, x0 + x, y0 + y, kA[y / s][x / s] == 'X' ? FG : BG)) return false;
    return true;
}
int main() {
    // ---- rasteriser ----
    Bitmap a = hud::rasterise({"A"}, 1, false);
    assert(a.width == 16 && a.height == 16 && a.px.size() == 16 * 16 * 4);
    assert(glyph_a_at(a, 4, 4, 1));
    for (uint32_t k = 0; k < 16; k++)  // the 4-pixel border is background all round
        for (uint32_t d : {0u, 1u, 2u, 3u, 12u, 13u, 14u, 15u})
            assert(px_is(a, k, d, BG) && px_is(a, d, k, BG));
    Bitmap a2 = hud::rasterise({"A"}, 2, false);
    assert(a2.width == 32 && a2.height == 32 && glyph_a_at(a2, 8, 8, 2));
    Bitmap ab = hud::rasterise({"A"}, 1, true);
    assert(px_is(ab, 0, 0, BG_BGRA) && px_is(ab, 4 + 2, 4, FG));  // B,G,R,A order
    Bitmap two = hud::rasterise({"AA", "", "xA"}, 1, false);  // longest line sets the width; 2-pixel line gaps
    assert(two.width == 8 + 3 * 8 - 8 && two.height == 8 + 3 * 8 + 2 * 2);
    assert(glyph_a_at(two, 4, 4, 1) && glyph_a_at(two, 12, 4, 1) && glyph_a_at(two, 12, 4 + 2 * 10, 1));
    for (uint32_t y = 14; y < 24; y++) for (uint32_t x = 0; x < two.width; x++) assert(px_is(two, x, y, BG));  // empty line
    Bitmap q = hud::rasterise({"?"}, 1, false), e = hud::rasterise({"\xe9"}, 1, false), t = hud::rasterise({"\t"}, 1, false);
    assert(q.px == e.px && q.px == t.px && q.px != hud::rasterise({" "}, 1, false).px);  // non-printable: '?'
    assert(hud::rasterise({}, 2, false).px.empty() && hud::rasterise({"A"}, 0, false).px.empty());
    std::cout << "PASS rasteriser: glyph A pixel-exact at scale 1 and 2, border, BGRA order, lines and gaps, '?' fallback\n";

    // ---- scale and placement ----
    assert(hud::scale_for(0) == 1 && hud::scale_for(720) == 1 && hud::scale_for(800) == 1 && hud::scale_for(1080) == 2 &&
           hud::scale_for(1440) == 3 && hud::scale_for(2160) == 4);
    uint32_t x = 0, y = 0;
    assert(hud::corner(a, 100, 60, 1, x, y) && x == 100 - 16 - 4 && y == 4);
    assert(!hud::corner(a, 19, 60, 1, x, y) && !hud::corner(a, 100, 19, 1, x, y) && hud::corner(a, 20, 20, 1, x, y));
    std::vector<uint8_t> img(100 * 60 * 4, 0x77);
    assert(hud::composite(a, 1, img.data(), 100, 60));
    for (uint32_t yy = 0; yy < 60; yy++)
        for (uint32_t xx = 0; xx < 100; xx++) {
            bool in = xx >= 80 && xx < 96 && yy >= 4 && yy < 20;
            const uint8_t* p = &img[(size_t(yy) * 100 + xx) * 4];
            if (in) assert(!std::memcmp(p, &a.px[(size_t(yy - 4) * 16 + xx - 80) * 4], 4));
            else assert(p[0] == 0x77 && p[1] == 0x77 && p[2] == 0x77 && p[3] == 0x77);
        }
    std::vector<uint8_t> small(10 * 10 * 4, 0x77);
    assert(!hud::composite(a, 1, small.data(), 10, 10) && small == std::vector<uint8_t>(10 * 10 * 4, 0x77));
    std::cout << "PASS placement: 2x at 1080p, top-right corner with a margin, pixels outside untouched, too small skipped\n";

    // ---- text ----
    assert(hud::speed_pct(30, 2) == 100 && hud::speed_pct(60, 1) == 100 && hud::speed_pct(45, 2) == 150 &&
           hud::speed_pct(30, 0) == 50);
    hud::Sample s;
    s.fps = 29.96, s.avg_ms = 33.38, s.max_ms = 41.04, s.interval = 2, s.cpu_pct = 245.4, s.cores = 10, s.rss_mb = 1234.4;
    s.thermal = "nominal", s.gpu = "Apple M9 Max", s.out_w = 1920, s.out_h = 1080, s.game_w = 1280, s.game_h = 720;
    std::vector<std::string> want = {"FPS 30.0", "Frame 33.4 ms avg, 41.0 max", "Speed 100% of 30 fps",
        "CPU 245% (10 cores)", "RAM 1234 MB", "Thermal nominal", "GPU Apple M9 Max", "1920x1080, game 1280x720"};
    assert(hud::format(s) == want);
    s.cpu_pct = -1, s.rss_mb = -1, s.out_w = s.out_h = 0, s.interval = 1, s.thermal = "n/a";
    s.gpu = std::string(60, 'G');
    auto f = hud::format(s);
    assert(f[2] == "Speed 50% of 60 fps" && f[3] == "CPU n/a" && f[4] == "RAM n/a" && f[5] == "Thermal n/a" &&
           f[6] == "GPU " + std::string(40, 'G') && f[7] == "headless, game 1280x720");
    std::cout << "PASS text: every line, n/a values, headless, long GPU names cut at 40\n";

    // ---- the 1 s window on a fake clock ----
    setenv("NX_PERF_HUD", "1", 1);
    assert(hud::enabled());
    hud::set_gpu("Test GPU 9000");
    hud::note_interval(2);
    hud::on_present(1280, 720, 1920, 1080);  // starts the window
    assert(hud::lines()[0] == "FPS 0.0" && hud::lines()[6] == "GPU Test GPU 9000");
    for (int k = 0; k < 30; k++) {  // 29 intervals of 33.333 ms and one of 50 ms: 30 presents over 1.0167 s
        plat::fake_ns += k == 10 ? 50'000'000 : 33'333'333;
        hud::on_present(1280, 720, 1920, 1080);
    }
    auto l = hud::lines();
    assert(l.size() == 8 && l[0] == "FPS 29.5" && l[1] == "Frame 33.9 ms avg, 50.0 max" && l[2] == "Speed 98% of 30 fps");
    assert(l[3].rfind("CPU ", 0) == 0 && l[3].find("cores)") != std::string::npos);
    assert(l[4].rfind("RAM ", 0) == 0 && l[5].rfind("Thermal ", 0) == 0 && l[7] == "1920x1080, game 1280x720");
    auto b1 = hud::bitmap(1080, true), b1again = hud::bitmap(1080, true), b720 = hud::bitmap(720, true);
    assert(b1 == b1again && b1 != b720 && b1->width == 2 * b720->width && b1->px == hud::rasterise(l, 2, true).px);
    for (int k = 0; k < 31; k++) plat::fake_ns += 33'333'333, hud::on_present(1280, 720, 0, 0);  // headless
    l = hud::lines();
    assert(l[0] == "FPS 30.0" && l[1] == "Frame 33.3 ms avg, 33.3 max" && l[2] == "Speed 100% of 30 fps" &&
           l[7] == "headless, game 1280x720");
    assert(hud::bitmap(1080, true) != b1);  // new text: re-rasterised
    std::cout << "PASS window: FPS, frame time avg/max, game speed from the present interval, headless line, bitmap cache\n";

    // ---- host probes (this process) ----
    assert(hud::process_cpu_seconds() >= 0);
#if defined(__APPLE__) || defined(__linux__)
    assert(hud::resident_bytes() > 0);
#endif
#if defined(__APPLE__)
    std::string th = hud::thermal_state();
    assert(th == "nominal" || th == "moderate" || th == "heavy" || th == "trapping" || th == "sleeping");
    std::cout << "PASS probes: CPU time, resident " << hud::resident_bytes() / (1024 * 1024) << " MB, thermal " << th << "\n";
#endif

    // ---- dumped frames (CPU) ----
    std::vector<uint8_t> frame(1920 * 1080 * 4, 0x33);
    auto hb = hud::bitmap(1080, false);
    assert(hud::composite_frame(frame.data(), 1920, 1080, false));
    uint32_t hx = 1920 - 8 - hb->width;
    assert(!std::memcmp(&frame[(size_t(8) * 1920 + hx) * 4], BG, 4));                       // HUD top-left corner
    assert(!std::memcmp(&frame[(size_t(8) * 1920 + 1920 - 9) * 4], BG, 4));                  // top-right
    assert(frame[(size_t(7) * 1920 + 1920 - 9) * 4] == 0x33 && frame[(size_t(8) * 1920 + 1919) * 4] == 0x33);  // margin
    assert(frame[(size_t(8) * 1920 + hx - 1) * 4] == 0x33 && frame[0] == 0x33);
    assert(!std::memcmp(&frame[(size_t(8 + hb->height - 1) * 1920 + hx) * 4], BG, 4));
    assert(frame[(size_t(8 + hb->height) * 1920 + hx) * 4] == 0x33);
    std::cout << "PASS dumps: HUD composited top-right of a 1920x1080 frame at 2x, the rest untouched\n";

    // ---- the swapchain copy (Vulkan commands recorded through fakes) ----
    VkCommandBuffer cb = reinterpret_cast<VkCommandBuffer>(uintptr_t(0xc0));
    VkImage sc = reinterpret_cast<VkImage>(uintptr_t(0x5c));
    nvn::hud_record(cb, sc, VK_FORMAT_B8G8R8A8_UNORM, {1920, 1080});
    auto hbgra = hud::bitmap(1080, true);
    assert(barriers.size() == 2 && copies.size() == 1 && copy_layout == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    assert(barriers[0].from == VK_IMAGE_LAYOUT_PRESENT_SRC_KHR && barriers[0].to == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    assert(barriers[1].from == VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL && barriers[1].to == VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    assert(barriers[0].image == sc && barriers[1].image == sc);
    const VkBufferImageCopy& c = copies[0];
    assert(c.imageOffset.x == int32_t(1920 - 8 - hbgra->width) && c.imageOffset.y == 8 && c.imageOffset.z == 0);
    assert(c.imageExtent.width == hbgra->width && c.imageExtent.height == hbgra->height && c.imageExtent.depth == 1);
    assert(c.bufferOffset % 16 == 0 && c.bufferOffset != 0 && c.bufferRowLength == 0 && c.bufferImageHeight == 0);
    assert(!std::memcmp(ring.data() + c.bufferOffset, hbgra->px.data(), hbgra->px.size()));
    assert(px_is(*hbgra, 0, 0, BG_BGRA));  // a BGRA swapchain gets BGRA bytes
    barriers.clear(), copies.clear();
    nvn::hud_record(cb, sc, VK_FORMAT_R16G16B16A16_SFLOAT, {1920, 1080});  // not a 4-byte UNORM/SRGB format
    nvn::hud_record(cb, sc, VK_FORMAT_R8G8B8A8_UNORM, {64, 32});            // does not fit
    assert(barriers.empty() && copies.empty());
    nvn::hud_record(cb, sc, VK_FORMAT_R8G8B8A8_UNORM, {1280, 720});
    assert(copies.size() == 1 && copies[0].imageOffset.x == int32_t(1280 - 4 - hud::bitmap(720, false)->width) &&
           copies[0].imageOffset.y == 4);
    assert(!std::memcmp(ring.data() + copies[0].bufferOffset, hud::bitmap(720, false)->px.data(), 16));  // RGBA bytes
    std::cout << "PASS swapchain copy: present -> transfer dst -> present, top-right offset, uploaded bytes, skips\n";

    // ---- F3 off ----
    hud::toggle();
    assert(!hud::enabled());
    barriers.clear(), copies.clear();
    nvn::hud_record(cb, sc, VK_FORMAT_B8G8R8A8_UNORM, {1920, 1080});
    std::vector<uint8_t> untouched(1920 * 1080 * 4, 0x44);
    assert(barriers.empty() && copies.empty() && !hud::composite_frame(untouched.data(), 1920, 1080, false));
    auto before = hud::lines();
    for (int k = 0; k < 40; k++) plat::fake_ns += 10'000'000, hud::on_present(1, 1, 1, 1);
    assert(hud::lines() == before);
    hud::toggle();
    assert(hud::enabled());
    std::cout << "PASS toggle: off records nothing, composites nothing and measures nothing; on again\n";

    // ---- native overlays (Apple's Metal HUD, MangoHud) ----
    assert(hud::native_wanted_at_start("1", "") && hud::native_wanted_at_start("yes", "perf_hud = 0"));
    assert(!hud::native_wanted_at_start("0", "perf_hud = 1") && !hud::native_wanted_at_start("", "perf_hud = 1"));
    assert(!hud::native_wanted_at_start(nullptr, "") && !hud::native_wanted_at_start(nullptr, "perf_hud = 0\n"));
    assert(hud::native_wanted_at_start(nullptr, "# x\n[settings]\r\n  Perf_HUD =  On \r\nmute = 1\n"));
    assert(hud::native_wanted_at_start(nullptr, "perf_hud=true") && !hud::native_wanted_at_start(nullptr, "perf_hud2 = 1"));
    setenv("NX_PERF_HUD", "Ac", 1);  // the built-in HUD, forced
    assert(hud::builtin_forced() && !hud::native_wanted_at_start("Ac", "perf_hud = 1"));
    static int shows = 0;
    static bool shown = false;
    auto ok = [](bool on) { shows++, shown = on; return true; };
    assert(!hud::use_native(ok, "Fake") && shows == 0 && hud::enabled() && !hud::native_name());
    setenv("NX_PERF_HUD", "1", 1);
    assert(!hud::builtin_forced() && !hud::use_native(nullptr, "Null"));
    assert(!hud::use_native([](bool) { return false; }, "Broken") && hud::enabled() && !hud::native_name());  // stays ours
    // MangoHud's manifest in the loader's implicit-layer directories.
    std::filesystem::create_directories("layers-none");
    std::filesystem::create_directories("layers-mango");
    std::ofstream("layers-none/VkLayer_other.json") << "{}";
    std::ofstream("layers-none/MangoHud.txt") << "{}";
    std::ofstream("layers-mango/MangoHud.x86_64.json") << "{}";
    assert(!hud::mangohud_installed({}) && !hud::mangohud_installed({"layers-none", "does-not-exist"}));
    assert(hud::mangohud_installed({"does-not-exist", "layers-none", "layers-mango"}));
    setenv("HOME", "/home/p", 1), setenv("XDG_CONFIG_HOME", "/c", 1), setenv("XDG_CONFIG_DIRS", "/d1:/d2", 1);
    setenv("XDG_DATA_HOME", "/h", 1), setenv("XDG_DATA_DIRS", "/s1::/s2", 1);
    std::vector<std::string> dirs = {"/c/vulkan/implicit_layer.d", "/d1/vulkan/implicit_layer.d",
        "/d2/vulkan/implicit_layer.d", "/etc/vulkan/implicit_layer.d", "/h/vulkan/implicit_layer.d",
        "/s1/vulkan/implicit_layer.d", "/s2/vulkan/implicit_layer.d"};
    assert(hud::vulkan_implicit_layer_dirs() == dirs);
    unsetenv("XDG_CONFIG_HOME"), unsetenv("XDG_CONFIG_DIRS"), unsetenv("XDG_DATA_HOME"), unsetenv("XDG_DATA_DIRS");
    dirs = {"/home/p/.config/vulkan/implicit_layer.d", "/etc/xdg/vulkan/implicit_layer.d", "/etc/vulkan/implicit_layer.d",
        "/home/p/.local/share/vulkan/implicit_layer.d", "/usr/local/share/vulkan/implicit_layer.d",
        "/usr/share/vulkan/implicit_layer.d"};
    assert(hud::vulkan_implicit_layer_dirs() == dirs);
    unsetenv("MANGOHUD"), unsetenv("MANGOHUD_CONFIG"), unsetenv("MANGOHUD_CONFIGFILE");
    assert(!hud::start_mangohud({"layers-none"}) && !std::getenv("MANGOHUD") && hud::enabled());  // not installed
    setenv("MANGOHUD", "0", 1);  // the player said no
    assert(!hud::start_mangohud({"layers-mango"}) && hud::enabled());
    unsetenv("MANGOHUD");
    assert(!hud::prepare_native_overlay());  // not Linux: nothing
    // Capture runs (dumps, scripted input, audio dumps) keep the built-in HUD.
    unsetenv("NX_DUMP_FRAMES"), unsetenv("NX_INPUT_SCRIPT"), unsetenv("NX_AUDIO_DUMP");
    std::filesystem::create_directories("root-plain");
    std::filesystem::create_directories("root-dump");
    std::ofstream("root-dump/dump_frames") << "30";
    assert(!hud::capture_run("root-plain") && !hud::capture_run("") && hud::capture_run("root-dump"));
    for (const char* name : {"NX_DUMP_FRAMES", "NX_INPUT_SCRIPT", "NX_AUDIO_DUMP"}) {
        setenv(name, "0", 1);
        assert(!hud::capture_run("root-plain"));
        setenv(name, "", 1);
        assert(!hud::capture_run("root-plain"));
        setenv(name, name[3] == 'I' ? "1:A:0.1" : "out.wav", 1);
        assert(hud::capture_run("root-plain"));
        assert(!hud::start_mangohud_for_run(false, "root-plain", {"layers-mango"}) && !std::getenv("MANGOHUD"));
        unsetenv(name);
    }
    assert(!hud::start_mangohud_for_run(true, "root-plain", {"layers-mango"}) && !std::getenv("MANGOHUD"));  // headless
    assert(!hud::start_mangohud_for_run(false, "root-dump", {"layers-mango"}) && !std::getenv("MANGOHUD"));
    assert(hud::enabled() && !hud::native_name());
    assert(hud::start_mangohud_for_run(false, "root-plain", {"layers-mango"}));
    assert(std::string(std::getenv("MANGOHUD")) == "1" && std::string(std::getenv("MANGOHUD_CONFIG")) == hud::kMangoHudConfig);
    assert(std::string(hud::kMangoHudConfig).rfind("read_cfg,", 0) == 0);  // the player's MangoHud.conf still loads
    assert(std::string(hud::kMangoHudConfig).find(",toggle_hud=F3,") != std::string::npos);
    assert(std::string(hud::native_name()) == "MangoHud" && hud::native_on() && !hud::enabled());
    // The built-in HUD now does nothing: no commands, no dump pixels, no statistics.
    barriers.clear(), copies.clear();
    nvn::hud_record(cb, sc, VK_FORMAT_B8G8R8A8_UNORM, {1920, 1080});
    assert(barriers.empty() && copies.empty() && !hud::composite_frame(untouched.data(), 1920, 1080, false));
    before = hud::lines();
    for (int k = 0; k < 40; k++) plat::fake_ns += 30'000'000, hud::on_present(1280, 720, 1920, 1080);
    assert(hud::lines() == before);
    hud::toggle();  // F3: the native overlay's state, not ours
    assert(!hud::native_on() && !hud::enabled());
    hud::toggle();
    assert(hud::native_on() && !hud::enabled());
    assert(!hud::use_native(ok, "Second") && shows == 0 && !hud::start_mangohud({"layers-mango"}));  // one owner
    std::cout << "PASS native overlays: start decision, NX_PERF_HUD=ac, failed hand-over, capture runs, MangoHud detection and env, "
                 "F3 routed, built-in HUD idle\n";
    return 0;
}
'''


def vulkan_include():
    common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
    if not common.is_absolute():
        common = (ROOT / common).resolve()
    return Path(os.environ.get('NVN_VULKAN_INCLUDE', str(common.parent /
        '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include')))


def sdl_include():
    for d in (os.environ.get('NX_SDL3_INCLUDE', ''), '/opt/homebrew/include', '/usr/local/include', '/usr/include'):
        if d and (Path(d) / 'SDL3/SDL.h').is_file():
            return d
    return None


def added_blocks(patch_text, path):
    """The runs of added lines of one file's hunks."""
    section = patch_text.split(f'diff --git a/{path} b/{path}\n', 1)[1].split('\ndiff --git ', 1)[0]
    blocks, run = [], []
    for line in section.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            run.append(line[1:])
        elif run:
            blocks.append(run)
            run = []
    if run:
        blocks.append(run)
    return blocks


class AstralPerfHudTests(unittest.TestCase):
    def test_overlay_rasteriser_window_copy_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        vulkan = vulkan_include()
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required; no downloads')
        out, source, _ = font.stack_source(self, 'astral-perf-hud')
        for name in BEFORE:
            font.apply(self, source, name)
        stacked = runtime.source_fingerprint(source)
        patch = font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         sorted(NEW + MODIFIED))
        text = patch.read_text()
        src = source / 'runtime/src'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(src), '-I', str(vulkan)]

        # The font table: 95 printable glyphs, the README's 'A', and its public domain notice.
        table = (src / 'font8x8_basic.h').read_text()
        self.assertEqual(len(re.findall(r'^    \{(?:0x[0-9a-f]{2}, ){7}0x[0-9a-f]{2}\},  // U\+00[2-7][0-9A-F]', table, re.M)), 95)
        self.assertIn('{0x0c, 0x1e, 0x33, 0x33, 0x3f, 0x33, 0x33, 0x00},  // U+0041 A', table)
        notice = (ROOT / 'runtime/patches/astral-perf-hud.NOTICE').read_text()
        self.assertIn('Daniel Hepper', notice)
        self.assertIn('Public Domain', notice)

        # CMake lists the two new TUs for Astral only, after the software keyboard.
        cmake = (source / 'CMakeLists.txt').read_text()
        listing = ('if(NX_GAME STREQUAL "astral")\n    list(APPEND NX_RUNTIME_SOURCES runtime/src/perf_hud.cpp '
                   'runtime/src/nvn/nvn_hud.cpp)\nendif()')
        self.assertIn(listing, cmake)
        self.assertGreater(cmake.index(listing), cmake.index('runtime/src/hle_swkbd.cpp'))

        # Where the hooks sit: the HUD goes on the swapchain image after the game's image (drawn or blitted) and
        # before the submit and present; headless presents are measured before the dump decision; dumps get it
        # before the file is written.
        vk = (src / 'nvn/nvn_vk.cpp').read_text()
        present = vk.split('void gpu_present(uint64_t texture, const int32_t* crop) {')[1]
        self.assertLess(present.index('if (!drawn) transition(g_cb, dst, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);'),
                        present.index('hud_record(g_cb, dst.image, g_sc_format, g_sc_extent);'))
        self.assertLess(present.index('hud_record('), present.index('frame_submit(acquired, rendered'))
        self.assertLess(present.index('hud_record('), present.index('p_vkQueuePresentKHR'))
        headless = vk.split('void present_headless(uint64_t texture) {')[1].split('\n}\n')[0]
        self.assertLess(headless.index('hud::on_present('), headless.index('frame_dump_due(presents)'))
        # MangoHud's environment is set in Linux main (astral-launcher.patch, test_astral_launcher), not on the game
        # thread: nvn_vk.cpp does not touch it.
        self.assertNotIn('prepare_native_overlay', vk)
        # macOS: MTL_HUD_ENABLED is decided before SDL (and with it any Metal device) starts; Apple's HUD takes the
        # HUD's state once the game window and its layer exist; F3 still goes through hud::toggle.
        mac = (src / 'platform_mac.cpp').read_text()
        main = mac.split('\nint main() {')[1]
        self.assertLess(main.index('nx::plat::metal_hud::preload();'), main.index('SDL_Init('))
        window = mac.split('void* create_window() {')[1].split('\n}\n')[0]
        self.assertLess(window.index('g_layer = SDL_Metal_GetLayer(g_view);'),
                        window.index('nx::hud::use_native(metal_hud::show, "Apple Metal HUD");'))
        self.assertIn('if (!headless() && metal_hud::g_loaded) nx::hud::use_native(', window)
        preload = mac.split('void preload() {')[1].split('\n}\n')[0]
        self.assertLess(preload.index('if (headless() || nx::hud::capture_run(data_root())) return;'),
                        preload.index('setenv("MTL_HUD_ENABLED", "1", 1);'))
        self.assertIn('nx::hud::native_wanted_at_start(std::getenv("NX_PERF_HUD"), text)', preload)
        self.assertIn('nx::hud::toggle();  // NX_PERF_HUD', main)
        dump = (src / 'nvn/nvn_debug.cpp').read_text().split('void frame_dump_write(')[1].split('\n}\n')[0]
        self.assertLess(dump.index('hud::composite_frame('), dump.index('std::fprintf(f, "P6'))
        # Windows and Linux hosts cannot be preprocessed here: each of their added blocks is a strict-only #if block.
        for host in ('runtime/src/platform_win.cpp', 'runtime/src/platform_linux.cpp'):
            blocks = added_blocks(text, host)
            self.assertEqual(len(blocks), 2, host)
            for block in blocks:
                self.assertEqual((block[0], block[-1]), ('#if defined(NX_ASTRAL_STRICT)', '#endif'), host)
                self.assertFalse(any(re.match(r'\s*#\s*(if|el|endif|define|undef)', line) for line in block[1:-1]), host)

        # The fixture: rasteriser, placement, text, window, probes, dumps, swapchain copy, toggle.
        work = out / 'strict'
        work.mkdir()
        (work / 'fixture.cpp').write_text(FIXTURE)
        build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Wno-unused-parameter',
                                '-Wno-missing-field-initializers', '-DNX_ASTRAL_STRICT=1', *includes,
                                str(work / 'fixture.cpp'), '-o', str(work / 'run')],
                               capture_output=True, text=True, timeout=180)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        result = subprocess.run([str(work / 'run')], cwd=work, capture_output=True, text=True, timeout=60,
                                env={k: v for k, v in os.environ.items() if not k.startswith('NX_')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS'), 9 if sys.platform == 'darwin' else 8, result.stdout)
        print(result.stdout, end='')

        # Strict syntax, Mac profile (the Astral macOS build's definitions), every changed TU that builds here.
        sdl = sdl_include()
        mac = ['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1']
        tus = ['perf_hud.cpp', 'nvn/nvn_hud.cpp', 'nvn/nvn_vk.cpp', 'nvn/nvn_debug.cpp', 'nvn/nvn_queue.cpp']
        if sdl and sys.platform == 'darwin':
            tus.append('platform_mac.cpp')
        extra = ['-I', sdl] if sdl else []
        for flags in (mac, []):
            for name in tus:
                warn = ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter'] if name in ('perf_hud.cpp', 'nvn/nvn_hud.cpp') else []
                check = subprocess.run([compiler, '-std=c++20', *warn, *flags, *includes, *extra, '-fsyntax-only',
                                        str(src / name)], capture_output=True, text=True, timeout=120)
                self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        print('PASS strict (Mac profile) and default syntax: ' + ', '.join(tus))

        # Default profile: the new TUs preprocess to nothing; the changed ones exactly as before.
        for name in ('perf_hud.cpp', 'nvn/nvn_hud.cpp'):
            empty = subprocess.run([compiler, '-std=c++20', '-E', '-P', *includes, str(src / name)],
                                   capture_output=True, text=True, timeout=60, check=True).stdout
            self.assertEqual(empty.strip(), '', name)
        compare = ['nvn/nvn_vk.cpp', 'nvn/nvn_debug.cpp', 'nvn/nvn_queue.cpp']
        if sdl and sys.platform == 'darwin':
            compare.append('platform_mac.cpp')
        patched = {n: preprocessed(compiler, includes + extra, src / n) for n in compare}
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        for n in compare:
            self.assertEqual(patched[n], preprocessed(compiler, includes + extra, src / n), n + ': default profile differs')
        print('PASS default profile: new TUs empty; ' + ', '.join(compare) + ' preprocess identically')

        # The Windows policy overlay still applies on top of this one.
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-perf-hud.patch')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
