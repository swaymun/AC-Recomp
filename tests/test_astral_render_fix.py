"""Exercise the production packaged-layout call and untiler with synthetic data.

Requires an existing pinned Wonder checkout and Vulkan headers; downloads nothing.
The fixture compiles the packaged-layout region verbatim, not a duplicate decoder.
No SDK bytes, shaders, game assets, credentials, cloud or GPU are used.
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
import prepare_runtime as runtime


FIXTURE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "nvn_tiling.h"
struct CPU {};
struct Texture { uint32_t format=0x80, height=4096, block_height_gobs=0; };
constexpr uint64_t kModuleBase=0x100000000, kKernelBase=0x200000000, kKernelSize=0x1000;
alignas(8) uint32_t output[3]={0x12345678,0,0xabcdef12};
uint32_t layout_word=0x403, present=1, arguments=0;
template<class T> T ld(uint64_t a) {T v;std::memcpy(&v,(void*)a,sizeof v);return v;}
template<class T> void st(uint64_t a,T v) {std::memcpy((void*)a,&v,sizeof v);}
uint64_t scratch(CPU&,size_t n) {assert(n==4);return uint64_t(output+1);}
uint64_t driver(CPU&,const char* name,std::initializer_list<uint64_t> args) {
 assert(std::string(name)=="nvnTextureBuilderGetPackagedTextureLayout");
 assert(*args.begin()==42);arguments=args.size();
 if(arguments==2) st<uint32_t>(*(args.begin()+1),present?layout_word:0);
 return present; // presence and output word are deliberately independent
}
[[noreturn]] void fatal(const char*,uint32_t) {throw std::runtime_error("invalid height");}
void format_block(uint32_t f,uint32_t& w,uint32_t& h,uint32_t& bytes) {w=h=f==0x46?4:8;bytes=f==0x46?8:16;}
uint32_t production_height(uint32_t word,uint32_t has,uint32_t height=4096,uint32_t format=0x80) {
 CPU c;Texture t;t.height=height;t.format=format;uint64_t builder=42;
 layout_word=word;present=has;arguments=0;output[1]=0xdeadbeef;
 // PRODUCTION
 assert(output[0]==0x12345678&&output[2]==0xabcdef12);
 return t.block_height_gobs;
}
// Independent byte-address reference tiler. ASTC8x8 and BC1 have different block
// dimensions and byte sizes; both are affected by the same height retrieval.
// every byte is patterned by its linear coordinate, mip and layer, never by its
// tiled address. The production untiler must recover all levels of every layer.
uint64_t align_up(uint64_t a,uint64_t b) {return (a+b-1)/b*b;}
uint32_t mip_height(uint32_t rows,uint32_t base) {while(base>1&&rows<=base*4)base/=2;return base;}
uint8_t pattern(uint64_t i,uint32_t mip,uint32_t layer) {return uint8_t(i*37+(i>>9)*71+mip*17+layer*113);}
void roundtrip(uint32_t w,uint32_t h,uint32_t word,uint32_t layers,uint32_t mips,bool bc1=false) {
 uint32_t bw=bc1?4:8,bh=bw,bytes=bc1?8:16;
 uint32_t base=production_height(word,1,h,bc1?0x46:0x80);
 std::vector<uint64_t> offsets;
 uint64_t chain=0;
 for(uint32_t m=0;m<mips;m++) {
  uint32_t cols=(std::max(1u,w>>m)+bw-1)/bw,rows=(std::max(1u,h>>m)+bh-1)/bh;
  offsets.push_back(chain);
  chain+=align_up(uint64_t(cols)*bytes,64)*align_up(rows,8*mip_height(rows,base));
 }
 uint64_t stride=align_up(chain,512*base);
 std::vector<uint8_t> tiled(stride*layers,0xcc),linear;
 for(uint32_t z=0;z<layers;z++)for(uint32_t m=0;m<mips;m++) {
  uint32_t cols=(std::max(1u,w>>m)+bw-1)/bw,rows=(std::max(1u,h>>m)+bh-1)/bh,gbh=mip_height(rows,base);
  uint64_t gobs_x=(uint64_t(cols)*bytes+63)/64;
  for(uint32_t y=0;y<rows;y++)for(uint32_t x=0;x<cols*bytes;x++) {
   uint64_t a=z*stride+offsets[m]+((y/(8*gbh))*gobs_x+x/64)*512*gbh;
   a+=(y/8%gbh)*512+(x%64/32)*256+(y%8/2)*64+(x%32/16)*32+(y%2)*16+x%16;
   assert(a<tiled.size());tiled[a]=pattern(uint64_t(y)*cols*bytes+x,m,z);
  }
 }
 auto lv=nx::nvn::deswizzle_texture(tiled.data(),tiled.size(),w,h,layers,mips,bw,bh,bytes,linear,base);
 assert(lv.size()==mips);
 if(base==32)assert(lv[0].block_height_gobs==32);
 for(uint32_t m=0;m<mips;m++)for(uint32_t z=0;z<layers;z++)
  for(uint64_t i=0;i<lv[m].layer_size;i++)assert(linear[lv[m].offset+z*lv[m].layer_size+i]==pattern(i,m,z));
 // The old estimate accepts the same allocation yet returns permuted bytes.
 if((base==8&&h==4096)||bc1) {
  auto bad=nx::nvn::deswizzle_texture(tiled.data(),tiled.size(),w,h,layers,mips,bw,bh,bytes,linear,16);
  assert(!bad.empty());bool differs=false;
  for(uint64_t i=0;i<bad[0].layer_size;i++)differs|=linear[i]!=pattern(i,0,0);
  assert(differs);
 }
}
int main() {
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
 assert(production_height(0x403,1)==8&&arguments==2);
 assert(production_height(0x403,1,512,0x46)==8&&arguments==2); // BC1 chest decal geometry
 assert(production_height(0x400,1)==1&&arguments==2); // zero height field is valid
 assert(production_height(0,1)==1&&arguments==2);     // whole output word may be zero
 assert(production_height(0x405,1)==32);             // not capped at the old 16
 assert(production_height(0x453,1)==8);              // unrelated layout bits do not affect Y
 assert(production_height(0x403,0)==0);              // unpackaged keeps default choice
 for(uint32_t b=6;b<16;b++) {bool threw=false;try{production_height(b,1);}catch(const std::runtime_error&){threw=true;}assert(threw);}
 roundtrip(4096,4096,0x403,1,13);
 roundtrip(1024,512,0x403,2,11,true); // synthetic bytes, observed BC1 decal geometry
 roundtrip(1024,1024,0x403,2,11);
 roundtrip(257,273,0,2,9);
 roundtrip(511,2049,0x405,1,12);
 std::cout<<"PASS strict: output ABI, presence/zero, all height bits, invalid heights; independent mip/layer roundtrips\n";
#else
 assert(production_height(0x403,1)==16&&arguments==1);
 assert(production_height(0x403,1,512,0x46)==16&&arguments==1);
 assert(production_height(0,1)==16); // old code ignores the output word
 assert(production_height(0x403,0)==0);
 std::cout<<"PASS before/default: missing output argument and wrong 16-GOB estimate reproduced\n";
#endif
}
'''


def packaged_region(source):
    start = source.index('    // Packaged (BNTX)')
    strict = source.rfind('#if defined(NX_ASTRAL_STRICT)', 0, start)
    if strict >= 0 and 'uint64_t packaged = scratch(c, 4);' in source[strict:start]:
        start = strict
    return source[start:source.index('    // Swizzle:', start)]


class AstralRenderFixTests(unittest.TestCase):
    def test_production_call_untiler_and_patch_integration(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        repo = (ROOT / common).resolve().parent if not common.is_absolute() else common.parent
        reference = Path(os.environ.get('NVN_REFERENCE', str(repo /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', '/opt/homebrew/include'))
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        patch = ROOT / 'runtime/patches/astral-render-fix.patch'
        with tempfile.TemporaryDirectory(prefix='astral render fix ') as temp:
            out = Path(temp)
            # Compose each shipping stack with render-fix already active.
            sources = []
            for platform in ('macos', 'linux', 'windows'):
                names = [s.strip() for s in (ROOT / f'runtime/patches/series.{platform}').read_text().splitlines()
                         if s.strip() and not s.lstrip().startswith('#')]
                self.assertEqual(names.count(patch.name), 1)
                source = out / platform
                runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in names])
                subprocess.run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(patch)], check=True, capture_output=True)
                sources.append(source)
            source = sources[0]
            # Recover the pre-fix region for the regression fixture, then reapply
            # below to exercise the shipping source against the old behavior.
            subprocess.run(['git', '-C', str(source), 'apply', '--reverse', str(patch)], check=True, capture_output=True)
            filename = source / 'runtime/src/nvn/nvn_objects.cpp'
            original = filename.read_text()
            includes = ['-I', str(source / 'runtime/src/nvn')]

            def run(name, text, flags):
                fixture = out / f'{name}.cpp'
                fixture.write_text(FIXTURE.replace(' // PRODUCTION', packaged_region(text)))
                binary = out / name
                result = subprocess.run([compiler, '-std=c++20', '-O1', '-pthread', *flags, *includes,
                    str(fixture), str(source / 'runtime/src/nvn/nvn_tiling.cpp'), '-o', str(binary)],
                    capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS', result.stdout)
                print(result.stdout, end='')

            run('before', original, ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1'])
            subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
            modified = filename.read_text()
            run('strict', modified, ['-DNX_ASTRAL_STRICT=1'])
            run('default', modified, [])
            includes += ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), '-I', str(vulkan)]
            for flags in (['-DNX_ASTRAL_STRICT=1'], []):
                result = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes,
                    '-fsyntax-only', str(filename)], capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Preprocess the production region to demonstrate default-title identity.
            before = out / 'before-region.cpp'
            after = out / 'after-region.cpp'
            before.write_text(packaged_region(original))
            after.write_text(packaged_region(modified))
            def preprocess(path):
                return subprocess.check_output([compiler, '-E', '-P', str(path)], text=True)
            self.assertEqual(preprocess(before).split(), preprocess(after).split())
            print('PASS macos/linux/windows series application; complete changed TU syntax in both profiles; default region unchanged')


if __name__ == '__main__':
    unittest.main()
