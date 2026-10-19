"""Compile the actual ordered VI HLE translation unit and loader registry.

Synthetic memory/window adapters only; no game, network, provider, or GPU launch.
"""
import datetime
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

PATCHES = ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
           'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch',
           'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch', 'astral-hid.patch',
           'astral-controller-support.patch', 'astral-vi.patch')

FIXTURE = r'''
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include "kernel.h"
#include "platform.h"
namespace nx {
struct Region {uint64_t a,n;uint32_t perm;}; std::vector<Region> regions;
void region(void* p,size_t n,uint32_t perm=3) {regions.push_back({uint64_t(p),n,perm});}
VmInfo vm_query(uint64_t a) {
 for(auto r:regions) if(a>=r.a && a-r.a<r.n) return {r.a,r.n,kMemHeap,r.perm};
 return {a,4096,kMemFree,0};
}
bool commit(uint64_t,uint64_t) {return true;}
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) {}
void backtrace(CPU&) {}
void event_signal(const std::shared_ptr<EventState>&) {}
uint32_t handle_add(std::shared_ptr<KObject>) {return 1;}
namespace nvn { /* ACTUAL_PRESENT_POLICY */ }
namespace plat {
unsigned creates=0,releases=0;bool available=true;
void* create_window() {++creates;return available?reinterpret_cast<void*>(0x12345678):nullptr;}
void release_window(void*) {++releases;}
uint64_t monotonic_ns() {return 0;}
void sleep_ns(int64_t) {}
void set_thread_name(const char*) {}
std::string data_root() {return ".";}
void log_line(const char*) {}
[[noreturn]] void exit_process(int) {throw std::runtime_error("strict fatal");}
}
}
#include "loader.cpp"
#include "hle_vi.cpp"
using namespace nx;
uint64_t invoke(const char* suffix,uint64_t a=0,uint64_t b=0) {
 auto name=std::string("_ZN2nn2vi")+suffix;assert(hle_lookup(name.c_str()));
 CPU c{};c.x[0]=a;c.x[1]=b;c.x[2]=UINT64_MAX;
 call(c,hle_address(name.c_str()));return c.x[0];
}
void bad(auto f) {bool caught=false;try {f();} catch(const std::runtime_error&) {caught=true;} assert(caught);}
const char *open="18OpenDefaultDisplayEPPNS0_7DisplayE",*create="11CreateLayerEPPNS0_5LayerEPNS0_7DisplayE",
 *scale="19SetLayerScalingModeEPNS0_5LayerENS0_11ScalingModeE",*native="15GetNativeWindowEPPvPNS0_5LayerE",
 *destroy="12DestroyLayerEPNS0_5LayerE",*close_display="12CloseDisplayEPNS0_7DisplayE";
int main(int argc, char** argv) {
 uint64_t out[3]={0xa5,0xa5,0xa5};region(out,sizeof out);auto p=uint64_t(out+1);
 bad([&]{invoke(open,p);});invoke("10InitializeEv");
 for(auto a:{uint64_t(0),UINT64_MAX-3,uint64_t(out)+sizeof(out)-4}) bad([&]{invoke(open,a);});
 uint64_t readonly=0;region(&readonly,8,1);bad([&]{invoke(open,uint64_t(&readonly));});
 uint8_t split[8]{};region(split,4,3);region(split+4,4,1);bad([&]{invoke(open,uint64_t(split));});
 alignas(uint64_t) uint8_t writable_split[8]{};
 region(writable_split,4,3);region(writable_split+4,4,3);
 assert(invoke(open,uint64_t(writable_split))==0);uint64_t split_display;
 std::memcpy(&split_display,writable_split,8);invoke(close_display,split_display);
 assert(invoke(open,p)==0);auto display=out[1];assert(display && out[0]==0xa5 && out[2]==0xa5);
 bad([&]{invoke(open,p);});
 for(auto d:{uint64_t(0),display+1,uint64_t(0x12345)}) bad([&]{invoke(create,p,d);});
 bad([&]{invoke(scale,display,2);});
 auto before=plat::creates;
 for(auto a:{uint64_t(0),UINT64_MAX-3,uint64_t(out)+sizeof(out)-4,uint64_t(&readonly),uint64_t(split)})
  bad([&]{invoke(create,a,display);});
 assert(plat::creates==before);
 plat::available=false;out[1]=0xa5;assert(invoke(create,p,display)==0x272 && out[1]==0xa5);
 plat::available=true;assert(invoke(create,p,display)==0);auto layer=out[1];assert(layer!=display);
 assert(out[0]==0xa5 && out[2]==0xa5 && plat::releases==1);
 if(argc>1) {
  const bool expected=argv[1][0]=='1';assert(nvn::present_pass_wanted()==expected);
  assert(invoke(scale,layer,2)==(expected?0x272:0));
  std::cout<<"PASS actual VI registry/dispatch and production presentation policy "<<expected<<"\n";return 0;
 }
 bad([&]{invoke(create,p,display);});
 for(auto l:{uint64_t(0),display,layer+1,uint64_t(0x12345678)}) {
  bad([&]{invoke(scale,l,2);});bad([&]{invoke(native,p,l);});
 }
 // API-level dispatch must consume the opaque token, never execute guest SDK object code.
 invoke("10InitializeEv");assert(invoke(scale,layer,2)==0);
 bad([&]{invoke(close_display,layer);});
 assert(invoke(scale,layer,0xabcdef0000000002ULL)==0); // enum ABI reads w1
 for(auto mode:{uint64_t(5),uint64_t(6),uint64_t(UINT32_MAX)}) bad([&]{invoke(scale,layer,mode);});
 for(unsigned mode: {0u,1u,3u,4u}) assert(invoke(scale,layer,mode)==0x272);
 before=plat::creates;assert(invoke(scale,layer,2)==0 && plat::creates==before);
 bad([&]{invoke(native,0,layer);});bad([&]{invoke(native,UINT64_MAX-1,layer);});
 bad([&]{invoke(native,uint64_t(out)+sizeof(out)-4,layer);});
 bad([&]{invoke(native,uint64_t(&readonly),layer);});
 out[1]=0xa5;plat::available=false;assert(invoke(native,p,layer)==0x272 && out[1]==0xa5);
 plat::available=true;assert(invoke(native,p,layer)==0 && out[1]==0x12345678 && out[0]==0xa5 && out[2]==0xa5);
 invoke(destroy,layer);bad([&]{invoke(scale,layer,2);});bad([&]{invoke(destroy,layer);});
 assert(invoke(create,p,display)==0);auto second=out[1];assert(second!=layer);
 invoke(close_display,display);bad([&]{invoke(scale,second,2);});bad([&]{invoke(create,p,display);});bad([&]{invoke(close_display,display);});
 assert(invoke(open,p)==0);auto nextdisplay=out[1];assert(nextdisplay!=display);
 assert(invoke(create,p,nextdisplay)==0);assert(out[1]!=second && invoke(scale,out[1],2)==0);
 auto final_layer=out[1];
 // Two Initialize calls above require two releases. Finalize at zero is benign.
 invoke("8FinalizeEv");assert(invoke(scale,final_layer,2)==0);
 invoke("8FinalizeEv");bad([&]{invoke(scale,final_layer,2);});
 bad([&]{invoke(open,p);});invoke("8FinalizeEv");invoke("10InitializeEv");
 bad([&]{invoke(create,p,nextdisplay);});
 assert(invoke(open,p)==0);auto reopened=out[1];assert(reopened!=nextdisplay);
 assert(invoke(create,p,reopened)==0);assert(out[1]!=final_layer);
 bad([&]{invoke(scale,final_layer,2);});assert(invoke(scale,out[1],2)==0);
 invoke("8FinalizeEv");
 // Missing unrelated capabilities remain unregistered/strict.
 assert(!hle_lookup("_ZN2nn2vi13SetLayerAlphaEPNS0_5LayerEf"));
 bad([&]{CPU c{};call(c,0x12345);});
 std::cout<<"PASS actual VI registry/dispatch: FitToLayer blit capability, incompatible presentation errors, enum ABI, invalid/stale/foreign identities, output extents/canaries, failed host allocation atomicity, close/destroy/finalize reference retirement and reopen, unrelated strict dispatch\n";
}
'''


