"""Actual patched Apple arm64 adapter, assembly, CPU and loader; original fixtures."""
import hashlib
import io
import tarfile
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import unittest
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime

HARNESS = r'''
#include <nx/runtime.h>
#include "kernel.h"
#include "platform.h"
#include <cassert>
#include <fstream>
#include <vector>
#include <stdexcept>
#include <thread>
#include <barrier>
#include <mutex>
#include <sys/wait.h>
#include <unistd.h>
struct ThreadExit {};
namespace nx {
thread_local KThread owner;
KThread* self_thread() { return &owner; }
std::vector<VmInfo> regions;
std::mutex regions_lock;
thread_local std::string last_log;
bool commit(uint64_t,uint64_t) { return true; }
void vm_set(uint64_t a,uint64_t n,uint32_t s,uint32_t p) { std::lock_guard lock(regions_lock);regions.push_back({a,n,s,p}); }
VmInfo vm_query(uint64_t p) { std::lock_guard lock(regions_lock);for(auto r:regions) if(p>=r.addr && p-r.addr<r.size) return r;return {}; }
void backtrace(CPU&) {}
namespace plat {
std::string data_root() { return "."; }
void log_line(const char* line) { last_log=line; }
[[noreturn]] void exit_process(int) { throw std::runtime_error("strict failure"); }
[[noreturn]] void exit_thread() { throw ThreadExit{}; }
}
}
#include "loader.cpp"
#include "hle_fiber.cpp"
using namespace nx;
uint64_t ptr(const void* p) { return reinterpret_cast<uint64_t>(p); }
alignas(16) thread_local unsigned char root_stack[8192], a_stack[8192], b_stack[8192];
alignas(16) thread_local unsigned char a_obj[96], b_obj[96];
alignas(4096) unsigned char module_memory[4096];
alignas(16) thread_local uint64_t root_slot;
thread_local std::vector<int> events;
uint64_t dispatch_target;
thread_local uint64_t tls=712, ro=913, cleanup_pointer=0x13579;
thread_local uint64_t sentinel_bias=0;
thread_local uintptr_t local_a,local_b;
thread_local int finalizers=0, callbacks=0;
thread_local bool exit_case=false;
void original_finalizer(CPU& c) {
 assert(ld<uint8_t>(c.x[0]+32)==3 && callbacks==2);
 ++finalizers;st<uint8_t>(c.x[0]+32,0);
}
void old_dispatch(CPU&) { assert(!"original dispatcher selected"); }
void fill(CPU& c,uint64_t n) {
 n+=sentinel_bias;
 for(int i=19;i<=30;++i)c.x[i]=n+i;
 for(int i=8;i<=15;++i){c.v[i].u64[0]=n+3*i;c.v[i].u64[1]=n+5*i;}
}
void check(CPU& c,uint64_t n) {
 n+=sentinel_bias;
 for(int i=19;i<=30;++i)assert(c.x[i]==n+uint64_t(i));
 for(int i=8;i<=15;++i){assert(c.v[i].u64[0]==n+3*i);assert(c.v[i].u64[1]==n+5*i);}
 assert(c.tpidr==tls && c.tpidrro==ro && self_thread()==&owner);
}
void transfer(CPU& c,uint64_t from,uint64_t to) {
 if(from!=ptr(&root_slot)){assert(ld<uint8_t>(from-80+32)==2);st<uint8_t>(from-80+32,1);}
 // A completed or finalized object cannot be made runnable by the fixture.
 if(to!=ptr(&root_slot) && ld<uint8_t>(to-80+32)==1)st<uint8_t>(to-80+32,2);
 c.x[0]=from;c.x[1]=to;call(c,dispatch_target);
}
void nested(CPU& c,uint64_t from,uint64_t to,int depth) {
 volatile int local=170+depth;
 register double host_value asm("d8")=37.25+depth;
 asm volatile("" : "+w"(host_value));
 if(depth)nested(c,from,to,depth-1);else transfer(c,from,to);
 asm volatile("" : "+w"(host_value));
 assert(local==170+depth && host_value==37.25+depth);
}
void b_entry(CPU& c) {
 volatile int local=29;local_b=ptr((const void*)&local);assert(local_b!=local_a);
 for(int i=0;i<2;++i){events.push_back(20+i);fill(c,200+i);nested(c,ptr(b_obj)+80,ptr(a_obj)+80,3);check(c,200+i);assert(local==29);}
 events.push_back(22); // Return to the trampoline, with its host frame still live.
}
void a_entry(CPU& c) {
 volatile int local=17;local_a=ptr((const void*)&local);
 assert(c.x[19]==0); // Legal initially unspecified callee register; source cleanup must wait.
 for(int i=20;i<30;++i)assert(c.x[i]==sentinel_bias+7000+uint64_t(i));
 for(int i=8;i<=15;++i){assert(c.v[i].u64[0]==sentinel_bias+9000+uint64_t(i));assert(c.v[i].u64[1]==sentinel_bias+11000+uint64_t(i));}
 assert(cleanup_pointer==0x13579 && hle_current_name()==nullptr);
 if(exit_case){owner.exited=true;fiber_retire_thread();assert(false);}
 for(int i=0;i<2;++i){events.push_back(10+2*i);fill(c,100+i);nested(c,ptr(a_obj)+80,ptr(b_obj)+80,4);check(c,100+i);assert(local==17);
  events.push_back(11+2*i);nested(c,ptr(a_obj)+80,ptr(&root_slot),2);check(c,100+i);}
 events.push_back(14);
}
// Original synthetic guest trampoline: completion is reachable only AFTER the
// callback returns. The production adapter keeps SDK lifecycle writes guest-owned.
void trampoline(CPU& c,uint64_t callback,uint64_t object,uint64_t next) {
 assert(c.x[0]==object && ld<uint8_t>(object+32)==2);
 volatile uint64_t local=object;
 call(c,callback);
 assert(local==object && state.active->object==object);
 assert(ld<uint8_t>(object+32)==2);
 ++callbacks;st<uint8_t>(object+32,3);
 if(next!=ptr(&root_slot)){assert(ld<uint8_t>(next-80+32)==1);st<uint8_t>(next-80+32,2);}
 c.x[0]=object+80;c.x[1]=next;call(c,dispatch_target);
 assert(!"completed callback resumed");
}
void a_trampoline(CPU& c) {trampoline(c,ptr(module_memory)+20,ptr(a_obj),ptr(b_obj)+80);}
void b_trampoline(CPU& c) {trampoline(c,ptr(module_memory)+24,ptr(b_obj),ptr(&root_slot));}
void init_object(unsigned char* obj,unsigned char* stack,uint64_t entry) {
 std::memset(obj,0,96);auto p=ptr(stack)+8192-frame_bytes;
 st<uint8_t>(ptr(obj)+32,2);st<uint64_t>(ptr(obj)+64,ptr(stack));st<uint64_t>(ptr(obj)+72,8192);st<uint64_t>(ptr(obj)+80,p);
 st<uint64_t>(p,ptr(obj));st<uint64_t>(p+96,entry);
 for(int i=20;i<30;++i)st<uint64_t>(p+8*(i-18),sentinel_bias+7000+i);
 for(int i=8;i<=15;++i){V128 v{};v.u64[0]=sentinel_bias+9000+i;v.u64[1]=sentinel_bias+11000+i;st<V128>(p+112+16*(i-8),v);}
}
void setup_flow() {
 for(auto p:{root_stack,a_stack,b_stack})vm_set(ptr(p),8192,kMemStack,3);
 for(auto p:{a_obj,b_obj})vm_set(ptr(p),96,kMemHeap,3);
 vm_set(ptr(&root_slot),8,kMemHeap,3);
 init_object(a_obj,a_stack,ptr(module_memory)+12);init_object(b_obj,b_stack,ptr(module_memory)+16);
 auto& c=owner.ctx;c.tpidr=tls;c.tpidrro=ro;c.x[31]=ptr(root_stack)+8192;
}
void setup(const std::string& dir) {
 static Symbol syms[]={{dispatch_name,4,4,2,1,0},{finalize_name,8,4,2,1,0}};
 static FuncEntry funcs[]={{4,old_dispatch},{8,original_finalizer},{12,a_trampoline},{16,b_trampoline},{20,a_entry},{24,b_entry}};
 static Reloc relocs[]={{256,R_AARCH64_JUMP_SLOT,0,0},{264,R_AARCH64_GLOB_DAT,0,0},{272,R_AARCH64_ABS64,1,0}};
 static ModuleInfo m{"synthetic",ptr(module_memory),0,128,128,128,256,3840,4096,0,funcs,6,relocs,3,syms,2,nullptr,0,nullptr,0};
 std::ofstream f(dir+"/synthetic.bin",std::ios::binary);f.write((char*)module_memory,4096);f.close();
 const ModuleInfo* mods[]={&m};load_modules(mods,1,dir);
 dispatch_target=ld<uint64_t>(m.base+256);assert(dispatch_target==hle_address(dispatch_name));assert(ld<uint64_t>(m.base+264)==dispatch_target);
 assert(find_symbol(dispatch_name)==m.base+4);assert(ld<uint64_t>(m.base+272)==hle_address(finalize_name));
 setup_flow();
}
template<class F> void rejected(F f) {
 const char* previous=hle_current_name();bool failed=false;
 try{f();}catch(const std::runtime_error&){failed=true;}
 assert(failed);
 // Production fatal exits the process. The fixture's throwing exit shim lets
 // independent negative probes continue; reset only its diagnostic bookkeeping.
 fiber_exchange_hle_name(previous);
}
void outer(CPU& c) {
 assert(std::string(hle_current_name())=="synthetic.outer");
 transfer(c,ptr(&root_slot),ptr(a_obj)+80);
 assert(std::string(hle_current_name())=="synthetic.outer");
}
NX_HLE("synthetic.outer",outer);
void start() {
 auto& c=owner.ctx;fill(c,300);c.x[19]=ptr(&cleanup_pointer);
 call(c,hle_address("synthetic.outer"));
 assert(c.x[19]==ptr(&cleanup_pointer));assert(hle_current_name()==nullptr);
}
void finish_flow() {
 assert(events==std::vector<int>({10,20,11,30,12,21,13,31,14,22,32}));assert(callbacks==2);
 assert(state.contexts.size()==2 && state.active==&state.root);
 for(auto obj:{a_obj,b_obj}) {
  assert(ld<uint8_t>(ptr(obj)+32)==3 && state.contexts.at(ptr(obj)+80)->suspended);
  // Completed contexts reject re-entry before the legitimate finalizer releases them.
  rejected([&]{transfer(owner.ctx,ptr(&root_slot),ptr(obj)+80);});
  assert(last_log.find("destination lifecycle")!=std::string::npos);
  owner.ctx.x[0]=ptr(obj);call(owner.ctx,hle_address(finalize_name));
  assert(ld<uint8_t>(ptr(obj)+32)==0);
 }
 assert(finalizers==2 && state.contexts.empty());
}
void independent_threads() {
 struct Snapshot {uint64_t source,a,b,stack,a_stack,b_stack,tls,ro;uintptr_t local_a,local_b;CPU* cpu;ThreadState* state;};
 Snapshot snapshots[2]{};
 std::barrier together(2);
 auto run=[&](int id) {
  tls=1000+id;ro=2000+id;sentinel_bias=10000*(id+1);setup_flow();
  start();events.push_back(30);
  snapshots[id]={ptr(&root_slot),ptr(a_obj)+80,ptr(b_obj)+80,ptr(root_stack),ptr(a_stack),ptr(b_stack),tls,ro,local_a,local_b,&owner.ctx,&state};
  together.arrive_and_wait();
  const auto& other=snapshots[1-id];
  assert(other.source!=ptr(&root_slot) && other.stack!=ptr(root_stack) && other.cpu!=&owner.ctx);
  assert(other.a!=ptr(a_obj)+80 && other.b!=ptr(b_obj)+80 && other.state!=&state);
  assert(other.a_stack!=ptr(a_stack) && other.b_stack!=ptr(b_stack));
  assert(other.tls!=tls && other.ro!=ro && other.local_a!=local_a && other.local_b!=local_b);
  {std::lock_guard lock(owners_lock);assert(owners.at(ptr(&root_slot))==&state);assert(owners.at(other.a)==other.state);}
  assert(state.active==&state.root && owner.ctx.x[31]==ptr(root_stack)+8192);
  // Valid, already-owned LOCAL source. Do not write the foreign destination's lifecycle.
  rejected([&]{owner.ctx.x[0]=ptr(&root_slot);owner.ctx.x[1]=other.a;call(owner.ctx,dispatch_target);});
  assert(last_log.find("fiber: foreign context")!=std::string::npos);
  assert(state.active==&state.root && state.contexts.size()==2);
  together.arrive_and_wait(); // Neither owner resumes while its peer inspects it.
  for(int i=1;i<3;++i){start();events.push_back(30+i);}
  finish_flow();fiber_retire_thread();assert(!state.cpu && state.contexts.empty());
 };
 std::thread first(run,0),second(run,1);first.join();second.join();assert(owners.empty());
}
int main(int argc,char** argv) {
 assert(argc==3);std::string mode=argv[1];setup(argv[2]);auto& c=owner.ctx;
 if(mode=="ordered") {
  for(int i=0;i<3;++i){start();events.push_back(30+i);}
  // Both inaccessible guard pages belong to the actual production allocation.
  auto* d=state.contexts.begin()->second.get();
  for(size_t offset:{size_t(0),d->allocation_bytes-1}) {pid_t p=fork();assert(p>=0);if(!p){*(volatile char*)((char*)d->allocation+offset)=1;_exit(0);}int status;waitpid(p,&status,0);assert(WIFSIGNALED(status));}
  finish_flow();
  rejected([&]{c.x[0]=ptr(a_obj);call(c,hle_address(finalize_name));});
  rejected([&]{transfer(c,ptr(&root_slot),ptr(a_obj)+80);});
  fiber_retire_thread();assert(owners.empty() && !state.cpu);
 } else if(mode=="exit") {
  exit_case=true;bool exited=false;try{start();}catch(ThreadExit&){exited=true;}
  assert(exited && owners.empty() && state.contexts.empty() && !state.cpu);
 } else if(mode=="foreign") {
  independent_threads();
 } else if(mode=="foreign_source") {
  start();auto foreign_source=ptr(&root_slot);
  std::thread t([&]{
   tls=3000;ro=4000;setup_flow();
   rejected([&]{owner.ctx.x[0]=foreign_source;owner.ctx.x[1]=ptr(a_obj)+80;call(owner.ctx,dispatch_target);});
   assert(last_log.find("fiber: foreign context")!=std::string::npos && state.contexts.empty());
   fiber_retire_thread();
  });t.join();
  {std::lock_guard lock(owners_lock);assert(owners.at(foreign_source)==&state);}
  fiber_retire_thread();assert(owners.empty());
 } else if(mode=="stale") {
  start();st<uint64_t>(ld<uint64_t>(ptr(a_obj)+80)+96,999);rejected([&]{start();});fiber_retire_thread();
 } else if(mode=="tls") {
  start();c.tpidr++;rejected([&]{start();});c.tpidr--;fiber_retire_thread();
 } else if(mode=="invalid") {
  for(uint64_t bad:{uint64_t(0),ptr(a_obj)+81,UINT64_MAX-7}){rejected([&]{c.x[0]=ptr(&root_slot);c.x[1]=bad;call(c,dispatch_target);});}
  auto p=ld<uint64_t>(ptr(a_obj)+80);st<uint64_t>(ptr(a_obj)+80,p+1);rejected([&]{start();});st<uint64_t>(ptr(a_obj)+80,p);
  st<uint8_t>(ptr(a_obj)+32,0);rejected([&]{c.x[0]=ptr(&root_slot);c.x[1]=ptr(a_obj)+80;call(c,dispatch_target);});
  st<uint8_t>(ptr(a_obj)+32,2);
  for(auto& r:regions)if(r.addr==ptr(a_stack))r.perm=1;
  rejected([&]{start();});
  fiber_retire_thread();
 } else assert(false);
 std::puts(("PASS "+mode).c_str());
}
'''

class FiberContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise AssertionError('Apple arm64 production backend required; no skip acceptance')
        common = Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip()).resolve()
        reference = Path(os.environ.get('FIBER_REFERENCE',str(common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        cls.out=ROOT / '.local/fiber-impl-078-fix1' / ('verify-'+uuid.uuid4().hex)
        cls.out.mkdir(parents=True)
        cls.source=cls.out/'source'
        patches=[ROOT/'runtime/patches'/n for n in ('apple-memory.patch','astral-bootstrap.patch','astral-control-import.patch','astral-fiber.patch')]
        # Extract only public production inputs at the immutable pin; avoid cloning
        # unrelated media and retain a real Git patch application boundary.
        selected=['CMakeLists.txt','runtime/src/loader.cpp','runtime/src/kernel.cpp','runtime/src/kernel.h',
                  'runtime/src/platform.h','runtime/include/nx/cpu.h','runtime/include/nx/runtime.h','runtime/include/nx/module.h']
        data=subprocess.check_output(['git','-C',str(reference),'archive',runtime.PIN,*selected],timeout=60)
        cls.source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(data)) as archive: archive.extractall(cls.source,filter='data')
        subprocess.run(['git','init','-q',str(cls.source)],check=True,timeout=15)
        includes=['--include='+n for n in selected+['runtime/src/hle_fiber.cpp','runtime/src/fiber_context_mac.S']]
        for patch in patches:
            subprocess.run(['git','-C',str(cls.source),'apply',*includes,str(patch)],check=True,capture_output=True,timeout=30)
        fixture=cls.out/'fixture';fixture.mkdir();(fixture/'main.cpp').write_text(HARNESS)
        cls.binary=fixture/'test'
        cmd=[shutil.which('c++'),'-std=c++20','-O2','-pthread','-DNX_ASTRAL_STRICT=1',
             '-I',str(cls.source/'runtime/include'),'-I',str(cls.source/'runtime/src'),str(fixture/'main.cpp'),
             str(cls.source/'runtime/src/fiber_context_mac.S'),'-o',str(cls.binary)]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
        (cls.out/'compile.log').write_text(r.stdout+r.stderr)
        if r.returncode:raise AssertionError(r.stdout+r.stderr)
        cls.receipt={'patches':{p.name:runtime.sha(p) for p in patches},'compile':cmd,'compile_exit':r.returncode,'binary_sha256':runtime.sha(cls.binary),'cases':[]}
    def case(self,name):
        r=subprocess.run([str(self.binary),name,str(self.out)],cwd=self.out,capture_output=True,text=True,timeout=15)
        self.receipt['cases'].append({'name':name,'exit_code':r.returncode,'output':r.stdout+r.stderr})
        (self.out/'receipt.json').write_text(json.dumps(self.receipt,indent=2))
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_ordered_resumes_callback_zero_register_guards_finalize(self):self.case('ordered')
    def test_thread_retirement_from_active_fiber(self):self.case('exit')
    def test_two_thread_flows_and_foreign_destination_rejected(self):self.case('foreign')
    def test_foreign_source_rejected(self):self.case('foreign_source')
    def test_stale_continuation_rejected(self):self.case('stale')
    def test_tls_owner_unchanged(self):self.case('tls')
    def test_invalid_ranges_alignment_lifecycle_permissions(self):self.case('invalid')

if __name__=='__main__':unittest.main()
