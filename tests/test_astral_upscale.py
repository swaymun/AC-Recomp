"""CPU regression of the upscaling overlay (astral-upscale.patch, docs/ASTRAL_UPSCALE.md).

The overlay is applied last, after astral-touch.patch, on a fresh copy of the pinned public runtime. The present
pass's FSR 1 shaders (EASU, RCAS) and its vertex shader are validated with spirv-val; the production
nvn/nvn_present.cpp is compiled with fake Vulkan functions and the passes it records are checked for NX_UPSCALE=fsr,
=metalfx (an alias for fsr; the launcher offers only Bilinear and FSR 1), =bilinear (over NX_FSR=1), unset (the
upstream behaviour: the blit unless NX_FSR=1), letterboxed and not-upscaled targets, the crop and the sharpness; the launcher's Upscaling setting round-trips through
settings.ini and is exported as NX_UPSCALE unless the environment sets it. The changed translation units get strict
syntax checks in the Mac profile, and the default profile's preprocessed source must be unchanged. No game, GPU,
window or device is used.
"""
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime  # noqa: E402
import test_astral_touch as touch  # noqa: E402
from test_astral_launcher import sdl_lib  # noqa: E402
from test_astral_perf_hud import sdl_include, vulkan_include  # noqa: E402
from test_nvn_window_depth import preprocessed  # noqa: E402
import test_astral_shared_font as font  # noqa: E402

# The native macOS overlay order (runtime/patches/series.macos): the touch overlay's, then this overlay last.
OVERLAY = 'astral-upscale.patch'
ORDER = (*touch.ORDER, OVERLAY)
NEW = ['runtime/src/nvn/nvn_upscale.h']
MODIFIED = ['runtime/src/hle_vi.cpp', 'runtime/src/input_map.cpp', 'runtime/src/input_map.h', 'runtime/src/launcher.cpp',
            'runtime/src/nvn/nvn_present.cpp']

PRESENT_FIXTURE = r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "nvn/nvn_vk.h"
#include "platform.h"
namespace nx {
void log(const char* f, ...) { std::printf("log: %s\n", f); }
namespace plat { size_t touch_overlay(OverlayShape*, size_t) { return 0; } }
}  // namespace nx
#include "nvn/nvn_present.cpp"

