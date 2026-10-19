"""Compile the production layout TU; private SDK evidence is optional and explicit.

Synthetic records cover adapter failure modes. Private evidence exercises real
SDK records when NVN_TEXTURE_EVIDENCE (or this unit's retained receipt) exists.
No device, GPU or guest startup is simulated by these CPU layout tests.
"""
import json
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
from test_nvn_init import PATCHES

FIXTURE = r'''
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include "nvn/nvn.h"
namespace nx {
std::vector<uint8_t> memory;
LoadedModule module{};
bool readable = true, present = true;
uint64_t unreadable_from = UINT64_MAX;
std::map<std::string,HleFn> hooks;
HleRegistrar::HleRegistrar(const char* n,HleFn f) {hooks[n]=f;}
[[noreturn]] void fatal(const char* f, ...) {throw std::runtime_error(f);}
uint64_t find_symbol(const char*) {return 1;}
const LoadedModule* module_at(uint64_t) {return present ? &module : nullptr;}
VmInfo vm_query(uint64_t a) {return {a,1,kMemStatic,(readable && a < unreadable_from) ? 1u : 0u};}
namespace nvn {
std::map<std::string,uint64_t> values;
std::string getter;
uint64_t real_proc(CPU&,const char* name) {getter=name;return 1;}
uint64_t guest_call(CPU&,uint64_t,std::initializer_list<uint64_t>) {return values.at(getter);}
}
}
#include "nvn/nvn_texture_layout.cpp"
using namespace nx;
void init(size_t n) {memory.resize(n);module.base=uint64_t(memory.data());module.size=n;}
uint64_t fingerprint(size_t off,size_t n) {
 uint64_t h=14695981039346656037ull;
 for(size_t i=0;i<n;i++)h=(h^memory[off+i])*1099511628211ull;
 return h;
}
void profile(uint64_t off=32,uint64_t count=4,uint64_t stride=8,uint64_t hash=0) {
 std::ofstream o("synthetic.profile");
 o << "NX_FORMAT_PROFILE_V1\n" << std::hex << off << ' ' << count << ' ' << stride
   << " 1 2 3 0 1 " << (hash ? hash : fingerprint(32,32)) << '\n';
 o.close();setenv("NX_NVN_FORMAT_PROFILE","synthetic.profile",1);
}
void check(uint32_t f,uint32_t w,uint32_t h,uint32_t d,uint32_t levels,uint32_t samples,
           uint32_t stride,uint64_t size,uint64_t align) {
 using namespace nx::nvn;
 values={{"nvnTextureBuilderGetFormat",f},{"nvnTextureBuilderGetWidth",w},
 {"nvnTextureBuilderGetHeight",h},{"nvnTextureBuilderGetDepth",d},
 {"nvnTextureBuilderGetLevels",levels},{"nvnTextureBuilderGetSamples",samples},
 {"nvnTextureBuilderGetStride",stride}};
 CPU c{};c.x[0]=123;c.x[19]=456;c.x[30]=789;
 hooks.at("nvnTextureBuilderGetStorageSize")(c);assert(c.x[0]==size);
 c.x[0]=123;hooks.at("nvnTextureBuilderGetStorageAlignment")(c);assert(c.x[0]==align);
 assert(c.x[19]==456 && c.x[30]==789);
 assert(texture_storage_size(c,123)==size);
}
int main(int argc,char** argv) {
 std::string mode=argc>1?argv[1]:"valid";
 try {
#if defined(NX_ASTRAL_STRICT)
 if(mode=="sdk") {
  std::ifstream in(argv[2],std::ios::binary);
  memory.assign(std::istreambuf_iterator<char>(in),{});
  module.base=uint64_t(memory.data());module.size=memory.size();
  setenv("NX_NVN_FORMAT_PROFILE",argv[3],1);
  std::ifstream cases(argv[4]);uint32_t f,bw,bh,bytes,w,h,d,l,s,p;uint64_t size,alignment;
  while(cases>>f>>bw>>bh>>bytes>>w>>h>>d>>l>>s>>p>>size>>alignment) {
   uint32_t x,y,z;nvn::format_block(f,x,y,z);assert(x==bw && y==bh && z==bytes);
   check(f,w,h,d,l,s,p,size,alignment);
  }
  bool rejected=false;try{uint32_t x,y,z;nvn::format_block(0,x,y,z);}catch(...){rejected=true;}
  assert(rejected);std::cout<<"PASS real SDK records and production storage calculations\n";return 0;
 }
 init(128);
 // Deliberately synthetic record layout and enum indices.
 memory[40]=1;memory[41]=1;memory[42]=1;memory[43]=4;
 memory[48]=1;memory[49]=4;memory[50]=4;memory[51]=8;
 memory[56]=1;memory[57]=12;memory[58]=12;memory[59]=16;
 profile();
 if(mode=="missing")unsetenv("NX_NVN_FORMAT_PROFILE");
 if(mode=="malformed") {std::ofstream o("synthetic.profile");o<<"bad";}
 if(mode=="trailing") {std::ofstream o("synthetic.profile",std::ios::app);o<<"trailing";}
 if(mode=="range")profile(UINT64_MAX);
 if(mode=="stride")profile(32,4,0);
 if(mode=="count")profile(32,UINT64_MAX,8);
 if(mode=="fingerprint")profile(32,4,8,1);
 if(mode=="unreadable")readable=false;
 if(mode=="partial")unreadable_from=module.base+63;
 if(mode=="module")present=false;
 if(mode=="zero") {memory[43]=0;profile();}
 if(mode=="widthzero") {memory[41]=0;profile();}
 if(mode=="heightzero") {memory[42]=0;profile();}
 if(mode=="flags") {memory[40]=2;profile();}
 uint32_t x,y,z;
 nvn::format_block(mode=="invalid"?0:mode=="outside"?4:mode=="huge"?UINT32_MAX:1,x,y,z);
 if(mode!="valid") {std::cerr<<"failure was not rejected\n";return 2;}
 assert(x==1 && y==1 && z==4);
 check(1,17,9,1,1,1,0,2048,1024);
 check(1,65,33,1,3,1,0,24576,4096);
 check(1,1,1,1,1,1,0,512,512);
 check(1,16,7,2,1,1,256,3584,256);
 check(2,17,17,1,1,1,0,512,512);
 check(3,25,97,1,1,1,0,1024,1024);
#else
 init(nvn::kFormatTable + nvn::kFormatCount*48);
 auto e=memory.data()+nvn::kFormatTable+48;e[8]=1;e[9]=1;e[16]=4;
 check(1,17,9,1,1,1,0,2048,1024);
 uint32_t x,y,z;nvn::format_block(UINT32_MAX,x,y,z);assert(x==1&&y==1&&z==4);
 nvn::format_block(0,x,y,z);assert(x==1&&y==1&&z==4);
#endif
 std::cout<<"PASS production layout "<<mode<<'\n';
 } catch(const std::runtime_error& e) {
  if(mode=="valid"||mode=="sdk") {std::cerr<<e.what()<<'\n';return 1;}
  assert(std::string(e.what()).find("strict NVN format") == 0);
  std::cout<<"PASS explicit rejection "<<mode<<": "<<e.what()<<'\n';
 }
}
'''


