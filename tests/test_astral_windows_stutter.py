"""Execute production hitch trace and pacing helpers with original synthetic events.

No game, GPU, VM, network or credentials are used. Optional series integration
reads an existing pinned public runtime clone and builds in temporary storage.
"""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prepare_runtime
PATCH=ROOT/'runtime/patches/astral-windows-stutter.patch'


def added(name):
    body=PATCH.read_text().split('+++ b/runtime/src/'+name+'\n',1)[1].split('\ndiff --git ',1)[0]
    return '\n'.join(x[1:] for x in body.splitlines() if x.startswith('+'))+'\n'


STUB=r'''
#pragma once
#include <cstdint>
#include <cstdio>
#include <chrono>
#include <thread>
#include <string>
namespace nx::plat {
inline uint64_t monotonic_ns() { return std::chrono::steady_clock::now().time_since_epoch().count(); }
inline int64_t current_thread_id() { return std::hash<std::thread::id>{}(std::this_thread::get_id()); }
inline FILE* fopen_utf8(const std::string& p,const char* mode) { return std::fopen(p.c_str(),mode); }
}
'''

FIXTURE=r'''
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <thread>
#include <vector>
#include <cassert>
#include <string>
#include <utility>
#define _WIN32 1
#define NX_ASTRAL_STRICT 1
#include "win_stutter.h"
int main(int argc,char** argv) {
 using namespace nx::stutter;
 if(argc>1 && std::string(argv[1])=="pacing") { std::printf("%d",pace_before_present());return 0; }
 if(argc==1) { assert(!trace()); mark(Frame); return 0; }
 assert(trace());
 // Test the exact bounded producer, including explicit loss accounting, without writer races.
 Trace bounded(nullptr); bounded.pending.reserve(Trace::limit);
 for(size_t k=0;k<Trace::limit+7;++k)bounded.append({1,2,3,4,5});
 assert(bounded.pending.size()==Trace::limit && bounded.lost==7);
 std::vector<std::thread> threads;
 for(unsigned k=0;k<4;++k)threads.emplace_back([k] {
   for(unsigned j=0;j<1000;++j) {
     Span outer(Texture,k);
     auto answer=call(Astc,[] { return 42; },j); assert(answer==42);
   }
 });
 for(auto& t:threads)t.join();
 call(Upload,[]{});mark(Frame,123);
 std::this_thread::sleep_for(std::chrono::milliseconds(350));
 assert(!trace()->lost);
}
'''


SINK_FIXTURE=r'''
#include <cassert>
#include <atomic>
#include <chrono>
#include <future>
#include <mutex>
#include <string>
#include <vector>
#include "win_log_sink.h"
std::mutex output_lock;
std::vector<std::string> output;
std::promise<void> entered,release;
auto ready=release.get_future().share();
void blocked(const char* line) {
 if(std::string(line)=="first") { entered.set_value();ready.wait(); }
 std::lock_guard guard(output_lock);output.emplace_back(line);
}
void collect(const char* line) {
 std::lock_guard guard(output_lock);output.emplace_back(line);
}
int main() {
 {
  nx::winlog::Sink sink(blocked,2);
  sink.submit("first"); entered.get_future().wait();
  std::string owned="second";sink.submit(owned);owned="overwritten caller buffer";
  sink.submit("third");
  std::promise<void> attempting;
  auto producer=std::async(std::launch::async,[&] { attempting.set_value();sink.submit("fourth"); });
  attempting.get_future().wait();
  assert(producer.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout);
  release.set_value();producer.get();sink.flush();
  assert((output==std::vector<std::string>{"first","second","third","fourth"}));
 }
 output.clear();
 {
  nx::winlog::Sink sink(collect,7);std::vector<std::thread> producers;
  for(int t=0;t<4;++t)producers.emplace_back([&,t] {
   for(int n=0;n<500;++n)sink.submit(std::to_string(t)+":"+std::to_string(n));
  });
  for(auto& p:producers)p.join();
  // Destructor must drain even without an explicit flush.
 }
 assert(output.size()==2000);
 int next[4]{};
 for(auto& line:output) {int t=line[0]-'0';assert(t>=0 && t<4);assert(std::stoi(line.substr(2))==next[t]++);}
 for(auto n:next)assert(n==500);
}
'''