class ViRuntimeTests(unittest.TestCase):
    def test_actual_ordered_hle(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('VI_REFERENCE', str(common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'clean pinned runtime required via VI_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/vi-core-068' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / n for n in PATCHES]
        fingerprint = runtime.prepare_source(reference, output / 'source', patches)
        fixture = output / 'fixture.cpp'
        presenter = output / 'source/runtime/src/nvn/nvn_present.cpp'
        # Compile these complete production policy functions too, without pulling
        # unrelated Vulkan rendering into this CPU-only dispatch fixture.
        def function(name):
            text = presenter.read_text()
            start = text.index('bool ' + name + '() {')
            pos = text.index('{', start)
            depth = 1
            end = pos + 1
            while depth:
                depth += (text[end] == '{') - (text[end] == '}')
                end += 1
            return text[start:end]
        policy = function('fsr_on') + '\n' + function('present_pass_wanted')
        fixture.write_text(FIXTURE.replace('/* ACTUAL_PRESENT_POLICY */', policy))
        source = output / 'source'
        argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1',
                '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), str(fixture), '-o', str(output / 'test')]
        build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        results = []
        env = {k: v for k, v in os.environ.items() if k not in ('NX_PRESENT_PASS', 'NX_FSR')}
        for args, settings in (([], {}), (['1'], {'NX_PRESENT_PASS': '1'}),
                               (['1'], {'NX_FSR': '1'}),
                               (['1'], {'NX_PRESENT_PASS': '0', 'NX_FSR': '1'}),
                               (['0'], {'NX_PRESENT_PASS': '0', 'NX_FSR': '0'})):
            result = subprocess.run([str(output / 'test'), *args], cwd=output,
                                    env={**env, **settings}, capture_output=True, text=True, timeout=10)
            (output / ('result-' + str(len(results)) + '.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS actual VI registry/dispatch', result.stdout)
            results.append({'settings': settings, 'exit_code': result.returncode, 'output': result.stdout})
            print(result.stdout, end='')
        receipt = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source': fingerprint,
                   'fixture_sha256': runtime.sha(fixture), 'test_sha256': runtime.sha(Path(__file__)),
                   'compiler_sha256': runtime.sha(Path(compiler).resolve()),
                   'compiler_version': subprocess.check_output([compiler, '--version'], text=True), 'compile': argv, 'binary_sha256': runtime.sha(output / 'test'),
                   'results': results, 'presenter_sha256': runtime.sha(presenter),
                   'limits': 'Synthetic host window/VM; actual production presentation query; no GPU/frame/platform acceptance.'}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('private receipt:', output / 'receipt.json')


if __name__ == '__main__':
    unittest.main()