class TextureLayoutTests(unittest.TestCase):
    def test_production_profiles(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'],
                                             cwd=ROOT, text=True).strip()).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        out = ROOT / '.local/nvn-texture-072' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / n for n in (*PATCHES, 'astral-nvn-texture.patch')]
        source = out / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        (out / 'fixture.cpp').write_text(FIXTURE)
        vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', str(common.parent /
            '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include')))
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'Vulkan headers required')
        results = []
        for name, flags in [('strict', ['-DNX_ASTRAL_STRICT=1']), ('default', [])]:
            binary = out / name
            cmd = [shutil.which('c++'), '-std=c++20', '-pthread', '-DNX_APPLE_HIGH_MEMORY=1',
                   *flags, '-I', str(vulkan), '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'),
                   str(out / 'fixture.cpp'), '-o', str(binary)]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            (out / (name + '-compile.log')).write_text(p.stdout + p.stderr)
            self.assertEqual(p.returncode, 0, p.stderr)
            modes = ['valid'] if name == 'default' else ['valid', 'missing', 'malformed', 'trailing',
                'range', 'stride', 'count', 'fingerprint', 'unreadable', 'partial', 'module', 'zero', 'widthzero', 'heightzero', 'flags',
                'invalid', 'outside', 'huge']
            for mode in modes:
                p = subprocess.run([str(binary), mode], cwd=out, capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn('PASS', p.stdout)
                results.append({'profile': name, 'mode': mode, 'output': p.stdout})
                print(p.stdout, end='')
        evidence = Path(os.environ.get('NVN_TEXTURE_EVIDENCE', str(ROOT / '.local/nvn-texture-072/sdk-evidence.json')))
        if evidence.is_file():
            e = json.loads(evidence.read_text())
            self.assertEqual(runtime.sha(Path(e['sdk_path'])), e['sdk_sha256'])
            self.assertEqual(runtime.sha(Path(e['profile_path'])), e['profile_sha256'])
            cases = Path(e['layout_cases_path'])
            self.assertEqual(runtime.sha(cases), e['layout_cases_sha256'])
            p = subprocess.run([str(out / 'strict'), 'sdk', e['sdk_path'], e['profile_path'], str(cases)],
                               cwd=out, capture_output=True, text=True, timeout=20)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            print(p.stdout, end='')
            results.append({'profile': 'private SDK', 'evidence_sha256': runtime.sha(evidence), 'output': p.stdout})
        else:
            print('Private SDK evidence absent: synthetic coverage only; no actual SDK validation claimed.')
        (out / 'receipt.json').write_text(json.dumps({'source': fingerprint,
            'patches': {p.name: runtime.sha(p) for p in patches}, 'results': results}, indent=2) + '\n')
        print('private receipt:', out / 'receipt.json')
        shutil.rmtree(source)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
