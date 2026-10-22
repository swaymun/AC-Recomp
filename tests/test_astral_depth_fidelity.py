"""Execute the shipped depth/mask and SPIR-V fixes on synthetic inputs, no game required."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime

PATCH = ROOT / 'runtime/patches/astral-depth-fidelity.patch'


def new_header():
    section = PATCH.read_text().split('+++ b/runtime/src/nvn/nvn_depth_fidelity.h\n', 1)[1].split('diff --git ', 1)[0]
    return ''.join(line[1:] + '\n' for line in section.splitlines() if line.startswith('+'))


FIXTURE = r'''
#include <cassert>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <vector>
#if defined(NX_TEST_WINDOWS)
#define _WIN32 1
#endif
#include "nvn_depth_fidelity.h"
using namespace nx::nvn;
namespace nx::nvn {
enum : uint32_t { OpTypeInt=21, OpTypeFloat=22, OpTypeVector=23, OpFunction=54, OpBitcast=124, OpDecorate=71 };
struct Inst { size_t at; uint32_t op, len; };
// PRODUCTION_PASS
// PRODUCTION_PRECISE
}
uint32_t bits(float x) { uint32_t b; std::memcpy(&b,&x,4); return b; }
float flt(uint32_t b) { float x; std::memcpy(&x,&b,4); return x; }
uint32_t half(uint32_t h) {
 uint32_t s=(h&0x8000)<<16, e=(h>>10)&31, m=h&1023;
 if(e==31)return s|0x7f800000|(m<<13);
 float x=e ? std::ldexp(float(1024+m),int(e)-25) : std::ldexp(float(m),-24);
 return bits(x)|s;
}
int main(int argc,char** argv) {
 if(argc==2) {
  bool expected=std::string(argv[1])!="off";
  bool extras=std::string(argv[1])=="all";
  assert(exact_equal_enabled()==expected);
  assert(depth_fidelity_option("NX_HALF_BITS")==extras);
  assert(depth_fidelity_option("NX_VERTEX_PRECISE")==extras);
  ShaderInfo fs;fs.stage=ShaderStage::Fragment;
  fs.refl.outputs.push_back({3,0,ScalarType::Float,4,1});
  assert(effective_fragment_outputs(&fs)==(extras?8u:255u));
  std::cout<<"PASS platform defaults / disable switches\n";return 0;
 }
 // Reflect a synthetic sparse MRT shader with an array and a depth built-in.
 std::ifstream rf("fragment.spv",std::ios::binary);std::vector<uint32_t> rw;uint32_t rword;
 while(rf.read(reinterpret_cast<char*>(&rword),4))rw.push_back(rword);
 ShaderInfo reflected;std::string error;
 assert(reflect_spirv(rw.data(),rw.size(),reflected.refl,&error));
 reflected.stage=reflected.refl.stage;
 assert(fragment_output_locations(&reflected)==0x69); // 0,3,5,6; FragDepth excluded
 // All compare functions, writes, stencil-independent depth semantics.
 for(uint32_t f=0;f<=8;f++)for(bool w:{false,true}) {
  assert(fidelity_depth_func(f,w,true)==f);
  assert(fidelity_depth_func(f,w,false)==(f==3&&!w?4u:f));
 }
 assert(fragment_output_locations(nullptr)==0); // vertex-only prepass preserves every MRT
 ShaderInfo fs;fs.stage=ShaderStage::Fragment;
 assert(fragment_output_locations(&fs)==0); // depth-only fragment stage
 fs.refl.outputs={{0,0,ScalarType::Float,4,1},{3,1,ScalarType::Float,1,1},
                  {5,0,ScalarType::Uint,4,2},{7,0,ScalarType::Float,4,100},
                  {32,0,ScalarType::Float,4,1},{0xffffffffu,0,ScalarType::Float,4,10}};
 uint32_t mask=fragment_output_locations(&fs);
 assert(mask==0xe9); // sparse targets, bounded arrays, component output, invalid locations
 for(uint32_t k=0;k<8;k++)for(uint32_t guest=0;guest<16;guest++) {
  uint32_t effective=fragment_color_mask(guest,mask,k);
  assert(effective==(guest&((mask>>k&1)?15u:0u)));
  uint32_t sentinel=0x98765432, result=sentinel;
  for(uint32_t c=0;c<4;c++)if(effective>>c&1)result&=~(15u<<(c*4));
  if(!(mask>>k&1))assert(result==sentinel);
 }
 // Synthetic shader assembled by spirv-as; no owned shader bytes in the fixture.
 std::ifstream f("input.spv",std::ios::binary);
 std::vector<uint32_t> in; uint32_t word;
 while(f.read(reinterpret_cast<char*>(&word),4))in.push_back(word);
 std::vector<uint32_t> out;
 assert(expand_half_unpack(in,out));
 std::ofstream g("output.spv",std::ios::binary);g.write(reinterpret_cast<char*>(out.data()),out.size()*4);g.close();
 std::vector<uint32_t> precise, again;
 assert(precise_vertex_math(out,precise));
 assert(!precise_vertex_math(precise,again)); // existing decorations are not duplicated
 out.swap(precise);
 std::ofstream pg("precise.spv",std::ios::binary);pg.write(reinterpret_cast<char*>(out.data()),out.size()*4);pg.close();
 assert(!expand_half_unpack(out,again)); // idempotent
 auto malformed=in;malformed.back()=0;assert(!expand_half_unpack(malformed,again));
 // Interpret the *emitted production instructions* for every binary16 bit pattern,
 // both lanes. This covers signed zero, all subnormals, infinities and NaN payloads.
 for(uint32_t h=0;h<65536;h++) {
  std::vector<uint32_t> v(out[3]);std::map<uint32_t,std::vector<uint32_t>> vec;
  uint32_t uint_type=0, entry=0;bool found=false;
  for(size_t i=5;i<out.size();) {
   uint32_t op=out[i]&65535,n=out[i]>>16;const uint32_t* w=&out[i];
   if(op==21&&w[2]==32&&!w[3])uint_type=w[1];
   if(op==15)entry=w[2];
   if(op==43)v[w[2]]=w[3];
   // The synthetic uint input constant is deliberately unique.
   if(op==43&&w[1]==uint_type&&w[3]==0x12345678)v[w[2]]=h|((65535-h)<<16);
   auto a=[&](int k){return v[w[k]];};
   if(op==128)v[w[2]]=a(3)+a(4);
   if(op==194)v[w[2]]=a(3)>>a(4);
   if(op==196)v[w[2]]=a(3)<<a(4);
   if(op==197)v[w[2]]=a(3)|a(4);
   if(op==199)v[w[2]]=a(3)&a(4);
   if(op==170)v[w[2]]=a(3)==a(4);
   if(op==169)v[w[2]]=a(3)?a(4):a(5);
   if(op==112)v[w[2]]=bits(float(a(3)));
   if(op==133)v[w[2]]=bits(flt(a(3))*flt(a(4)));
   if(op==124)v[w[2]]=a(3);
   if(op==80&&n==5) {
    assert(a(3)==half(h)&&a(4)==half(65535-h));found=true;
   }
   i+=n;
  }
  assert(found&&entry);
 }
 std::cout<<"PASS compares; sparse/array/vertex-only MRT preservation; 131072 half conversions incl NaN/Inf/-0\n";
}
'''

ASSEMBLY = '''
OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos
OpDecorate %pos BuiltIn Position
%void = OpTypeVoid
%fn = OpTypeFunction %void
%u = OpTypeInt 32 0
%f = OpTypeFloat 32
%v2 = OpTypeVector %f 2
%v4 = OpTypeVector %f 4
%ptr = OpTypePointer Output %v4
%pos = OpVariable %ptr Output
%packed = OpConstant %u 305419896
%zero = OpConstant %f 0
%one = OpConstant %f 1
%main = OpFunction %void None %fn
%label = OpLabel
%unpack = OpExtInst %v2 %glsl UnpackHalf2x16 %packed
%x = OpCompositeExtract %f %unpack 0
%y = OpCompositeExtract %f %unpack 1
%p = OpCompositeConstruct %v4 %x %y %zero %one
OpStore %pos %p
OpReturn
OpFunctionEnd
'''


FRAGMENT_ASSEMBLY = r'''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %o0 %o3 %o5 %depth
OpExecutionMode %main OriginUpperLeft
OpExecutionMode %main DepthReplacing
OpDecorate %o0 Location 0
OpDecorate %o3 Location 3
OpDecorate %o3 Component 1
OpDecorate %o5 Location 5
OpDecorate %depth BuiltIn FragDepth
%void = OpTypeVoid
%fn = OpTypeFunction %void
%u = OpTypeInt 32 0
%two = OpConstant %u 2
%f = OpTypeFloat 32
%v4 = OpTypeVector %f 4
%arr = OpTypeArray %v4 %two
%pv4 = OpTypePointer Output %v4
%pf = OpTypePointer Output %f
%pa = OpTypePointer Output %arr
%o0 = OpVariable %pv4 Output
%o3 = OpVariable %pf Output
%o5 = OpVariable %pa Output
%depth = OpVariable %pf Output
%zero = OpConstant %f 0
%vzero = OpConstantNull %v4
%azero = OpConstantNull %arr
%main = OpFunction %void None %fn
%label = OpLabel
OpStore %o0 %vzero
OpStore %o3 %zero
OpStore %o5 %azero
OpStore %depth %zero
OpReturn
OpFunctionEnd
'''


class DepthFidelityTests(unittest.TestCase):
    def test_shipped_algorithms_and_spirv(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        # Read the exact implementation out of the diff, not a test-side model.
        section = PATCH.read_text().split('+++ b/runtime/src/nvn/nvn_spirv_patch.cpp\n', 1)[1]
        added = '\n'.join(s[1:] for s in section.splitlines() if s.startswith('+'))
        production = added[added.index('bool expand_half_unpack('):added.index('// END_HALF_PASS')]
        precise = added[added.index('bool precise_vertex_math('):added.index('// END_PRECISE_PASS')]
        header = new_header()
        with tempfile.TemporaryDirectory(prefix='depth fidelity ') as d:
            out = Path(d)
            (out/'nvn_depth_fidelity.h').write_text(header)
            # This public header is unchanged by the candidate; use the local pin when present.
            reference = Path(os.environ.get('NVN_REFERENCE', '/nonexistent'))
            source_header = reference/'runtime/src/nvn/nvn_shaders.h'
            if not source_header.is_file():
                self.skipTest('NVN_REFERENCE with pinned public runtime required')
            shutil.copyfile(source_header, out/'nvn_shaders.h')
            (out/'fixture.cpp').write_text(FIXTURE.replace('// PRODUCTION_PASS', production).replace('// PRODUCTION_PRECISE',precise))
            (out/'input.spvasm').write_text(ASSEMBLY)
            (out/'fragment.spvasm').write_text(FRAGMENT_ASSEMBLY)
            subprocess.run(['spirv-as','--target-env','vulkan1.1',str(out/'fragment.spvasm'),'-o',str(out/'fragment.spv')],check=True,capture_output=True)
            subprocess.run(['spirv-val','--target-env','vulkan1.1',str(out/'fragment.spv')],check=True,capture_output=True)
            subprocess.run(['spirv-as','--target-env','vulkan1.1',str(out/'input.spvasm'),'-o',str(out/'input.spv')],check=True,capture_output=True)
            for flags, name in (([], 'native'), (['-DNX_TEST_WINDOWS=1','-DNX_ASTRAL_STRICT=1'], 'windows')):
                result=subprocess.run([compiler,'-std=c++20','-O1',*flags,'-I'+str(source_header.parent),'fixture.cpp',str(source_header.parent/'nvn_spirv_reflect.cpp'),'-o',name],cwd=out,text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([str(out/'native')],cwd=out,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
            subprocess.run(['spirv-val','--target-env','vulkan1.1',str(out/'output.spv')],check=True,capture_output=True)
            subprocess.run(['spirv-val','--target-env','vulkan1.1',str(out/'precise.spv')],check=True,capture_output=True)
            for name, env, expected in (
                ('native', {}, 'off'), ('windows', {}, 'on'),
                ('windows', {'NX_EXACT_EQUAL':'1','NX_FRAG_OUTPUT_MASK':'1','NX_HALF_BITS':'1','NX_VERTEX_PRECISE':'1'}, 'all'),
                ('windows', {'NX_EXACT_EQUAL':'0','NX_FRAG_OUTPUT_MASK':'0','NX_HALF_BITS':'0','NX_VERTEX_PRECISE':'0'}, 'off')):
                result=subprocess.run([str(out/name),expected],cwd=out,env={**os.environ,**env},text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print('PASS half/precise SPIR-V validation and idempotence; Windows defaults and four switches; non-Windows behavior retained')

    def test_all_series_and_native_syntax(self):
        reference = Path(os.environ.get('NVN_REFERENCE', '/nonexistent'))
        if not reference.is_dir():
            self.skipTest('NVN_REFERENCE required for full-series application')
        with tempfile.TemporaryDirectory(prefix='depth series ') as d:
            for platform in ('macos','linux','windows'):
                names=[s.strip() for s in (ROOT/f'runtime/patches/series.{platform}').read_text().splitlines()
                       if s.strip() and not s.startswith('#')]
                self.assertEqual(names.count(PATCH.name),1)
                self.assertEqual(names[names.index(PATCH.name)-1],'astral-render-fix.patch')
                source=Path(d)/platform
                stop = names.index(PATCH.name) + 1
                runtime.prepare_source(reference,source,[ROOT/'runtime/patches'/n for n in names[:stop]])
                subprocess.run(['git','-C',str(source),'apply','--reverse','--check',str(PATCH)],check=True,capture_output=True)
                for name in names[stop:]:
                    subprocess.run(['git','-C',str(source),'apply',str(ROOT/'runtime/patches'/name)],check=True,capture_output=True)
                if platform=='windows':
                    raster=(source/'runtime/src/nvn/nvn_raster.cpp').read_text()
                    def actual_function(signature):
                        begin=raster.index(signature)
                        return raster[begin:raster.index('\n}',begin)+2]
                    code = r'''#include <cassert>
#include <cstdlib>
#include <iostream>
#define _WIN32 1
#define NX_ASTRAL_STRICT 1
#include "nvn_depth_fidelity.h"
namespace nx::nvn {
struct DepthStencilInfo { bool depth_write=false; uint32_t depth_func=0; };
@UNITS@
@SLACK@
}
int main() {
 using namespace nx::nvn;
 const bool exact=exact_equal_enabled();
 const bool zero=equal_slack_units()==0;
 for (uint32_t f=0;f<=8;++f) for (bool write:{false,true}) {
  DepthStencilInfo d{write,f};
  assert(equal_slack_pass(d)==(!write&&!zero&&((f==3&&!exact)||f==5)));
 }
 std::cout<<"PASS actual EQUAL slack removal, greater opt-in and depth-write guards\n";
}
'''.replace('@UNITS@',actual_function('float equal_slack_units()')).replace('@SLACK@',actual_function('bool equal_slack_pass('))
                    fixture=source/'slack.cpp';fixture.write_text(code);exe=source/'slack'
                    subprocess.run(['c++','-std=c++20','-I'+str(source/'runtime/src/nvn'),str(fixture),'-o',str(exe)],check=True,capture_output=True)
                    for exact,slack in [('0','4'),('1','4'),('1','0')]:
                        result=subprocess.run([str(exe)],env={**os.environ,'NX_EXACT_EQUAL':exact,'NX_EQUAL_SLACK':slack,'NX_GREATER_SLACK':'1'},capture_output=True,text=True)
                        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    print('PASS actual raster slack: exact EQUAL has no synthetic bias; guest write/greater policies retained')
                if platform=='macos':
                    for name in ('nvn_pipeline.cpp','nvn_raster.cpp','nvn_spirv_patch.cpp'):
                        result=subprocess.run(['c++','-std=c++20','-DNX_ASTRAL_STRICT=1','-fsyntax-only',
                            '-I'+str(source/'runtime/src'),'-I'+str(source/'runtime/include'),'-I/opt/homebrew/include',
                            str(source/'runtime/src/nvn'/name)],text=True,capture_output=True)
                        self.assertEqual(result.returncode,0,result.stderr)
            print('PASS macOS/Linux/Windows full-series application; all three changed translation units compile')


if __name__=='__main__':
    unittest.main()
