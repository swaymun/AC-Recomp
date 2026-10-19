"""CPU regression of the cube-map storage size (astral-nvn-cube-storage.patch).

A cube map (NVN target 8) built with depth 1 was given one face's storage size, while its image has 6 layers, so
deswizzle_texture refused it ("could not untile") and the texture was never uploaded. The overlay is applied after
the native Astral overlays, astral-nvn-window-depth.patch and astral-nvn-bc-zero-fill.patch on a fresh copy of the
pinned public runtime. The production nvn_texture_layout.cpp and nvn_tiling.cpp are compiled with a synthetic format
table; a reference block-linear tiler written here tiles synthetic data that must untile back exactly. The default
profile's preprocessed source must be identical to the unpatched one. No game, GPU or device is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime
from test_nvn_window_depth import NATIVE_ORDER, OVERLAY as WINDOW_DEPTH, preprocessed

ORDER = (*NATIVE_ORDER, WINDOW_DEPTH, 'astral-nvn-bc-zero-fill.patch')
OVERLAY = 'astral-nvn-cube-storage.patch'

FIXTURE = r'''
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include "nvn/nvn.h"
#include "nvn/nvn_tiling.h"
namespace nx {
std::vector<uint8_t> memory;
LoadedModule module{};
std::map<std::string,HleFn> hooks;
HleRegistrar::HleRegistrar(const char* n,HleFn f) {hooks[n]=f;}
[[noreturn]] void fatal(const char* f, ...) {throw std::runtime_error(f);}
uint64_t find_symbol(const char*) {return 1;}
const LoadedModule* module_at(uint64_t) {return &module;}
VmInfo vm_query(uint64_t a) {return {a,1,kMemStatic,1u};}
namespace nvn {
std::map<std::string,uint64_t> values;
std::string getter;
uint64_t real_proc(CPU&,const char* name) {getter=name;return 1;}
uint64_t guest_call(CPU&,uint64_t,std::initializer_list<uint64_t>) {return values.at(getter);}
}
}
#include "nvn/nvn_texture_layout.cpp"
using namespace nx;
using namespace nx::nvn;
// Synthetic format records (flags, block width, block height, bytes): 1 a 4x4 16-byte BC6H-like format, 2 an
// 8-byte texel RGBA16F-like one, 3 a 4x4 8-byte BC1-like one. Indices and layout are made up.
void formats() {
 const uint8_t rec[3][4]={{1,4,4,16},{1,1,1,8},{1,4,4,8}};
#if !defined(NX_ASTRAL_STRICT)  // the default profile reads the SDK's own table
 memory.assign(nvn::kFormatTable+nvn::kFormatCount*48,0);module.base=uint64_t(memory.data());module.size=memory.size();
 for(int k=0;k<3;k++) {auto e=memory.data()+nvn::kFormatTable+48*(k+1);e[8]=rec[k][1];e[9]=rec[k][2];e[16]=rec[k][3];}
 return;
#endif
 memory.assign(128,0);module.base=uint64_t(memory.data());module.size=memory.size();
 for(int k=0;k<3;k++) std::memcpy(&memory[40+8*k],rec[k],4);
 uint64_t h=14695981039346656037ull;
 for(size_t i=32;i<64;i++)h=(h^memory[i])*1099511628211ull;
 std::ofstream o("synthetic.profile");
 o<<"NX_FORMAT_PROFILE_V1\n"<<std::hex<<32<<' '<<4<<' '<<8<<" 1 2 3 0 1 "<<h<<'\n';o.close();
 setenv("NX_NVN_FORMAT_PROFILE","synthetic.profile",1);
}
uint64_t storage(uint32_t target,uint32_t f,uint32_t w,uint32_t h,uint32_t d,uint32_t levels) {
 values={{"nvnTextureBuilderGetTarget",target},{"nvnTextureBuilderGetFormat",f},{"nvnTextureBuilderGetWidth",w},
 {"nvnTextureBuilderGetHeight",h},{"nvnTextureBuilderGetDepth",d},{"nvnTextureBuilderGetLevels",levels},
 {"nvnTextureBuilderGetSamples",0},{"nvnTextureBuilderGetStride",0}};
 CPU c{};c.x[0]=123;hooks.at("nvnTextureBuilderGetStorageSize")(c);
 assert(texture_storage_size(c,123)==c.x[0]);
 return c.x[0];
}
// Reference Maxwell block-linear tiler (independent of nvn_tiling.cpp): byte (x, y) of a GOB is at
// (x/32)*256 + (y/2)*64 + ((x/16)%2)*32 + (y%2)*16 + x%16; GOBs stack bh high in a block; blocks left to right, then
// down; a level's block height halves while the level fits in half a block; each layer is the whole chain, aligned to
// one level-0 block.
uint64_t gob_byte(uint32_t x,uint32_t y) {return (x/32)*256+(y/2)*64+((x/16)%2)*32+(y%2)*16+x%16;}
uint32_t level_bh(uint32_t rows,uint32_t bh0) {uint32_t g=(rows+7)/8,h=1;while(h<g&&h<32)h<<=1;return std::min(h,bh0);}
struct Ref {uint64_t layer_stride,size;};
uint8_t pattern(uint32_t layer,uint32_t level,uint64_t at) {return uint8_t((at*131+level*29+layer*71+(at>>8))^0x5a);}
Ref tile(std::vector<uint8_t>& out,uint32_t w,uint32_t h,uint32_t layers,uint32_t levels,uint32_t bw,uint32_t bhk,uint32_t bytes,uint32_t bh0,uint64_t size) {
 uint64_t chain=0;std::vector<uint64_t> at;
 for(uint32_t l=0;l<levels;l++) {
  uint32_t wb=(std::max(1u,w>>l)+bw-1)/bw,hb=(std::max(1u,h>>l)+bhk-1)/bhk,b=level_bh(hb,bh0);
  at.push_back(chain);chain+=(uint64_t(wb)*bytes+63)/64*((hb+8*b-1)/(8*b))*512*b;
 }
 uint64_t stride=(chain+512*bh0-1)/(512*bh0)*(512*bh0);
 out.assign(size,0xee);
 for(uint32_t z=0;z<layers;z++) for(uint32_t l=0;l<levels;l++) {
  uint32_t wb=(std::max(1u,w>>l)+bw-1)/bw,hb=(std::max(1u,h>>l)+bhk-1)/bhk,b=level_bh(hb,bh0);
  uint64_t gobs_x=(uint64_t(wb)*bytes+63)/64;
  for(uint32_t y=0;y<hb;y++) for(uint64_t x=0;x<uint64_t(wb)*bytes;x++) {
   uint64_t gx=x/64,gy=y/8;
   uint64_t o=z*stride+at[l]+((gy/b)*gobs_x+gx)*512*b+(gy%b)*512+gob_byte(uint32_t(x%64),y%8);
   assert(o<size);out[o]=pattern(z,l,uint64_t(y)*wb*bytes+x);
  }
 }
 return {stride,stride*(layers-1)+chain};
}
void round_trip(uint32_t f,uint32_t w,uint32_t h,uint32_t levels,uint32_t bh0,uint64_t want) {
 uint32_t bw,bhk,bytes;nvn::format_block(f,bw,bhk,bytes);
 uint64_t size=storage(8,f,w,h,1,levels);assert(size==want);
 std::vector<uint8_t> tiled,linear;
 Ref r=tile(tiled,w,h,6,levels,bw,bhk,bytes,bh0,size);
 assert(r.size<=size&&r.layer_stride*6==size);
 auto lv=nvn::deswizzle_texture(tiled.data(),size,w,h,6,levels,bw,bhk,bytes,linear,bh0);
 assert(lv.size()==levels);
 for(uint32_t l=0;l<levels;l++) for(uint32_t z=0;z<6;z++)
  for(uint64_t k=0;k<lv[l].layer_size;k++) assert(linear[lv[l].offset+z*lv[l].layer_size+k]==pattern(z,l,k));
 // One face's size, as before the overlay, cannot hold the six.
 assert(nvn::deswizzle_texture(tiled.data(),size/6,w,h,6,levels,bw,bhk,bytes,linear,bh0).empty());
}
int main(int argc,char** argv) {
 const std::string mode=argc>1?argv[1]:"";
 formats();
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
 // The two cube maps of the trace: 64x64 BC6H, 7 levels, block height 2 (face 0x2000) and 256x256 RGBA16F,
 // 9 levels, block height 16 (face 0xac000). Six faces each, and their data untiles back exactly.
 round_trip(1,64,64,7,2,6*0x2000);
 round_trip(2,256,256,9,16,6*0xac000);
 round_trip(3,40,24,6,1,storage(1,3,40,24,1,6)*6);  // odd size, BC1-like 8-byte blocks
 assert(storage(8,1,64,64,6,7)==6*0x2000);          // a builder depth of 6 is the same cube map
 bool threw=false;try{storage(8,1,64,64,3,7);}catch(const std::runtime_error& e){threw=std::string(e.what()).find("cube map")!=std::string::npos;}
 assert(threw);
 // Other targets are unchanged: 2D, 2D array and cube map array keep the builder's depth.
 assert(storage(1,1,64,64,1,7)==0x2000&&storage(4,1,64,64,6,7)==6*0x2000&&storage(9,1,64,64,12,7)==12*0x2000);
 std::cout<<"PASS strict cube storage: 6 faces whatever the builder depth; trace sizes untile exactly; others unchanged\n";
#else
 // Before the overlay (and in the default profile): one face, too small for the six the image has.
 assert(storage(8,1,64,64,1,7)==0x2000&&storage(8,2,256,256,1,9)==0xac000);
 std::vector<uint8_t> tiled,linear;tile(tiled,64,64,6,7,4,4,16,2,6*0x2000);
 assert(nvn::deswizzle_texture(tiled.data(),0x2000,64,64,6,7,4,4,16,linear,2).empty());
 std::cout<<"PASS "<<(mode.empty()?"default":mode)<<": a depth-1 cube map is sized as one face and cannot be untiled\n";
#endif
 return 0;
}
'''


class NvnCubeStorageTests(unittest.TestCase):
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
        out = ROOT / '.local/nvn-cube-storage-124' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        source = out / 'source'
        stacked = runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in ORDER])
        nvn = source / 'runtime/src/nvn'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), '-I', str(vulkan)]

        def run(name, flags, mode):
            fixture = out / (name + '.cpp')
            fixture.write_text(FIXTURE)
            binary = out / name
            build = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, str(fixture),
                                    str(nvn / 'nvn_tiling.cpp'), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary), *([mode] if mode else [])], cwd=out, capture_output=True,
                                    text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS', result.stdout)
            print(result.stdout, end='')

        run('before', ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1'], 'before strict')
        patch = ROOT / 'runtime/patches' / OVERLAY
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(applied.keys(), stacked.keys())
        self.assertEqual(sorted(k for k in applied if applied[k] != stacked[k]),
                         ['runtime/src/nvn/nvn_texture_layout.cpp'])
        self.assertNotRegex(patch.read_text(), r'/(?:Users|home)/')
        run('strict', ['-DNX_ASTRAL_STRICT=1'], '')
        run('default', [], '')

        name = nvn / 'nvn_texture_layout.cpp'
        for flags in (['-DNX_ASTRAL_STRICT=1'], []):
            check = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, '-fsyntax-only', str(name)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        patched = preprocessed(compiler, includes, name)
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        self.assertEqual(patched, preprocessed(compiler, includes, name), 'default profile differs')
        print('PASS changed TU: strict/default syntax; default profile preprocesses identically')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
