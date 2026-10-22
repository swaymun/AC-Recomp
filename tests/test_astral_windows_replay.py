"""Execute shipped replay storage/options/key/state helpers on synthetic commands.

No game, credentials, VM or network is used. Full-series checks use an existing pin.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT/'runtime/patches/astral-windows-replay.patch'
sys.path.insert(0, str(ROOT/'tools'))
import prepare_runtime


def added(name):
    body = PATCH.read_text().split('+++ b/runtime/src/nvn/'+name+'\n', 1)[1].split('\ndiff --git ', 1)[0]
    return '\n'.join(s[1:] for s in body.splitlines() if s.startswith('+'))+'\n'


def function(text, signature):
    start = text.index(signature)
    at = text.index('{', start)
    depth = 1
    end = at+1
    while depth:
        depth += (text[end]=='{')-(text[end]=='}')
        end += 1
    return text[start:end]


PREAMBLE = r'''
#ifndef NOMINMAX
#define NOMINMAX 1
#endif
#include <cassert>
#include <cstring>
#include <iostream>
#include <thread>
#include <algorithm>
#include <string>
#if defined(NX_TEST_WINDOWS) && !defined(_WIN32)
#define _WIN32 1
#endif
#include "nvn_command_storage.h"
using namespace nx::nvn;
void env(const char* name,const char* value) {
#if defined(_MSC_VER)
 _putenv_s(name,value);
#else
 setenv(name,value,1);
#endif
}
'''

STORAGE = r'''
namespace nx::nvn {
@COMMANDS@
struct CommandBuffer { std::mutex lock; std::shared_ptr<CmdList> recording; };
CommandBuffer* current=nullptr;
std::atomic<unsigned> g_no_cb{0};
template<class T> T* get(uint64_t) { return static_cast<T*>(current); }
@RECORD@
}
int main() {
 assert(replay_options().pool);
 auto pool=std::make_shared<CommandListPool<CmdList>>();
 auto list=pool->acquire(pool); auto queued=list;
 CommandBuffer cb; cb.recording=list; current=&cb;
 std::vector<uint8_t> bytes(257); for(size_t k=0;k<bytes.size();++k)bytes[k]=uint8_t(k);
 for(unsigned k=0;k<4096;++k) {
  Cmd c{Cmd::BindVertexAttribs}; c.n=k; record(1,c,bytes.data(),bytes.size());
 }
 for(unsigned k=0;k<4096;++k) {
  assert(list->cmds[k].n==k && list->cmds[k].blob==k);
  auto view=list->blobs[k]; assert(view.size()==bytes.size());
  assert(reinterpret_cast<uintptr_t>(view.data())%alignof(std::max_align_t)==0);
  assert(!std::memcmp(view.data(),bytes.data(),bytes.size()));
 }
 list->handle=42;list->epoch=99;list->own_dispatches=7;list->scanned_size=4096;list->calls={1,2,3};
 auto address=list.get(); cb.recording.reset(); list.reset();
 auto other=pool->acquire(pool); assert(other.get()!=address); // queued owner pins immutable commands
 assert(queued->handle==42 && queued->blobs[4095].size()==257);
 queued.reset(); auto reused=pool->acquire(pool); assert(reused.get()==address);
 assert(reused->cmds.empty() && !reused->blobs.size() && reused->calls.empty());
 assert(!reused->handle && !reused->epoch && !reused->own_dispatches && reused->scanned_size==SIZE_MAX);
 // Warm capacities survive recycling; recording the same workload needs no blob heap allocations.
 auto capacity=reused->retained_bytes();cb.recording=reused;
 for(unsigned k=0;k<4096;++k)record(1,Cmd{Cmd::SetRenderTargets},bytes.data(),bytes.size());
 assert(reused->retained_bytes()==capacity);cb.recording.reset();reused.reset();other.reset();
 std::vector<std::thread> threads;
 for(int t=0;t<4;++t)threads.emplace_back([pool] {
  for(int k=0;k<1000;++k) {
   auto item=pool->acquire(pool); item->handle=uint64_t(k+1);
   auto pinned=item;item.reset(); assert(pinned->handle==uint64_t(k+1));
  }
 });
 for(auto& t:threads)t.join();
 // Bound both object count and retained capacity, independently of live/queued lists.
 std::vector<std::shared_ptr<CmdList>> many;
 for(int k=0;k<300;++k)many.push_back(pool->acquire(pool));
 many.clear();assert(g_replay_released>=44 && pool->retained_bytes()<=32u*1024*1024);
 auto huge=pool->acquire(pool);huge->cmds.reserve((33u<<20)/sizeof(Cmd)+1);huge.reset();
 assert(pool->retained_bytes()<=32u*1024*1024 && g_replay_reused>1000);
 std::cout<<"PASS production record payloads/alignment/growth, queued-owner lifetime, reset, reuse, concurrency and bounds\n";
}
'''

OPTIONS = r'''
int main(int argc,char** argv) {
 bool cached=std::string(argv[1])=="cached";
 assert(replay_options().environment==cached);
 assert(!replay_resident_enabled() && replay_resident_part(false) && replay_resident_part(true));
 env("NX_RESIDENT","1");env("NX_RESIDENT_READ","0");env("NX_RESIDENT_STORAGE","0");
 assert(replay_resident_enabled()==!cached && replay_resident_part(false)==cached && replay_resident_part(true)==cached);
 env("NX_REPLAY_POOL","1");assert(!replay_options().pool); // frozen process options
 std::cout<<"PASS cached launch flags and original uncached A/B behavior\n";
}
'''

KEYS = r'''
#include "nvn_pipeline.h"
#include "nvn_replay_keys.h"
namespace nx::nvn { VkFormat vk_vertex_format(uint32_t f) { return f==~0u ? VK_FORMAT_UNDEFINED : VK_FORMAT_R32G32B32A32_SFLOAT; } }
using namespace nx::nvn;
int main() {
 ShaderInfo vs; vs.refl.inputs={{2,0,ScalarType::Float,4,1}};
 PipelineKey a;std::memset(&a,0,sizeof a);a.vs=&vs;a.attrib_count=16;a.stream_count=16;
 a.attribs[2]={1,8,4};a.streams[4]={32,0};a.color_count=1;a.mask.mask[0]=15;
 a.color_formats[0]=VK_FORMAT_R8G8B8A8_UNORM;
 auto b=a;b.attribs[7]={123,456,9};b.streams[9]={666,1};b.blend[0].src_rgb=42;
 b.blend[7].dst_a=12;b.color.blend_enable[7]=1;b.color.alpha_test=123;b.color.logic_op=321;
 b.mask.mask[7]=255;b.color_formats[7]=VK_FORMAT_R32_SFLOAT;b.ufloat_colors=128;
 canonical_replay_key(a);canonical_replay_key(b);assert(!std::memcmp(&a,&b,sizeof a));
 assert(a.attrib_count==3 && a.stream_count==5 && a.attribs[2].stream==4 && a.streams[4].stride==32);
 auto differs=[&](auto mutate) { auto c=a;mutate(c);canonical_replay_key(c);assert(std::memcmp(&a,&c,sizeof a)); };
 differs([](auto& c){c.attribs[2].offset++;});differs([](auto& c){c.streams[4].stride++;});
 differs([](auto& c){c.depth.depth_func++;});differs([](auto& c){c.depth.depth_write=1;});
 differs([](auto& c){c.mask.mask[0]=7;});differs([](auto& c){c.polygon.cull=2;});
 a.color.blend_enable[0]=1;a.blend[0].src_rgb=2;b=a;b.blend[0].src_rgb=3;
 canonical_replay_key(a);canonical_replay_key(b);assert(std::memcmp(&a,&b,sizeof a));
 vs.refl.inputs.push_back({15,0,ScalarType::Float,4,1});a.attrib_count=16;a.attribs[15]={~0u,999,2};
 canonical_replay_key(a);assert(a.attrib_count==16 && a.attribs[15].format==~0u && a.streams[2].stride==0);
 std::cout<<"PASS unused-field hits, effective vertex/blend/depth/polygon/mask misses and invalid-format fallback\n";
}
'''


ENV_LOOKUPS = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <iostream>
#if defined(NX_TEST_WINDOWS) && !defined(_WIN32)
#define _WIN32 1
#endif
unsigned part_queries=0;
namespace std {
inline char* counted_getenv(const char* name) {
 if (!std::strcmp(name,"NX_RESIDENT_READ") || !std::strcmp(name,"NX_RESIDENT_STORAGE")) ++part_queries;
 return std::getenv(name);
}
}
#define getenv counted_getenv
#include "nvn_resident.h"
#undef getenv
namespace nx::plat {
uint64_t monotonic_ns(){return 1;}
bool write_watch_pages(const uint8_t*,uint64_t,std::vector<uint64_t>&,uint64_t&,uint64_t&){return false;}
}
namespace nx::nvn {void frame_wait_all(){}}
int main(int argc,char** argv) {
 using namespace nx::nvn;using namespace nx::nvn::replay;
 const bool cached=std::string(argv[1])=="cached";
 assert(replay_options().environment==cached);part_queries=0;
 Upload out;
 for(int k=0;k<17;++k) assert(!resident_upload(nullptr,1,1,1,false,out));
 assert(part_queries==(cached?0u:17u)); // original off control must query even for tiny bypassed reads
 std::cout<<"PASS production tiny-read bypass keeps all original off lookups; enabled path caches them\n";
}
'''


DYNAMIC = r'''
#include <vulkan/vulkan.h>
#include "nvn_replay_options.h"
namespace nx::nvn {
struct Upload { uint64_t buffer=0, offset=0; };
struct State {
 uint8_t stencil_ref[2]{},stencil_compare_mask[2]{},stencil_write_mask[2]{};
 float bias_factor=0,bias_units=0,bias_clamp=0,blend_color[4]{};
 struct { bool depth_test=false; } depth;
} g_state;
@BOUND@
uint64_t g_state_set=0,g_state_kept=0;
template<class T> bool same_bytes(const T& a,const T& b){return !std::memcmp(&a,&b,sizeof(T));}
unsigned ref_calls=0,cmp_calls=0,write_calls=0,bias_calls=0,vp_calls=0,sc_calls=0,blend_calls=0;
void p_vkCmdSetStencilReference(VkCommandBuffer,VkStencilFaceFlags,uint32_t){++ref_calls;}
void p_vkCmdSetStencilCompareMask(VkCommandBuffer,VkStencilFaceFlags,uint32_t){++cmp_calls;}
void p_vkCmdSetStencilWriteMask(VkCommandBuffer,VkStencilFaceFlags,uint32_t){++write_calls;}
void p_vkCmdSetDepthBias(VkCommandBuffer,float,float,float){++bias_calls;}
void p_vkCmdSetViewport(VkCommandBuffer,uint32_t,uint32_t,const VkViewport*){++vp_calls;}
void p_vkCmdSetScissor(VkCommandBuffer,uint32_t,uint32_t,const VkRect2D*){++sc_calls;}
void p_vkCmdSetBlendConstants(VkCommandBuffer,const float*){++blend_calls;}
bool equal_slack_pass(const decltype(State::depth)&){return false;}
float equal_slack_units(){return 4;}
VkPhysicalDeviceFeatures vk_features(){VkPhysicalDeviceFeatures f{};f.depthBiasClamp=true;return f;}
@RASTER@
@DYNAMIC@
}
using namespace nx::nvn;
int main(int argc,char** argv) {
 bool filtering=std::string(argv[1])=="on";assert(replay_options().dynamic==filtering);
 auto cb=reinterpret_cast<VkCommandBuffer>(uintptr_t(1));
 VkViewport vp{0,0,1600,900,0,1};VkRect2D sc{{0,0},{1600,900}};
 set_dynamic(cb,vp,sc);assert(ref_calls==1&&cmp_calls==1&&write_calls==1&&bias_calls==1);
 set_dynamic(cb,vp,sc);assert(ref_calls==1&&bias_calls==1&&vp_calls==1&&sc_calls==1&&blend_calls==1);
 g_state.stencil_ref[0]=g_state.stencil_ref[1]=7;set_dynamic(cb,vp,sc);
 assert(ref_calls==2&&cmp_calls==(filtering?1u:2u)&&write_calls==(filtering?1u:2u)&&bias_calls==(filtering?1u:2u));
 auto refs=ref_calls;auto biases=bias_calls;g_state.bias_units=3;set_dynamic(cb,vp,sc);
 assert(bias_calls==biases+1&&ref_calls==refs+(filtering?0:1));
 // New command-buffer and helper-pass boundaries forget every group, even at the same values.
 refs=ref_calls;biases=bias_calls;g_bound=Bound{};set_dynamic(cb,vp,sc);
 assert(ref_calls==refs+1&&bias_calls==biases+1&&vp_calls==2&&sc_calls==2&&blend_calls==2);
 g_bound=Bound{};set_dynamic(reinterpret_cast<VkCommandBuffer>(uintptr_t(2)),vp,sc);
 assert(vp_calls==3&&sc_calls==3&&blend_calls==3);
 std::cout<<"PASS production raster/state calls, independent changes and command/helper boundary resets\n";
}
'''


class FixtureMixin:
    def compile(self, code, headers, *, flags=(), includes=(), sources=()):
        cxx = shutil.which('clang-cl' if os.name=='nt' else 'clang++')
        self.assertIsNotNone(cxx, 'C++ compiler required')
        tmp = tempfile.TemporaryDirectory(prefix='replay fixture '); self.addCleanup(tmp.cleanup)
        out=Path(tmp.name)
        for n,t in headers.items(): (out/n).write_text(t)
        (out/'test.cpp').write_text(code)
        exe=out/('test.exe' if os.name=='nt' else 'test')
        if os.name=='nt':
            cmd=[cxx,'/nologo','/std:c++20','/EHsc','/O2','/UNDEBUG','/DNOMINMAX=1',
                 '/DNX_ASTRAL_STRICT=1',*[f'/D{f}' for f in flags],*[f'/I{p}' for p in includes],
                 str(out/'test.cpp'),*map(str,sources),'/Fe'+str(exe),'/Fo'+str(out/'test.obj')]
        else:
            cmd=[cxx,'-std=c++20','-O2','-UNDEBUG','-pthread','-DNX_ASTRAL_STRICT=1',
                 *[f'-D{f}' for f in flags],*[f'-I{p}' for p in includes],str(out/'test.cpp'),*map(str,sources),'-o',str(exe)]
        r=subprocess.run(cmd,cwd=out,text=True,capture_output=True,timeout=120)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return exe

    def run_fixture(self, exe, args=(), env=None):
        clean={k:v for k,v in os.environ.items() if not k.startswith(('NX_REPLAY_','NX_RESIDENT'))}
        r=subprocess.run([str(exe),*args],env={**clean,**(env or {})},capture_output=True,text=True,timeout=60)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('PASS',r.stdout)
        print(r.stdout.strip())

    def headers(self):
        return {n:added(n) for n in ['nvn_command_storage.h','nvn_replay_options.h']}



class ReplayTests(FixtureMixin, unittest.TestCase):
    def test_frozen_environment_and_same_binary_control(self):
        exe=self.compile(PREAMBLE+OPTIONS,self.headers(),flags=['NX_TEST_WINDOWS=1'])
        for value,arg in [('0','uncached'),('1','cached')]:
            self.run_fixture(exe,[arg],{'NX_REPLAY_ENV':value})

    def test_series_scope_and_opt_in_defaults(self):
        from acr_build import read_series
        names=read_series(ROOT/'runtime/patches/series.windows')
        replay_end=names.index(PATCH.name)+1
        self.assertEqual(names[replay_end-4:replay_end],['astral-windows-perf.patch','astral-windows-resident.patch',
                                    'astral-windows-writeback.patch',PATCH.name])
        for p in ['macos','linux']:self.assertNotIn(PATCH.name,read_series(ROOT/f'runtime/patches/series.{p}'))
        text=PATCH.read_text()
        self.assertNotRegex(text,r'/(?:Users|home|work)/|[A-Z]:[\\/]')
        self.assertTrue(all(p.startswith('runtime/src/nvn/') for p in re.findall(r'^diff --git a/(\S+)',text,re.M)))
        exe=self.compile(PREAMBLE+r'''int main(){auto o=replay_options();assert(!o.pool&&!o.keys&&!o.dynamic&&!o.scratch&&!o.environment);std::cout<<"PASS defaults off\\n";}''',self.headers(),flags=['NX_TEST_WINDOWS=1'])
        self.run_fixture(exe)


class FullReplayTests(FixtureMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('NVN_TEST_SOURCE'):
            cls.source=Path(os.environ['NVN_TEST_SOURCE'])
            cls.n=cls.source/'runtime/src/nvn'
            if not (cls.n/'nvn_command_storage.h').is_file():raise RuntimeError('missing built replay source')
            return
        reference=Path(os.environ.get('NVN_REFERENCE','/nonexistent'))
        if not (reference/'.git').is_dir():raise unittest.SkipTest('existing NVN_REFERENCE required for full-series executable fixtures')
        cls.tmp=tempfile.TemporaryDirectory(prefix='replay full series ');cls.addClassCleanup(cls.tmp.cleanup)
        cls.source=Path(cls.tmp.name)/'source'
        from acr_build import read_series
        prepare_runtime.prepare_source(reference,cls.source,[ROOT/'runtime/patches'/n for n in read_series(ROOT/'runtime/patches/series.windows')])
        cls.n=cls.source/'runtime/src/nvn'

    def test_production_record_and_pooled_command_lifetimes(self):
        header=(self.n/'nvn.h').read_text();cmds=header[header.index('struct Cmd {'):header.index('// NX_TRACE_SKINLISTS (nvn_cmd.cpp)')]
        code=PREAMBLE+STORAGE.replace('@COMMANDS@',cmds).replace('@RECORD@',function((self.n/'nvn_cmd.cpp').read_text(),'void record('))
        exe=self.compile(code,self.headers(),flags=['NX_TEST_WINDOWS=1'])
        self.run_fixture(exe,env={'NX_REPLAY_POOL':'1'})

    def test_effective_pipeline_keys(self):
        inc=[self.n,self.source/'runtime/src',self.source/'runtime/include',os.environ.get('NVN_VULKAN_INCLUDE','/opt/homebrew/include')]
        exe=self.compile('#define NOMINMAX 1\n#include <cassert>\n#include <iostream>\n'+KEYS,{},includes=inc)
        self.run_fixture(exe)

    def test_production_off_environment_lookup_control(self):
        import test_astral_windows_resident as resident
        headers={'nvn_resident.h':(self.n/'nvn_resident.h').read_text(),
                 'nvn_replay_options.h':added('nvn_replay_options.h'),
                 'nvn_vk.h':resident.VULKAN_STUB+'\nnamespace nx::nvn { void frame_wait_all(); }\n',
                 'platform.h':'#pragma once\nnamespace nx::plat { uint64_t monotonic_ns(); }\n',
                 'nvn_writeback.h':(self.n/'nvn_writeback.h').read_text()}
        for name in ['win_page_generations.h','win_write_watch.h']:
            headers[name]=(self.source/'runtime/src'/name).read_text()
        exe=self.compile(ENV_LOOKUPS,headers,flags=['NX_TEST_WINDOWS=1'])
        for value,arg in [('0','uncached'),('1','cached')]:self.run_fixture(exe,[arg],{'NX_REPLAY_ENV':value})

    def test_production_dynamic_state_filter_and_resets(self):
        draw=(self.n/'nvn_draw.cpp').read_text()
        begin=draw.index('struct Bound {'); end=draw.index('} g_bound;',begin)+len('} g_bound;')
        code=PREAMBLE+DYNAMIC.replace('@BOUND@',draw[begin:end]).replace('@RASTER@',
            function((self.n/'nvn_raster.cpp').read_text(),'void raster_dynamic(')).replace('@DYNAMIC@',
            function(draw,'void set_dynamic('))
        exe=self.compile(code,self.headers(),flags=['NX_TEST_WINDOWS=1'],
            includes=[os.environ.get('NVN_VULKAN_INCLUDE','/opt/homebrew/include')])
        for value,arg in [('0','off'),('1','on')]:self.run_fixture(exe,[arg],{'NX_REPLAY_DYNAMIC':value})

    def test_changed_translation_units_compile(self):
        if os.name=='nt':self.skipTest('full native production build is recorded separately on Windows')
        for name in ['nvn_cmd.cpp','nvn_draw.cpp','nvn_draw_state.cpp','nvn_pipeline.cpp','nvn_raster.cpp']:
            r=subprocess.run(['clang++','-std=c++20','-DNX_ASTRAL_STRICT=1','-fsyntax-only',
                '-I'+str(self.source/'runtime/src'),'-I'+str(self.source/'runtime/include'),
                '-I'+os.environ.get('NVN_VULKAN_INCLUDE','/opt/homebrew/include'),str(self.n/name)],text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr)
        print('PASS full Windows series and five production translation units')


if __name__=='__main__':unittest.main()