CACHE_FIXTURE=r'''
#include <cassert>
#include <cstdio>
#include "win_astc_cache.h"
using namespace nx::astc_cache;
bool digest(std::initializer_list<Part> parts,Digest& out) {
 uint64_t h[4]={14695981039346656037ull,17,314159,987654321};
 for(auto [ptr,n]:parts)for(size_t k=0;k<n;++k)for(int j=0;j<4;++j)h[j]=(h[j]^static_cast<const uint8_t*>(ptr)[k])*(1099511628211ull+2*j);
 for(int j=0;j<4;++j)put64(out.data()+8*j,h[j]);return true;
}
int main() {
 std::filesystem::path root=std::filesystem::u8path("cache-\xc3\xa9");Cache cache(root,digest,"build-A");
 std::vector<uint8_t> input(257),bytes(4096);for(size_t n=0;n<bytes.size();++n)bytes[n]=uint8_t(n*13+7);
 Digest key{};assert(cache.key("dimensions:A",input,key));
 assert(cache.save(key,bytes,3));
 auto check=[&] {std::vector<uint8_t> out(bytes.size());uint64_t bad=0;assert(cache.load(key,out,bad));assert(out==bytes && bad==3);};check();
 auto rejects=[&] {std::vector<uint8_t> out(bytes.size(),0);uint64_t bad=0;assert(!cache.load(key,out,bad));assert(out==std::vector<uint8_t>(bytes.size()) && bad==0);};
 Cache warm(root,digest,"build-A");std::vector<uint8_t> out(bytes.size());uint64_t bad=0;assert(warm.load(key,out,bad) && out==bytes && bad==3);
 for(auto metadata:{"dimensions:B","format:B","layers:B","srgb:B","layout:B"}) {
  Digest other{};assert(cache.key(metadata,input,other) && other!=key);out.assign(bytes.size(),0);assert(!cache.load(other,out,bad));
 }
 input[7]^=1;Digest other{};assert(cache.key("dimensions:A",input,other) && other!=key);
 input[7]^=1;Cache rebuilt(root,digest,"build-B");assert(rebuilt.key("dimensions:A",input,other) && other!=key);
 auto path=root/(hex(key)+".bin");
 auto flip=[&](size_t at) {std::fstream file(path,std::ios::in|std::ios::out|std::ios::binary);file.seekg(at);char c=0;file.get(c);file.seekp(at);file.put(c^1);};
 // Prepared entries are owned immutable checked snapshots; a later disk change
 // cannot mutate them, while a new process rejects the corrupted disk entry.
 Cache prepared(root,digest,"build-A",bytes.size());assert(prepared.prepared_bytes()==bytes.size());
 Cache too_small(root,digest,"build-A",bytes.size()-1);assert(too_small.prepared_bytes()==0);
 flip(100);rejects();bool ready=false;out.assign(bytes.size(),0);bad=0;
 assert(prepared.load(key,out,bad,&ready) && ready && out==bytes && bad==3);
 Cache corrupt(root,digest,"build-A",bytes.size());assert(corrupt.prepared_bytes()==0);
 out.assign(bytes.size(),0);bad=0;ready=true;
 assert(!corrupt.load(key,out,bad,&ready) && !ready && out==std::vector<uint8_t>(bytes.size()) && bad==0);
 out.assign(bytes.size()+1,0);assert(!prepared.load(key,out,bad));
 assert(cache.save(key,bytes,3));prepared.prepare(bytes.size()-1);assert(prepared.prepared_bytes()==0);
 for(auto at:{size_t(0),size_t(8),size_t(16),size_t(24),size_t(56),size_t(100)}) {flip(at);rejects();assert(cache.save(key,bytes,3));check();}
 std::filesystem::resize_file(path,100);rejects();assert(cache.save(key,bytes,3));
 {std::ofstream file(path,std::ios::binary|std::ios::app);file.put('x');}rejects();assert(cache.save(key,bytes,3));
 // A failed replacement preserves the previous good entry.
 std::filesystem::create_directory(root/"pending.tmp");assert(!cache.save(key,bytes,4));check();std::filesystem::remove(root/"pending.tmp");
 out.assign(bytes.size()+1,0);assert(!cache.load(key,out,bad));
 std::vector<uint8_t> oversized(Cache::max_payload+1);assert(!cache.save(key,oversized,0));
#ifndef _WIN32
 // No writes through an attacker-controlled leaf or temporary symlink.
 std::ofstream("external").put('z');std::filesystem::create_symlink(std::filesystem::absolute("external"),root/"pending.tmp");
 assert(!cache.save(key,bytes,0));check();std::filesystem::remove(root/"pending.tmp");
 std::filesystem::remove(path);std::filesystem::create_symlink(std::filesystem::absolute("external"),path);
 rejects();assert(!cache.save(key,bytes,0));
#endif
}
'''


