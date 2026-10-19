"""CPU regression of the block-compressed zero fill (astral-nvn-bc-zero-fill.patch).

MoltenVK cannot vkCmdClearColorImage a BC image (VK_ERROR_FEATURE_NOT_PRESENT fails the whole submit), so the strict
profile zero-fills BC images with buffer copies. The overlay is applied after the native Astral overlay order on a
fresh copy of the pinned public runtime; the whole production nvn_upload.cpp is compiled with synthetic Vulkan and
upload adapters that record what it asks for. The changed TUs get syntax checks in both profiles, and the default
profile's preprocessed source must be identical to the unpatched one. No game, GPU or device is used.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime
from test_nvn_window_depth import NATIVE_ORDER, OVERLAY as WINDOW_DEPTH, preprocessed

ORDER = (*NATIVE_ORDER, WINDOW_DEPTH)
OVERLAY = 'astral-nvn-bc-zero-fill.patch'
CHANGED = ('nvn_upload.cpp', 'nvn_pipeline.cpp')

FIXTURE = r'''
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <iostream>
#include <string>
#include "nvn/nvn_upload.cpp"
namespace nx {
int magenta_logs = 0;
void log(const char* f, ...) {if(std::string(f).find("magenta")!=std::string::npos)magenta_logs++;}
namespace plat {uint64_t monotonic_ns() {return 0;}}
namespace vk {
struct Copy {VkBuffer buffer; VkImage image; VkImageLayout layout; std::vector<VkBufferImageCopy> regions;};
std::vector<Copy> copies;
int colour_clears = 0, depth_clears = 0;
void VKAPI_CALL copy(VkCommandBuffer, VkBuffer b, VkImage i, VkImageLayout l, uint32_t n, const VkBufferImageCopy* r) {
 copies.push_back({b,i,l,std::vector<VkBufferImageCopy>(r,r+n)});
}
void VKAPI_CALL colour(VkCommandBuffer, VkImage, VkImageLayout, const VkClearColorValue*, uint32_t, const VkImageSubresourceRange*) {colour_clears++;}
void VKAPI_CALL depth(VkCommandBuffer, VkImage, VkImageLayout, const VkClearDepthStencilValue*, uint32_t, const VkImageSubresourceRange*) {depth_clears++;}
PFN_vkCmdCopyBufferToImage p_vkCmdCopyBufferToImage = copy;
PFN_vkCmdClearColorImage p_vkCmdClearColorImage = colour;
PFN_vkCmdClearDepthStencilImage p_vkCmdClearDepthStencilImage = depth;
}
namespace nvn {
VkBuffer const RING = reinterpret_cast<VkBuffer>(uintptr_t(0x1000)), STAGING = reinterpret_cast<VkBuffer>(uintptr_t(0x2000));
std::vector<uint8_t> ring(8u<<20), staging_mem;
uint64_t ring_at = 48, ring_size = 0, ring_used = 0;  // 0: synchronous submits, as frame_ring_size() reports them
int staging_calls = 0;
Upload upload_alloc(uint64_t size, uint64_t) {assert(ring_at+size<=ring.size());Upload u{RING,ring_at,ring.data()+ring_at};ring_at+=(size+15)&~15ull;return u;}
Upload upload(const void* p, uint64_t size, uint64_t a) {Upload u=upload_alloc(size,a);std::memcpy(u.ptr,p,size);return u;}
Upload staging_alloc(uint64_t size) {staging_calls++;staging_mem.assign(size,0xab);return {STAGING,0,staging_mem.data()};}
uint64_t frame_ring_size() {return ring_size;}
uint64_t frame_upload_used() {return ring_used;}
void transition(VkCommandBuffer, GpuImage& img, VkImageLayout to) {img.layout=to;}
bool gpu_profile_on() {return false;}
void gpu_profile_mark(VkCommandBuffer, const std::string&) {}
void note_astc_decoded(uint64_t) {}
bool astc_decoded(uint32_t) {return false;}
uint64_t astc_decode_image(const uint8_t*,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,bool,uint8_t*) {return 0;}
bool bc_host_decode(uint32_t) {return false;}
uint32_t bc_decoded_bytes(uint32_t) {return 4;}
void bc_decode(uint32_t,const uint8_t*,uint32_t,uint32_t,uint32_t,uint8_t*) {}
void format_block(uint32_t,uint32_t& w,uint32_t& h,uint32_t& b) {w=h=1;b=4;}
uint32_t vk_block_bytes(VkFormat) {return 0;}
std::vector<LinearLevel> deswizzle_texture(const uint8_t*,uint64_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,std::vector<uint8_t>&,uint32_t) {return {};}
}
}
using namespace nx;
using namespace nx::nvn;
using nx::vk::copies;
GpuImage image(VkFormat f,uint32_t w,uint32_t h,uint32_t levels,uint32_t layers=1,uint32_t depth=1) {
 GpuImage i;i.image=reinterpret_cast<VkImage>(uintptr_t(0x77));i.format=f;i.width=w;i.height=h;i.levels=levels;i.layers=layers;i.depth=depth;
 i.view_type=depth>1?VK_IMAGE_VIEW_TYPE_3D:layers>1?VK_IMAGE_VIEW_TYPE_2D_ARRAY:VK_IMAGE_VIEW_TYPE_2D;return i;
}
VkImageSubresourceRange all(const GpuImage& i) {return {i.aspect,0,i.levels,0,i.layers};}
struct Want {uint64_t offset;uint32_t level,w,h,d;};
void check(const std::vector<VkBufferImageCopy>& got,const std::vector<Want>& want,uint64_t base,uint32_t layer0,uint32_t layers) {
 assert(got.size()==want.size());
 for(size_t k=0;k<want.size();k++) {
  const VkBufferImageCopy& c=got[k];
  assert(c.bufferOffset==base+want[k].offset&&c.bufferRowLength==0&&c.bufferImageHeight==0);
  assert(c.imageSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT&&c.imageSubresource.mipLevel==want[k].level);
  assert(c.imageSubresource.baseArrayLayer==layer0&&c.imageSubresource.layerCount==layers);
  assert(c.imageOffset.x==0&&c.imageOffset.y==0&&c.imageOffset.z==0);
  assert(c.imageExtent.width==want[k].w&&c.imageExtent.height==want[k].h&&c.imageExtent.depth==want[k].d);
  assert(c.bufferOffset%8==0);  // a multiple of the block size (8 or 16; ring allocations are 16-aligned)
 }
}
int main(int argc,char** argv) {
 const std::string mode=argc>1?argv[1]:"";
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
 auto plan=[](const GpuImage& i,VkImageSubresourceRange r,uint64_t& total) {return bc_zero_fill_regions(i,r,total);};
 if(mode=="regions") {
  uint64_t total=0;
  // 2D, full mip chain: BC1 8-byte blocks, BC7 16-byte; levels below 4x4 are one block.
  GpuImage a=image(VK_FORMAT_BC1_RGBA_UNORM_BLOCK,64,64,7);
  check(plan(a,all(a),total),{{0,0,64,64,1},{2048,1,32,32,1},{2560,2,16,16,1},{2688,3,8,8,1},{2720,4,4,4,1},{2728,5,2,2,1},{2736,6,1,1,1}},0,0,1);
  assert(total==2744);
  GpuImage b=image(VK_FORMAT_BC7_SRGB_BLOCK,64,64,7);
  check(plan(b,all(b),total),{{0,0,64,64,1},{4096,1,32,32,1},{5120,2,16,16,1},{5376,3,8,8,1},{5440,4,4,4,1},{5456,5,2,2,1},{5472,6,1,1,1}},0,0,1);
  assert(total==5488);
  // An array (a cube's 6 faces): every level covers every layer, its size times the layer count.
  GpuImage c=image(VK_FORMAT_BC3_UNORM_BLOCK,32,16,3,6);
  check(plan(c,all(c),total),{{0,0,32,16,1},{3072,1,16,8,1},{3840,2,8,4,1}},0,0,6);
  assert(total==4032);
  // 3D: one layer, depth halved per level (and counted in the size).
  GpuImage d=image(VK_FORMAT_BC4_UNORM_BLOCK,16,16,3,1,8);
  check(plan(d,all(d),total),{{0,0,16,16,8},{1024,1,8,8,4},{1152,2,4,4,2}},0,0,1);
  assert(total==1168);
  GpuImage d1=image(VK_FORMAT_BC6H_UFLOAT_BLOCK,8,8,4,1,2);
  check(plan(d1,all(d1),total),{{0,0,8,8,2},{128,1,4,4,1},{144,2,2,2,1},{160,3,1,1,1}},0,0,1);
  assert(total==176);
  // Odd sizes: partial blocks round up; the extent is the level's own (the subresource edge).
  GpuImage e=image(VK_FORMAT_BC7_UNORM_BLOCK,13,5,4);
  check(plan(e,all(e),total),{{0,0,13,5,1},{128,1,6,2,1},{160,2,3,1,1},{176,3,1,1,1}},0,0,1);
  assert(total==192);
  // A sub-range: levels clamp to the image's, layers as asked.
  GpuImage f=image(VK_FORMAT_BC5_SNORM_BLOCK,16,16,3,4);
  check(plan(f,{VK_IMAGE_ASPECT_COLOR_BIT,1,10,2,2},total),{{0,1,8,8,1},{128,2,4,4,1}},0,2,2);
  assert(total==160);
  check(plan(f,{VK_IMAGE_ASPECT_COLOR_BIT,3,1,0,4},total),{},0,0,4);
  assert(total==0);
  // Not BC: nothing, and no fill.
  for(VkFormat n:{VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_ASTC_4x4_UNORM_BLOCK,VK_FORMAT_ETC2_R8G8B8A8_UNORM_BLOCK,VK_FORMAT_D32_SFLOAT}) {
   GpuImage g=image(n,64,64,7);assert(plan(g,all(g),total).empty()&&total==0);
   assert(!zero_fill_compressed(nullptr,g,all(g))&&copies.empty());
  }
  std::cout<<"PASS strict regions: 2D/array/3D/odd/sub-range sizes, offsets and extents; BC1 8 vs BC7 16 bytes; non-BC none\n";
 } else if(mode=="clear") {
  // clear_image of a BC image: zero-filled copies from the ring, no colour clear; magenta logged once.
  std::fill(ring.begin(),ring.end(),0xab);
  GpuImage a=image(VK_FORMAT_BC1_RGBA_UNORM_BLOCK,64,64,7);
  clear_image(nullptr,a,false);
  assert(nx::vk::colour_clears==0&&copies.size()==1&&a.layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  assert(copies[0].buffer==RING&&copies[0].image==a.image&&copies[0].layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  check(copies[0].regions,{{0,0,64,64,1},{2048,1,32,32,1},{2560,2,16,16,1},{2688,3,8,8,1},{2720,4,4,4,1},{2728,5,2,2,1},{2736,6,1,1,1}},48,0,1);
  for(uint64_t k=48;k<48+2744;k++) assert(ring[k]==0);
  assert(ring[48+2744]==0xab&&magenta_logs==0);
  GpuImage b=image(VK_FORMAT_BC7_UNORM_BLOCK,8,8,1,1,4);
  clear_image(nullptr,b,true);clear_image(nullptr,b,true);
  assert(magenta_logs==1&&nx::vk::colour_clears==0&&copies.size()==3);
  check(copies[1].regions,{{0,0,8,8,4}},48+2752,0,1);  // after the 2744 bytes, 16-aligned
  // Other formats and aspects clear as before.
  GpuImage c=image(VK_FORMAT_R8G8B8A8_UNORM,64,64,7);clear_image(nullptr,c,true);
  assert(nx::vk::colour_clears==1&&copies.size()==3);
  GpuImage d=image(VK_FORMAT_D32_SFLOAT,64,64,1);d.aspect=VK_IMAGE_ASPECT_DEPTH_BIT;clear_image(nullptr,d,false);
  assert(nx::vk::depth_clears==1&&copies.size()==3&&staging_calls==0);
  std::cout<<"PASS strict clear_image: BC zero-filled from zeroed ring bytes, magenta skip logged once; others cleared\n";
 } else if(mode=="staging") {
  // 4 MB of BC7: synchronous submits (no ring) give it a staging buffer of its own, as a big upload gets.
  GpuImage a=image(VK_FORMAT_BC7_UNORM_BLOCK,2048,2048,1);
  assert(zero_fill_compressed(nullptr,a,all(a)));
  assert(staging_calls==1&&copies.back().buffer==STAGING&&staging_mem.size()==(4u<<20));
  for(uint8_t v:staging_mem) assert(v==0);
  check(copies.back().regions,{{0,0,2048,2048,1}},0,0,1);
  // A 1 GB ring with room takes it, as it takes a steady-state upload; past a quarter of it used, staging again.
  ring_size=1ull<<30;uint64_t at=ring_at;
  assert(zero_fill_compressed(nullptr,a,all(a))&&staging_calls==1&&copies.back().buffer==RING);
  check(copies.back().regions,{{0,0,2048,2048,1}},at,0,1);
  ring_used=ring_size/4;assert(zero_fill_compressed(nullptr,a,all(a))&&staging_calls==2&&copies.back().buffer==STAGING);
  // NX_STAGING_RING=1 keeps big uploads in the ring (bisecting); so it does fills. Small fills never stage.
  ring_at=48;setenv("NX_STAGING_RING","1",1);assert(zero_fill_compressed(nullptr,a,all(a))&&staging_calls==2);
  unsetenv("NX_STAGING_RING");ring_at=48;
  GpuImage s=image(VK_FORMAT_BC1_RGB_UNORM_BLOCK,256,256,9);ring_size=0;
  assert(zero_fill_compressed(nullptr,s,all(s))&&staging_calls==2&&copies.back().buffer==RING);
  std::cout<<"PASS strict staging: a 1 MB+ fill stages on the upload terms (no ring, quarter used), else the ring\n";
 } else return 2;
#else
 // The default profile (and the strict stack before the overlay): BC images go through vkCmdClearColorImage.
 GpuImage a=image(VK_FORMAT_BC1_RGBA_UNORM_BLOCK,64,64,7);clear_image(nullptr,a,true);
 assert(nx::vk::colour_clears==1&&copies.empty()&&magenta_logs==0);
 std::cout<<"PASS "<<(mode.empty()?"default":mode)<<" profile: a BC image is cleared with vkCmdClearColorImage\n";
#endif
 return 0;
}
'''


class NvnBcZeroFillTests(unittest.TestCase):
    def test_overlay_order_and_production_profiles(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        repo = common.parent
        reference = Path(os.environ.get('NVN_REFERENCE', str(repo /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', str(repo /
            '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include')))
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required; no downloads')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out = ROOT / '.local/nvn-bc-zero-fill-124' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        source = out / 'source'
        stacked = runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in ORDER])
        nvn = source / 'runtime/src/nvn'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), '-I', str(vulkan)]

        def run(name, flags, modes):
            fixture = out / (name + '.cpp')
            fixture.write_text(FIXTURE)
            binary = out / name
            build = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, str(fixture), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            for mode in modes:
                env = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
                result = subprocess.run([str(binary), *([mode] if mode else [])], cwd=out, capture_output=True,
                                        text=True, timeout=30, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS', result.stdout)
                print(result.stdout, end='')

        # The actual before: the strict stack clears BC images with vkCmdClearColorImage.
        run('before', ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1'], ['before-strict'])
        patch = ROOT / 'runtime/patches' / OVERLAY
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(applied.keys(), stacked.keys())
        self.assertEqual(sorted(k for k in applied if applied[k] != stacked[k]),
                         ['runtime/src/nvn/nvn_pipeline.cpp', 'runtime/src/nvn/nvn_pipeline.h',
                          'runtime/src/nvn/nvn_upload.cpp'])
        text = patch.read_text()
        self.assertNotRegex(text, r'/(?:Users|home)/')
        added = [l[1:] for l in text.splitlines() if l.startswith('+') and not l.startswith('+++')]
        self.assertEqual(sum(l.startswith('#if defined(NX_ASTRAL_STRICT)') for l in added),
                         sum(l.startswith('#endif') for l in added))

        # ensure_contents' "never written: black" clear: BC images are zero-filled, the colour clear stays for others.
        pipeline = (nvn / 'nvn_pipeline.cpp').read_text()
        never = pipeline.split('// never written: black, not garbage')[1].split('return img;')[0]
        self.assertRegex(never, r'#if defined\(NX_ASTRAL_STRICT\)\n\s+if \(!zero_fill_compressed\(cb, \*img, r\)\)[^\n]*\n'
                                r'#endif\n\s+p_vkCmdClearColorImage\(')

        run('strict', ['-DNX_ASTRAL_STRICT=1'], ['regions', 'clear', 'staging'])
        run('default', [], [''])

        for flags in (['-DNX_ASTRAL_STRICT=1'], []):
            for name in CHANGED:
                check = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, '-fsyntax-only',
                                        str(nvn / name)], capture_output=True, text=True, timeout=60)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

        # Default profile: preprocessed patched TUs equal the unpatched ones (headers included).
        patched = {n: preprocessed(compiler, includes, nvn / n) for n in CHANGED}
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        for n in CHANGED:
            original = preprocessed(compiler, includes, nvn / n)
            diff = next((i for i, (a, b) in enumerate(zip(patched[n], original)) if a != b), None)
            self.assertTrue(diff is None and len(patched[n]) == len(original),
                            f'{n}: default profile differs at preprocessed line {diff}')
        print('PASS full changed TUs: strict/default syntax; default profile preprocesses identically')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