// ---- fake Vulkan ----
uintptr_t next_handle = 0x1000;
template <class T> T fresh() { return reinterpret_cast<T>(++next_handle); }
std::map<VkShaderModule, const uint32_t*> module_code;
std::map<VkPipeline, const uint32_t*> pipeline_code;
std::map<VkRenderPass, VkFormat> pass_format;
std::map<VkFramebuffer, std::pair<uint32_t, uint32_t>> fb_size;
std::vector<VkImageCreateInfo> images;
struct Call { std::string what; uint64_t a = 0; std::vector<float> f; };
std::vector<Call> calls;
using namespace nx::vk;
#define H(T) reinterpret_cast<uint64_t>(T)
VKAPI_ATTR VkResult VKAPI_CALL f_alloc(VkDevice, const VkMemoryAllocateInfo*, const VkAllocationCallbacks*, VkDeviceMemory* m) { *m = fresh<VkDeviceMemory>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_bind(VkDevice, VkImage, VkDeviceMemory, VkDeviceSize) { return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL f_begin(VkCommandBuffer, const VkRenderPassBeginInfo* b, VkSubpassContents) {
    calls.push_back({"begin", H(b->renderPass), {float(b->renderArea.extent.width), float(b->renderArea.extent.height)}});
    assert(fb_size.count(b->framebuffer));
    assert(fb_size[b->framebuffer] == std::make_pair(b->renderArea.extent.width, b->renderArea.extent.height));
}
VKAPI_ATTR void VKAPI_CALL f_sets(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, uint32_t, uint32_t n, const VkDescriptorSet*, uint32_t, const uint32_t*) { assert(n == 1); }
VKAPI_ATTR void VKAPI_CALL f_pipe(VkCommandBuffer, VkPipelineBindPoint, VkPipeline p) { calls.push_back({"pipeline", H(p)}); }
VKAPI_ATTR void VKAPI_CALL f_draw(VkCommandBuffer, uint32_t v, uint32_t i, uint32_t, uint32_t) { assert(v == 3 && i == 1); calls.push_back({"draw"}); }
VKAPI_ATTR void VKAPI_CALL f_end(VkCommandBuffer) { calls.push_back({"end"}); }
VKAPI_ATTR void VKAPI_CALL f_push(VkCommandBuffer, VkPipelineLayout, VkShaderStageFlags s, uint32_t o, uint32_t n, const void* d) {
    assert(s == VK_SHADER_STAGE_FRAGMENT_BIT && o == 0 && n == 64);
    const float* f = static_cast<const float*>(d);
    calls.push_back({"push", 0, std::vector<float>(f, f + 16)});
}
VKAPI_ATTR void VKAPI_CALL f_scissor(VkCommandBuffer, uint32_t, uint32_t, const VkRect2D*) {}
VKAPI_ATTR void VKAPI_CALL f_viewport(VkCommandBuffer, uint32_t, uint32_t, const VkViewport* v) { calls.push_back({"viewport", 0, {v->width, v->height}}); }
VKAPI_ATTR VkResult VKAPI_CALL f_dsl(VkDevice, const VkDescriptorSetLayoutCreateInfo*, const VkAllocationCallbacks*, VkDescriptorSetLayout* o) { *o = fresh<VkDescriptorSetLayout>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_fb(VkDevice, const VkFramebufferCreateInfo* c, const VkAllocationCallbacks*, VkFramebuffer* o) { *o = fresh<VkFramebuffer>(); fb_size[*o] = {c->width, c->height}; return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_gp(VkDevice, VkPipelineCache, uint32_t n, const VkGraphicsPipelineCreateInfo* c, const VkAllocationCallbacks*, VkPipeline* o) {
    assert(n == 1 && c->stageCount == 2 && c->pStages[1].stage == VK_SHADER_STAGE_FRAGMENT_BIT);
    *o = fresh<VkPipeline>();
    pipeline_code[*o] = module_code[c->pStages[1].module];
    return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL f_image(VkDevice, const VkImageCreateInfo* c, const VkAllocationCallbacks*, VkImage* o) { images.push_back(*c); *o = fresh<VkImage>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_view(VkDevice, const VkImageViewCreateInfo*, const VkAllocationCallbacks*, VkImageView* o) { *o = fresh<VkImageView>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_pl(VkDevice, const VkPipelineLayoutCreateInfo*, const VkAllocationCallbacks*, VkPipelineLayout* o) { *o = fresh<VkPipelineLayout>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_rp(VkDevice, const VkRenderPassCreateInfo* c, const VkAllocationCallbacks*, VkRenderPass* o) { *o = fresh<VkRenderPass>(); pass_format[*o] = c->pAttachments[0].format; return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_sampler(VkDevice, const VkSamplerCreateInfo*, const VkAllocationCallbacks*, VkSampler* o) { *o = fresh<VkSampler>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL f_sm(VkDevice, const VkShaderModuleCreateInfo* c, const VkAllocationCallbacks*, VkShaderModule* o) { *o = fresh<VkShaderModule>(); module_code[*o] = c->pCode; return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL f_dfb(VkDevice, VkFramebuffer, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_dimg(VkDevice, VkImage, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_dview(VkDevice, VkImageView, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_dpipe(VkDevice, VkPipeline, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_drp(VkDevice, VkRenderPass, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_dsm(VkDevice, VkShaderModule, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_free(VkDevice, VkDeviceMemory, const VkAllocationCallbacks*) {}
VKAPI_ATTR void VKAPI_CALL f_req(VkDevice, VkImage, VkMemoryRequirements* r) { r->size = 1 << 20; r->memoryTypeBits = 1; }
VKAPI_ATTR void VKAPI_CALL f_upd(VkDevice, uint32_t, const VkWriteDescriptorSet*, uint32_t, const VkCopyDescriptorSet*) {}
namespace nx::vk {
PFN_vkAllocateMemory p_vkAllocateMemory = f_alloc;
PFN_vkBindImageMemory p_vkBindImageMemory = f_bind;
PFN_vkCmdBeginRenderPass p_vkCmdBeginRenderPass = f_begin;
PFN_vkCmdBindDescriptorSets p_vkCmdBindDescriptorSets = f_sets;
PFN_vkCmdBindPipeline p_vkCmdBindPipeline = f_pipe;
PFN_vkCmdDraw p_vkCmdDraw = f_draw;
PFN_vkCmdEndRenderPass p_vkCmdEndRenderPass = f_end;
PFN_vkCmdPushConstants p_vkCmdPushConstants = f_push;
PFN_vkCmdSetScissor p_vkCmdSetScissor = f_scissor;
PFN_vkCmdSetViewport p_vkCmdSetViewport = f_viewport;
PFN_vkCreateDescriptorSetLayout p_vkCreateDescriptorSetLayout = f_dsl;
PFN_vkCreateFramebuffer p_vkCreateFramebuffer = f_fb;
PFN_vkCreateGraphicsPipelines p_vkCreateGraphicsPipelines = f_gp;
PFN_vkCreateImage p_vkCreateImage = f_image;
PFN_vkCreateImageView p_vkCreateImageView = f_view;
PFN_vkCreatePipelineLayout p_vkCreatePipelineLayout = f_pl;
PFN_vkCreateRenderPass p_vkCreateRenderPass = f_rp;
PFN_vkCreateSampler p_vkCreateSampler = f_sampler;
PFN_vkCreateShaderModule p_vkCreateShaderModule = f_sm;
PFN_vkDestroyFramebuffer p_vkDestroyFramebuffer = f_dfb;
PFN_vkDestroyImage p_vkDestroyImage = f_dimg;
PFN_vkDestroyImageView p_vkDestroyImageView = f_dview;
PFN_vkDestroyPipeline p_vkDestroyPipeline = f_dpipe;
PFN_vkDestroyRenderPass p_vkDestroyRenderPass = f_drp;
PFN_vkDestroyShaderModule p_vkDestroyShaderModule = f_dsm;
PFN_vkFreeMemory p_vkFreeMemory = f_free;
PFN_vkGetImageMemoryRequirements p_vkGetImageMemoryRequirements = f_req;
PFN_vkUpdateDescriptorSets p_vkUpdateDescriptorSets = f_upd;
}  // namespace nx::vk
std::vector<uint8_t> ring(1 << 20);
namespace nx::nvn {
VkDevice vk_device() { return reinterpret_cast<VkDevice>(uintptr_t(0xd0d0)); }
uint32_t memory_type(uint32_t, VkMemoryPropertyFlags) { return 0; }
std::vector<VkImageLayout> transitions;
void transition(VkCommandBuffer, GpuImage& img, VkImageLayout to) { transitions.push_back(to); img.layout = to; }
Upload upload_alloc(uint64_t size, uint64_t) { return {reinterpret_cast<VkBuffer>(uintptr_t(0xb0f)), 256, ring.data() + 256}; }
VkDescriptorSet descriptor_set(VkDescriptorSetLayout) { return fresh<VkDescriptorSet>(); }
}  // namespace nx::nvn

using namespace nx::nvn;
const VkCommandBuffer cb = reinterpret_cast<VkCommandBuffer>(uintptr_t(0xcb));
GpuImage game() {
    GpuImage s;
    s.image = fresh<VkImage>(), s.view = fresh<VkImageView>(), s.format = VK_FORMAT_R8G8B8A8_UNORM;
    s.width = 1600, s.height = 900;
    s.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    return s;
}
std::vector<VkImage> swapchain() { return {fresh<VkImage>(), fresh<VkImage>(), fresh<VkImage>()}; }
bool near(float a, float b) { return std::fabs(a - b) < 1e-4f; }
const uint32_t* bound(size_t k) { return pipeline_code.at(reinterpret_cast<VkPipeline>(calls.at(k).a)); }

// EASU into the 16-bit intermediate at the picture's size, then RCAS into the swapchain image (the full target).
void expect_fsr(uint32_t tw, uint32_t th, uint32_t ow, uint32_t oh, const int32_t* crop, float sharp) {
    GpuImage src = game();
    calls.clear(), transitions.clear(), images.clear();
    assert(present_pass_targets(VK_FORMAT_B8G8R8A8_UNORM, swapchain(), {tw, th}, VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR));
    assert(present_pass_record(cb, src, crop, 1));
    assert(transitions.size() == 1 && transitions[0] == VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    const char* want[] = {"begin", "viewport", "pipeline", "push", "draw", "end", "begin", "viewport", "pipeline", "push", "draw", "end"};
    assert(calls.size() == 12);
    for (size_t k = 0; k < 12; k++) assert(calls[k].what == want[k]);
    assert(pass_format[reinterpret_cast<VkRenderPass>(calls[0].a)] == VK_FORMAT_R16G16B16A16_SFLOAT);
    assert(calls[0].f[0] == ow && calls[0].f[1] == oh && calls[1].f[0] == ow && calls[1].f[1] == oh);
    assert(bound(2) == kEasu && bound(8) == kRcas);
    assert(pass_format[reinterpret_cast<VkRenderPass>(calls[6].a)] == VK_FORMAT_B8G8R8A8_UNORM);
    assert(calls[6].f[0] == tw && calls[6].f[1] == th && calls[7].f[0] == tw && calls[7].f[1] == th);
    float cx = crop ? crop[0] : 0, cy = crop ? crop[1] : 0, cw = crop ? crop[2] : 1600, ch = crop ? crop[3] : 900;
    const std::vector<float>& e = calls[3].f;  // EASU: scale, offset, shown part
    assert(near(e[0], cw / ow) && near(e[1], ch / oh) && near(e[2], 0.5f * e[0] - 0.5f) && near(e[3], 0.5f * e[1] - 0.5f));
    assert(e[4] == cx && e[5] == cy && e[6] == cw && e[7] == ch);
    const std::vector<float>& r = calls[9].f;  // RCAS: rot, off, box (letterbox), {size, sharpness}
    assert(near(r[8], (1 - float(ow) / tw) / 2) && near(r[9], (1 - float(oh) / th) / 2));
    assert(near(r[10], float(ow) / tw) && near(r[11], float(oh) / th));
    assert(r[12] == ow && r[13] == oh && near(r[14], std::exp2(-sharp)));
    if (images.size()) assert(images.back().format == VK_FORMAT_R16G16B16A16_SFLOAT && images.back().extent.width == ow &&
                              images.back().extent.height == oh);
}

// The plain present pass (bilinear, letterboxed): one render pass with the main pipeline.
void expect_plain(uint32_t tw, uint32_t th) {
    GpuImage src = game();
    calls.clear();
    assert(present_pass_targets(VK_FORMAT_B8G8R8A8_UNORM, swapchain(), {tw, th}, VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR));
    assert(present_pass_record(cb, src, nullptr, 0));
    assert(calls.size() == 6 && calls[0].what == "begin" && calls[2].what == "pipeline" && bound(2) == kFragment);
}

int main(int argc, char** argv) {
    std::string mode = argv[1];
    float sharp = argc > 2 ? float(std::atof(argv[2])) : 0.2f;
    if (mode == "blit") {  // the pass is off: gpu_present blits, as before
        GpuImage src = game();
        assert(!present_pass_wanted() && !present_pass_targets(VK_FORMAT_B8G8R8A8_UNORM, swapchain(), {2560, 1440},
                                                               VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR));
        assert(!present_pass_record(cb, src, nullptr, 0) && calls.empty());
        std::printf("PASS blit: no present pass, nothing recorded\n");
        return 0;
    }
    assert(present_pass_wanted());
    expect_fsr(2560, 1440, 2560, 1440, nullptr, sharp);  // 1600x900 -> 1440p
    expect_fsr(2560, 1600, 2560, 1440, nullptr, sharp);  // 16:10: bars top and bottom
    expect_fsr(3456, 2234, 3456, 1944, nullptr, sharp);  // a 16" MacBook Pro's HiDPI drawable, fullscreen
    const int32_t crop[4] = {0, 0, 1280, 720};
    expect_fsr(1920, 1080, 1920, 1080, crop, sharp);  // nvnWindowSetCrop: the shown part only
    expect_plain(1600, 900);   // no upscale needed: the plain pass
    expect_plain(1280, 720);   // a smaller window: the plain pass (EASU never downscales)
    expect_fsr(2560, 1440, 2560, 1440, nullptr, sharp);  // and back: the intermediate is made again
    std::printf("PASS fsr (%s): EASU into RGBA16F at the picture size then RCAS (sharpness %.2f stops) into the "
                "swapchain; letterbox, HiDPI, crop, no upscale at or below the game's size, resize\n", mode.c_str(), sharp);
    return 0;
}
'''

SETTINGS_FIXTURE = r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
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
#include "nvn/nvn_upscale.h"
using namespace nx;
int main(int argc, char** argv) {
    std::string mode = argv[1];
    if (mode == "settings") {
        input::Settings d;
        assert(d.upscale == "bilinear" && input::setting_text(d, input::kSetUpscale) == "Bilinear");
        assert(input::write_settings(d).find("upscale = bilinear\n") != std::string::npos);
        for (int u = 0; u < input::kUpscaleCount; u++) {
            input::Settings s;
            s.upscale = input::kUpscales[u];
            assert(input::parse_settings(input::write_settings(s)) == s);
            assert(input::setting_text(s, input::kSetUpscale) == input::kUpscaleLabels[u]);
        }
        assert(input::parse_settings("upscale = FSR\n").upscale == "fsr");
        assert(input::parse_settings("upscale = lanczos\n").upscale == "bilinear");
        // MetalFX is not offered (not built): two choices everywhere; an older "metalfx" reads as FSR 1.
        assert(input::kUpscaleCount == 2 && std::string(input::kUpscaleLabels[0]) == "Bilinear" &&
               std::string(input::kUpscaleLabels[1]) == "FSR 1");
        for (int u = 0; u < input::kUpscaleCount; u++) assert(std::string(input::kUpscaleLabels[u]) != "MetalFX");
        assert(input::parse_settings("upscale = metalfx\n").upscale == "fsr");
        assert(input::parse_settings("upscale = MetalFX\n").upscale == "fsr");
        assert(input::env_effect(input::kSetUpscale, "metalfx") == "FSR 1");
        assert(std::string(input::setting_key(input::kSetUpscale)) == "upscale");
        assert(std::string(input::setting_env(input::kSetUpscale)) == "NX_UPSCALE");
        assert(input::env_effect(input::kSetUpscale, "FSR") == "FSR 1" && input::env_effect(input::kSetUpscale, "x") == "Bilinear");
        std::printf("PASS settings: upscale round-trips, labels, unknown values stay bilinear\n");
    } else if (mode == "export") {  // the default is not exported; FSR is unless the environment set NX_UPSCALE
        input::Settings s;
        const bool preset = std::getenv("NX_UPSCALE") != nullptr;
        input::export_env(s);
        assert(preset || !std::getenv("NX_UPSCALE"));
        s.upscale = "fsr";
        input::export_env(s);
        std::printf("NX_UPSCALE=%s\n", std::getenv("NX_UPSCALE"));
    } else {  // the runtime's reading of NX_UPSCALE / NX_UPSCALE_SHARPNESS (nvn_upscale.h)
        using namespace nx::nvn::upscale;
        assert(parse(nullptr) == Mode::Unset && parse("") == Mode::Unset && parse(" FSR ") == Mode::Fsr);
        assert(parse("bilinear") == Mode::Bilinear && parse("MetalFX") == Mode::MetalFx && parse("x") == Mode::Unknown);
        assert(fsr_wanted("fsr", nullptr) && fsr_wanted("metalfx", nullptr) && !fsr_wanted("bilinear", "1"));
        assert(!fsr_wanted("lanczos", "1") && fsr_wanted(nullptr, "1") && !fsr_wanted(nullptr, nullptr) && !fsr_wanted("", "0"));
        assert(sharpness(nullptr, nullptr) == 0.2f && sharpness("0.5", "1") == 0.5f && sharpness(nullptr, "1") == 1.0f);
        assert(sharpness("-3", nullptr) == 0.0f && sharpness("9", nullptr) == 2.0f && sharpness("x", nullptr) == 0.2f);
        std::printf("PASS env: NX_UPSCALE modes, NX_FSR fallback, sharpness default and clamp\n");
    }
    return 0;
}
'''


def spirv_words(text, name):
    body = text.split(f'const uint32_t {name}[] = {{', 1)[1].split('};', 1)[0]
    body = re.sub(r'//[^\n]*', '', body)
    return [int(w, 16) for w in re.findall(r'0x[0-9a-fA-F]+', body)]


class AstralUpscaleTests(unittest.TestCase):
    def test_overlay_fsr_present_pass_settings_and_default_profile(self):
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

        # The FSR 1 shaders and the vertex shader: valid Vulkan 1.0 SPIR-V; the MIT notice is shipped.
        spirv_val = shutil.which('spirv-val')
        if spirv_val:
            inc = (src / 'nvn/nvn_fsr_spirv.inc').read_text()
            present = (src / 'nvn/nvn_present.cpp').read_text()
            for name, text in (('kEasu', inc), ('kRcas', inc), ('kVertex', present), ('kFragment', present)):
                words = spirv_words(text, name)
                self.assertEqual(words[0], 0x07230203, name)
                blob = out / f'{name}.spv'
                blob.write_bytes(struct.pack(f'<{len(words)}I', *words))
                val = subprocess.run([spirv_val, '--target-env', 'vulkan1.0', str(blob)], capture_output=True, text=True)
                self.assertEqual(val.returncode, 0, name + ': ' + val.stdout + val.stderr)
            print('PASS spirv-val (vulkan1.0): EASU, RCAS, present vertex and fragment shaders')
        notice = (ROOT / 'runtime/patches/astral-upscale.NOTICE').read_text()
        self.assertIn('Advanced Micro Devices', notice)
        self.assertIn('MIT', notice)
        self.assertIn('FidelityFX', (ROOT / 'THIRD_PARTY_NOTICES.md').read_text())

        # The present pass with fake Vulkan, one process per environment (the switches are read once).
        clean = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
        work = out / 'present'
        work.mkdir()
        (work / 'fixture.cpp').write_text(PRESENT_FIXTURE)
        build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wno-unused-parameter', '-Wno-missing-field-initializers',
                                '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1', *includes,
                                str(work / 'fixture.cpp'), '-o', str(work / 'run')],
                               capture_output=True, text=True, timeout=180)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        def run(exe, *args, env=None):
            r = subprocess.run([str(exe), *args], cwd=exe.parent, capture_output=True, text=True, timeout=60,
                               env={**clean, **(env or {})})
            self.assertEqual(r.returncode, 0, ' '.join(args) + str(env) + ': ' + r.stdout + r.stderr)
            print(''.join(l + '\n' for l in r.stdout.splitlines() if l.startswith('PASS')), end='')
            return r.stdout

        present = work / 'run'
        run(present, 'blit')  # unset: as before (the Mac blits)
        run(present, 'blit', env={'NX_UPSCALE': 'bilinear', 'NX_FSR': '1'})  # the setting wins over NX_FSR
        run(present, 'blit', env={'NX_UPSCALE': 'lanczos'})
        run(present, 'fsr', env={'NX_UPSCALE': 'fsr'})
        run(present, 'fsr', '0.5', env={'NX_UPSCALE': 'FSR', 'NX_UPSCALE_SHARPNESS': '0.5', 'NX_FSR_SHARP': '1'})
        run(present, 'fsr', '1.0', env={'NX_FSR': '1', 'NX_FSR_SHARP': '1.0'})  # the upstream switches still work
        self.assertIn('an alias for fsr: FSR 1', run(present, 'fsr', env={'NX_UPSCALE': 'metalfx'}))

        # The launcher's setting and the runtime's reading of the variables.
        sdl = sdl_include()
        lib = sdl_lib(sdl) if sdl else None
        if sdl and lib:
            work = out / 'settings'
            work.mkdir()
            (work / 'fixture.cpp').write_text(SETTINGS_FIXTURE)
            build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wno-unused-parameter', '-DNX_ASTRAL_STRICT=1',
                                    *includes, '-I', sdl, str(work / 'fixture.cpp'), '-L', lib, '-lSDL3',
                                    '-Wl,-rpath,' + lib, '-o', str(work / 'run')], capture_output=True, text=True,
                                   timeout=180)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run(work / 'run', 'settings')
            run(work / 'run', 'env')
            self.assertIn('NX_UPSCALE=fsr', run(work / 'run', 'export'))
            self.assertIn('NX_UPSCALE=bilinear', run(work / 'run', 'export', env={'NX_UPSCALE': 'bilinear'}))
            print('PASS export: NX_UPSCALE from settings.ini unless the environment set it')
        launcher = (src / 'launcher.cpp').read_text()
        self.assertIn('"Mute audio", "Upscaling"};', launcher)
        self.assertIn('case input::kSetUpscale: {', launcher)

        # Dumps keep the game's image: gpu_present dumps `src`, never the swapchain or the intermediate.
        vk = (src / 'nvn/nvn_vk.cpp').read_text().split('void gpu_present(uint64_t texture, const int32_t* crop) {')[1]
        self.assertIn('dump = dump && frame_dump_record(g_cb, *src);', vk)
        self.assertIn('if (dump) frame_dump_write(*src, presents);', vk)

        # VI: Astral calls SetLayerScalingMode(FitToLayer) once at boot and stops on an error. With the present pass on
        # (NX_UPSCALE=fsr) FitToLayer now succeeds, the picture keeping its aspect; other modes still fail.
        vi = (src / 'hle_vi.cpp').read_text().split('void SetLayerScalingMode(CPU& c) {')[1].split('\n}\n')[0]
        strict = vi.split('#if defined(NX_ASTRAL_STRICT)')[1].split('#else')[0]
        self.assertIn('if (mode != 2) {', strict)
        self.assertNotIn('present_pass_wanted()) {', strict)
        self.assertIn('vi: FitToLayer uses the host present pass (aspect kept)', strict)

        # Strict syntax (Mac profile) and default syntax of the changed TUs.
        extra = ['-I', sdl] if sdl else []
        tus = ['nvn/nvn_present.cpp', 'hle_vi.cpp'] + (['input_map.cpp', 'launcher.cpp'] if sdl else [])
        for flags in (['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1'], []):
            for name in tus:
                check = subprocess.run([compiler, '-std=c++20', *flags, *includes, *extra, '-fsyntax-only',
                                        str(src / name)], capture_output=True, text=True, timeout=120)
                self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        print('PASS strict (Mac profile) and default syntax: ' + ', '.join(tus))

        # Default profile: the new header is empty, and nvn_present.cpp preprocesses exactly as before the overlay
        # (input_map.cpp and launcher.cpp are Astral-only translation units).
        empty = subprocess.run([compiler, '-std=c++20', '-E', '-P', '-x', 'c++', *includes, str(src / 'nvn/nvn_upscale.h')],
                               capture_output=True, text=True, timeout=60, check=True).stdout
        self.assertEqual(empty.strip(), '')
        compare = ('nvn/nvn_present.cpp', 'hle_vi.cpp')
        after = {n: preprocessed(compiler, includes, src / n) for n in compare}
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        for n in compare:
            self.assertEqual(after[n], preprocessed(compiler, includes, src / n), n + ': default profile differs')
        print('PASS default profile: nvn_upscale.h empty; nvn_present.cpp, hle_vi.cpp preprocess identically')

        # The Windows policy overlay still applies on top of this one.
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(ROOT / 'runtime/patches/windows-native.patch')],
                       check=True, capture_output=True)
        print('PASS windows-native.patch applies after astral-upscale.patch')


if __name__ == '__main__':
    unittest.main()