STORE_FIXTURE=r'''
#include <cassert>
#include <atomic>
#include <future>
#include <stdexcept>
#include "win_astc_store.h"
using namespace nx::astc_cache;
bool digest(std::initializer_list<Part> parts,Digest& out) {
 uint64_t h=14695981039346656037ull;
 for(auto [p,n]:parts)for(size_t k=0;k<n;++k)h=(h^static_cast<const uint8_t*>(p)[k])*1099511628211ull;
 for(int i=0;i<4;++i)put64(out.data()+i*8,h+i);return true;
}
int main() {
 Cache cache("cache",digest,"build");
 Digest key{},other{};std::vector<uint8_t> input(17,1),bytes(4096,23);
 assert(cache.key("first",input,key));assert(cache.key("second",input,other));
 std::promise<void> entered,release;
 auto allowed=release.get_future().share();
 {
  Store store([&](const Digest& k,const std::vector<uint8_t>& data,uint64_t bad) {
   entered.set_value();allowed.wait();return cache.save(k,data,bad);
  },bytes.size(),1);
  assert(store.submit(key,bytes,7));entered.get_future().wait();
  bytes.assign(bytes.size(),99);key=other; // mutate every caller-owned input
  // In-flight bytes/jobs stay charged. Producer must not block on a busy writer.
  assert(!store.submit(other,bytes,8));
  auto count=store.snapshot();assert(count.queued==1 && count.skipped==1 && count.saved==0);
  std::vector<uint8_t> out(bytes.size());uint64_t invalid=0;
  assert(!cache.load(other,out,invalid));
  release.set_value();store.flush();count=store.snapshot();assert(count.saved==1 && !count.failed);
 }
 assert(cache.key("first",input,key));std::vector<uint8_t> out(bytes.size());uint64_t invalid=0;
 assert(cache.load(key,out,invalid) && out==std::vector<uint8_t>(4096,23) && invalid==7);
 // Exercise byte and job bounds independently, counting the blocked in-flight job.
 for(bool byte_bound:{true,false}) {
  std::promise<void> busy,go;auto proceed=go.get_future().share();
  Store limited([&](const auto&,const auto&,uint64_t) {busy.set_value();proceed.wait();return false;},
                byte_bound ? 4096 : 8192,byte_bound ? 16 : 1);
  assert(limited.submit(key,bytes,9));busy.get_future().wait();
  assert(!limited.submit(other,bytes,9));
  go.set_value();limited.flush();
  const auto c=limited.snapshot();assert(c.queued==1 && c.skipped==1 && c.failed==1);
 }
 // Atomic publications can be read concurrently; every successful read is complete.
 assert(cache.save(key,std::vector<uint8_t>(4096,7),7));
 std::atomic<bool> done=false;std::atomic<unsigned> checked=0;
 std::thread reader([&] { while(!done) {
  std::vector<uint8_t> value(4096);uint64_t bad=0;
  if(cache.load(key,value,bad)) {assert(value==std::vector<uint8_t>(4096,uint8_t(bad)));++checked;}
 }});
 {
  Store store([&](const auto& k,const auto& data,uint64_t bad) {return cache.save(k,data,bad);});
  for(unsigned n=1;n<80;++n) { std::vector<uint8_t> value(4096,uint8_t(n));store.submit(key,value,n); }
 } // Destructor drains all accepted work, including the in-flight job.
 done=true;reader.join();assert(checked>0);
 {
  Store fails([](const auto&,const auto&,uint64_t)->bool {throw std::runtime_error("disk failure");});
  assert(fails.submit(key,bytes,9));fails.flush();auto c=fails.snapshot();assert(c.failed==1 && !c.saved);
  assert(fails.submit(key,bytes,9));fails.flush();assert(fails.snapshot().failed==2);
 }
 {
  Store zero([](const auto&,const auto&,uint64_t) {assert(false);return true;},0,0);
  assert(!zero.submit(key,bytes,9));assert(zero.snapshot().skipped==1);
 }
}
'''


class TraceTests(unittest.TestCase):
    def test_shipped_trace_executes_concurrently_and_is_disabled_by_default(self):
        cxx=os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            (d/'platform.h').write_text(STUB)
            (d/'win_stutter.h').write_text(added('win_stutter.h'))
            (d/'test.cpp').write_text(FIXTURE)
            exe=d/'test'
            p=subprocess.run([cxx,'-std=c++20','-pthread',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            env={k:v for k,v in os.environ.items() if k!='NX_STUTTER_TRACE'}
            p=subprocess.run([str(exe)],env=env,cwd=d,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertFalse((d/'trace.bin').exists())
            # Exercise a genuinely unset environment, as a player's default launch.
            default_env={k:v for k,v in env.items() if k not in ('NX_WIN_PACE_BEFORE','NX_REPLAY_THREAD')}
            p=subprocess.run([str(exe),'pacing'],env=default_env,cwd=d,capture_output=True,text=True)
            self.assertEqual((p.returncode,p.stdout),(0,'0'),p.stderr)
            for setting,replay,expected in [('', '', '0'),('0','','0'),('1','','1'),('11','','0'),('1','1','0'),('1','0','1')]:
                p=subprocess.run([str(exe),'pacing'],env=dict(env,NX_WIN_PACE_BEFORE=setting,NX_REPLAY_THREAD=replay),cwd=d,capture_output=True,text=True)
                self.assertEqual((p.returncode,p.stdout),(0,expected),p.stderr)

            p=subprocess.run([str(exe),'on'],env=dict(env,NX_STUTTER_TRACE=str(d/'trace.bin')),cwd=d,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            raw=(d/'trace.bin').read_bytes()
            self.assertEqual(raw[:8],b'ACST0001')
            self.assertEqual((len(raw)-8)%32,0)
            events=list(struct.iter_unpack('<QQQII',raw[8:]))
            self.assertEqual(len(events),8002)
            self.assertTrue(all(end>=begin>0 and tid for begin,end,arg,tid,kind in events))
            self.assertEqual(sum(k==4 for b,e,a,t,k in events),4000)
            self.assertEqual(sum(k==5 for b,e,a,t,k in events),4000)
            self.assertEqual([(a,k) for b,e,a,t,k in events if k==16],[(123,16)])
            self.assertEqual(len({t for b,e,a,t,k in events if k==4}),4)

    def test_route_changed_word_oracle_uses_production_scalar_and_avx2_merge(self):
        # Reuse the independent randomized/guard-page/changed-block contract suite
        # with the final overlay's diagnostic wrapper around the actual merge.
        from unittest import mock
        import test_astral_windows_perf as perf
        import test_astral_windows_writeback as writeback
        original=writeback.function
        implementation=original('void apply_write_back_full(').replace(
            'void apply_write_back_full(', 'void apply_write_back_full_impl(',1)
        with mock.patch.object(perf,'PATCH',PATCH):
            oracle=perf.function('runtime/src/nvn/nvn_written.cpp','void apply_write_back_full(')
        def composed(signature):
            if signature=='void apply_write_back_full(':return implementation+'\n'+oracle
            return original(signature)
        with mock.patch.object(writeback,'function',composed), \
             mock.patch.dict(os.environ,{'NX_WIN_WRITEBACK_VERIFY':'1'}):
            helper=writeback.WindowsWritebackTest()
            helper.merge(False)
            helper.merge(True)

    def test_route_oracle_detects_unchanged_guest_word_clobber(self):
        from unittest import mock
        import test_astral_windows_perf as perf
        import test_astral_windows_resident as resident
        with mock.patch.object(perf,'PATCH',PATCH):
            oracle=perf.function('runtime/src/nvn/nvn_written.cpp','void apply_write_back_full(')
        code=r'''#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
struct WriteBack { const uint8_t* from; uint8_t* to; uint64_t size;
 std::shared_ptr<std::vector<uint8_t>> before; uint64_t before_offset=0; };
unsigned failures=0; bool inject=false;
void log(const char* text,...) { if(std::strstr(text,"ORACLE_MISMATCH"))++failures; }
void apply_write_back_full_impl(const WriteBack& w) {
 // First emulate the correct sparse update, then deliberately clobber unchanged words.
 std::memcpy(w.to,w.from,inject?w.size:4);
}
@ORACLE@
int main() {
 uint8_t from[16]={1,2,3,4},to[16];std::memset(to,0x6b,sizeof(to));
 auto before=std::make_shared<std::vector<uint8_t>>(16,0);
 WriteBack w{from,to,16,before};apply_write_back_full(w);assert(failures==0);
 inject=true;apply_write_back_full(w);assert(failures==1);
 std::puts("PASS route oracle rejects unchanged-word clobber");
}
'''.replace('@ORACLE@',oracle)
        with mock.patch.dict(os.environ,{'NX_WIN_WRITEBACK_VERIFY':'1'}):
            resident.WindowsResidentTest().compile_run(code)

    def test_console_sink_owns_lines_preserves_order_bounds_and_drains(self):
        cxx=os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'win_log_sink.h').write_text(added('win_log_sink.h'))
            (d/'test.cpp').write_text(SINK_FIXTURE)
            exe=d/'test'
            p=subprocess.run([cxx,'-std=c++20','-pthread',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_decoded_cache_identity_corruption_bounds_and_atomic_failure(self):
        cxx=os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'win_astc_cache.h').write_text(added('win_astc_cache.h'))
            (d/'test.cpp').write_text(CACHE_FIXTURE);exe=d/'test'
            p=subprocess.run([cxx,'-std=c++20',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],cwd=d,capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_decoded_cache_disk_caps_refuse_new_persistence(self):
        cxx=os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        # Use production limits and sparse synthetic files, never game textures.
        # This checks refusal at the cap; the current cache has no eviction policy.
        code=CACHE_FIXTURE.split('int main() {',1)[0]+r'''
int main() {
 static_assert(Cache::budget==(4ull<<30) && Cache::max_files==4096);
 std::vector<uint8_t> payload(128,7);Digest key{};key.fill(255);
 const std::filesystem::path count_root="count-bound",byte_root="byte-bound";
 std::filesystem::create_directory(count_root);
 for(size_t n=0;n<Cache::max_files;++n) {
  Digest name{};put64(name.data(),n);
  std::ofstream(count_root/(hex(name)+".bin"),std::ios::binary).put('x');
 }
 Cache count_cache(count_root,digest,"build");
 assert(!count_cache.save(key,payload,0));
 assert(!std::filesystem::exists(count_root/"pending.tmp"));
 assert(std::distance(std::filesystem::directory_iterator(count_root),
                      std::filesystem::directory_iterator{})==Cache::max_files);
 std::filesystem::create_directory(byte_root);
 Digest filler{};auto path=byte_root/(hex(filler)+".bin");
 std::ofstream(path,std::ios::binary).put('x');
#ifdef _WIN32
 HANDLE handle=CreateFileW(path.c_str(),GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,
                           nullptr,OPEN_EXISTING,0,nullptr);
 assert(handle!=INVALID_HANDLE_VALUE);DWORD returned=0;
 assert(DeviceIoControl(handle,0x000900c4,nullptr,0,nullptr,0,&returned,nullptr));
 CloseHandle(handle);
#endif
 auto size=Cache::budget-Cache::header_size-payload.size()+1;
 std::filesystem::resize_file(path,size);
 Cache byte_cache(byte_root,digest,"build");
 assert(!byte_cache.save(key,payload,0));
 assert(std::filesystem::file_size(path)==size);
 assert(!std::filesystem::exists(byte_root/"pending.tmp"));
 std::filesystem::resize_file(path,Cache::budget+1);
 Cache overfull(byte_root,digest,"build");Digest output{};
 assert(!overfull.key("input",payload,output));
 assert(!overfull.save(key,payload,0));
 assert(std::filesystem::file_size(path)==Cache::budget+1);
 std::puts("4096-file and 4294967296-byte caps refuse persistence; no eviction");
}
'''
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'win_astc_cache.h').write_text(added('win_astc_cache.h'))
            (d/'test.cpp').write_text(code);exe=d/'test'
            p=subprocess.run([cxx,'-std=c++20',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],cwd=d,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('caps refuse persistence; no eviction',p.stdout)

    def test_async_store_retains_inputs_bounds_inflight_and_publishes_atomically(self):
        cxx=os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            for name in ['win_astc_cache.h','win_astc_store.h']:
                (d/name).write_text(added(name))
            (d/'test.cpp').write_text(STORE_FIXTURE);exe=d/'test'
            p=subprocess.run([cxx,'-std=c++20','-pthread',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],cwd=d,capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    @unittest.skipUnless(sys.platform=='win32','actual Windows CNG backend')
    def test_native_cng_known_vectors_and_executable_identity(self):
        cxx=os.environ.get('CXX') or shutil.which('clang++')
        if not cxx:self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'win_astc_cache.h').write_text(added('win_astc_cache.h'))
            code="""#include <cassert>
#include "win_astc_cache.h"
int main() {
 nx::astc_cache::Digest d{};
 assert(nx::astc_cache::sha256({{nullptr,0}},d));
 assert(nx::astc_cache::hex(d)=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
 assert(nx::astc_cache::sha256({{"a",1},{"bc",2}},d));
 assert(nx::astc_cache::hex(d)=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
 assert(nx::astc_cache::executable_identity().size()==80);
}
"""
            (d/'test.cpp').write_text(code);exe=d/'test.exe'
            p=subprocess.run([cxx,'-std=c++20',str(d/'test.cpp'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],cwd=d,capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_windows_series_ends_with_this_overlay(self):
        series=[x.split('#')[0].strip() for x in (ROOT/'runtime/patches/series.windows').read_text().splitlines()]
        self.assertEqual([x for x in series if x][-2:],['astral-windows-replay.patch',PATCH.name])
        for platform in ['linux','macos']:
            self.assertNotIn(PATCH.name,(ROOT/f'runtime/patches/series.{platform}').read_text())

    def test_full_series_applies_after_replay(self):
        reference=Path(os.environ.get('NVN_REFERENCE','/nonexistent'))
        if not (reference/'.git').exists():self.skipTest('existing NVN_REFERENCE required; no downloads')
        with tempfile.TemporaryDirectory() as temp:
            series=[x.split('#')[0].strip() for x in (ROOT/'runtime/patches/series.windows').read_text().splitlines()]
            out=Path(temp)/'source'
            prepare_runtime.prepare_source(reference,out,[ROOT/'runtime/patches'/x for x in series if x])
            self.assertEqual((out/'runtime/src/win_stutter.h').read_text(),added('win_stutter.h'))
            platform_source=(out/'runtime/src/platform_win.cpp').read_text()
            root_function='std::string data_root() {'+platform_source.split('std::string data_root() {',1)[1].split('// ---- window',1)[0]
            self.assertIn('GetEnvironmentVariableW(L"NX_DATA_ROOT"',root_function)
            self.assertIn('WideCharToMultiByte(CP_UTF8',root_function)
            if sys.platform=='win32':
                cxx=os.environ.get('CXX') or shutil.which('clang++')
                self.assertTrue(cxx,'native C++ compiler required')
                code='''#define NOMINMAX
#include <windows.h>
#include <string>
#include <cstdio>
namespace nx::game { struct Info { const char* pc_data_root; }; const Info kInfo{"default-data"}; }
namespace nx::plat {
@ROOT@
}
int main() { std::printf("%s",nx::plat::data_root().c_str()); }
'''.replace('@ROOT@',root_function)
                fixture=Path(temp)/'root.cpp';fixture.write_text(code);exe=Path(temp)/'root.exe'
                run=subprocess.run([cxx,'-std=c++20',str(fixture),'-o',str(exe)],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                value=str(Path(temp)/'data-雪-é')
                run=subprocess.run([str(exe)],env=dict(os.environ,NX_DATA_ROOT=value),capture_output=True)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual(run.stdout.decode('utf-8'),value)
            # Trace all creation classes, decode/prepare, waits, present and acquire in composed production source.
            for name,kinds in [('nvn/nvn_pipeline.cpp',['Graphics','Compute','Module']),
                               ('nvn/nvn_upload.cpp',['Astc','Texture']),('nvn/nvn_frames.cpp',['Fence']),
                               ('nvn/nvn_vk.cpp',['Present','Acquire','Frame','Submit']),
                               ('kernel.cpp',['Svc','Block']),('platform_win.cpp',['Sleep'])]:
                text=(out/'runtime/src'/name).read_text()
                for kind in kinds:self.assertIn('stutter::'+kind,text,name)


if __name__=='__main__':unittest.main()
