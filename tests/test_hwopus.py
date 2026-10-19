"""Real patched hwopus/CMIF, real host libopus; only kernel/VM glue is synthetic."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


HOST = r'''
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/mman.h>
namespace nx {
struct CPU { uint64_t x[32]{}; };
bool g_trace=false;
void log(const char*, ...) {}
[[noreturn]] void fatal(const char* fmt, ...) {
    char b[256];va_list args;va_start(args,fmt);vsnprintf(b,sizeof b,fmt,args);va_end(args);
    throw std::runtime_error(b);
}
template<class T> T ld(uint64_t a) { T v;std::memcpy(&v,(void*)a,sizeof v);return v; }
template<class T> void st(uint64_t a,T v) { std::memcpy((void*)a,&v,sizeof v); }
struct VmInfo { uint64_t addr,size;uint32_t state,perm; };
std::vector<VmInfo> regions;
VmInfo vm_query(uint64_t a) {
    for(auto v:regions) if(a>=v.addr && a-v.addr<v.size) return v;
    return {a,1,0,0};
}
uint64_t kernel_alloc(uint64_t) { throw std::runtime_error("unexpected kernel allocation"); }
bool commit(uint64_t,uint64_t) { throw std::runtime_error("unexpected commit"); }
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) { throw std::runtime_error("unexpected vm_set"); }
constexpr uint32_t kMemAlias=14;
}
#include "ipc.h"
namespace nx {
std::map<uint32_t,std::shared_ptr<KObject>> handles;
uint32_t next_handle=1;
uint32_t handle_add(std::shared_ptr<KObject> p) { auto h=next_handle++;handles[h]=std::move(p);return h; }
std::shared_ptr<KObject> handle_get(uint32_t h) { auto it=handles.find(h);return it==handles.end()?nullptr:it->second; }
void handle_close(uint32_t h) { handles.erase(h); }
}
#include "ipc.cpp"
#include "svc_hwopus.cpp"
using namespace nx;
'''

TEST = r'''
uint64_t BASE=0x120000000ull;
alignas(16) uint32_t msg[256];
CPU cpu;
struct Reply { uint32_t rc,handle,object;std::vector<uint8_t> data; };
Reply wire(uint32_t session,uint32_t cmd,std::vector<uint8_t> args={},
           std::vector<uint32_t> copies={},std::vector<Buffer> a={},std::vector<Buffer> b={},
           uint32_t domain=0,uint32_t type=6,bool close_domain=false) {
    std::memset(msg,0,sizeof msg);msg[0]=type|(uint32_t(a.size())<<20)|(uint32_t(b.size())<<24);
    size_t p=2;
    if(!copies.empty()) {msg[1]=1u<<31;msg[p++]=uint32_t(copies.size())<<1;for(auto h:copies)msg[p++]=h;}
    auto descriptor=[&](Buffer v) {
        msg[p++]=uint32_t(v.size);msg[p++]=uint32_t(v.addr);
        msg[p++]=uint32_t((v.addr>>32)&15)<<28|uint32_t((v.addr>>36)&7)<<2|uint32_t((v.size>>32)&15)<<24;
    };
    for(auto v:a)descriptor(v);for(auto v:b)descriptor(v);
    size_t start=p*4, raw=(start+15)&~size_t(15), cmif=raw;
    if(domain) {
        msg[raw/4]=(close_domain?2u:1u)|(uint32_t(close_domain?0:16+args.size())<<16);
        msg[raw/4+1]=domain;cmif+=16;
    }
    msg[cmif/4]=kSFCI;msg[cmif/4+1]=1;msg[cmif/4+2]=cmd;msg[cmif/4+3]=123;
    std::memcpy((uint8_t*)msg+cmif+16,args.data(),args.size());
    msg[1]|=uint32_t((32+(domain?16:0)+args.size()+3)/4);
    assert(ipc_request(cpu,session,(uint64_t)msg,sizeof msg)==0);
    if(close_domain)return {};
    size_t q=2;uint32_t h=0;
    if(msg[1]>>31) {assert(msg[q]==32);h=msg[++q];++q;}
    size_t replyraw=(q*4+15)&~size_t(15), data=replyraw+(domain?16:0)+16;
    assert(msg[(data-16)/4]==kSFCO);
    auto rc=msg[(data-8)/4];
    size_t end=q*4+((msg[1]&1023)-4)*4;
    uint32_t object=0;
    if(domain && msg[replyraw/4]) {assert(msg[replyraw/4]==1);end-=4;object=msg[end/4];}
    return {rc,h,object,{(uint8_t*)msg+data,(uint8_t*)msg+end}};
}
std::vector<uint8_t> scalars(uint32_t r,uint32_t ch,uint32_t bytes=0,bool open=false) {
    std::vector<uint8_t> v(open?12:8);std::memcpy(v.data(),&r,4);std::memcpy(v.data()+4,&ch,4);
    if(open)std::memcpy(v.data()+8,&bytes,4);return v;
}
uint32_t word(const std::vector<uint8_t>& v,size_t off=0) {uint32_t n;assert(v.size()>=off+4);std::memcpy(&n,v.data()+off,4);return n;}
void be(uint8_t* p,uint32_t v) {for(int i=0;i<4;++i)p[i]=uint8_t(v>>(24-8*i));}
uint32_t acquire() {
    uint64_t sm=0;assert(ipc_connect("sm:",&sm)==0);
    auto r=wire(uint32_t(sm),1,{'h','w','o','p','u','s',0,0});assert(r.rc==0 && r.handle && r.data.empty());
    handle_close(uint32_t(sm));return r.handle;
}
void protocol_close(uint32_t h) {
    std::memset(msg,0,sizeof msg);msg[0]=2;
    assert(ipc_request(cpu,h,(uint64_t)msg,sizeof msg)==0xF601);handle_close(h);
}
int main() {
    void* allocation=mmap((void*)BASE,1<<20,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    assert(allocation!=MAP_FAILED);BASE=reinterpret_cast<uint64_t>(allocation);
    assert(BASE<(1ull<<39));regions={{BASE,1<<20,5,3}};
    uint32_t manager=acquire();
    for(uint32_t ch:{1u,2u})for(uint32_t rate:{8000u,12000u,16000u,24000u,48000u}) {
        auto query=wire(manager,1,scalars(rate,ch));
        assert(query.rc==0 && query.data.size()==4 && !query.handle);
        assert(word(query.data)==uint32_t(opus_decoder_get_size(int(ch))));
        auto bytes=(word(query.data)+4095)&~4095u;
        auto tm=std::make_shared<KTransferMemory>();tm->addr=BASE;tm->size=bytes;
        std::memset((void*)BASE,0xa5,bytes);std::weak_ptr<KTransferMemory> weak=tm;
        auto t=handle_add(tm);tm.reset();
        auto opened=wire(manager,0,scalars(rate,ch,bytes,true),{t});
        assert(opened.rc==0 && opened.handle && opened.data.empty());
        auto decoder=opened.handle;handle_close(t);assert(!weak.expired());
        // Independent real encoder creates original synthetic audio, no stored/game fixtures.
        int err=0;auto* encoder=opus_encoder_create(48000,int(ch),OPUS_APPLICATION_AUDIO,&err);assert(err==0);
        std::vector<opus_int16> signal(960*ch);
        for(size_t i=0;i<960;++i)for(size_t c=0;c<ch;++c)
            signal[i*ch+c]=opus_int16(((int(i)%(c?173:109))-50)*200);
        auto* packet=(uint8_t*)(BASE+0x40000);auto* pcm=(uint8_t*)(BASE+0x50000);
        int count=opus_encode(encoder,signal.data(),960,packet+8,4000);assert(count>0);
        opus_uint32 range=0;assert(opus_encoder_ctl(encoder,OPUS_GET_FINAL_RANGE(&range))==0);assert(range);
        opus_encoder_destroy(encoder);be(packet,uint32_t(count));be(packet+4,range);
        const int samples=int(rate/50);const size_t pcmbytes=size_t(samples)*ch*2;
        std::vector<opus_int16> expected(size_t(samples)*ch),second(expected.size());
        auto* reference=opus_decoder_create(int(rate),int(ch),&err);assert(err==0);
        assert(opus_decode(reference,packet+8,count,expected.data(),samples,0)==samples);
        assert(std::any_of(expected.begin(),expected.end(),[](auto v){return v!=0;}));
        assert(opus_decode(reference,packet+8,count,second.data(),samples,0)==samples);
        opus_decoder_destroy(reference);
        auto decode=[&](uint8_t reset=0,uint64_t insize=0,uint64_t outsize=0) {
            return wire(decoder,6,{reset}, {},{{(uint64_t)packet,insize?insize:uint64_t(count+8)}},
                        {{(uint64_t)pcm,outsize?outsize:pcmbytes}});
        };
        auto assert_pcm=[&](const std::vector<opus_int16>& e) {assert(std::memcmp(pcm,e.data(),pcmbytes)==0);};
        std::memset(pcm-16,0x5a,pcmbytes+32);auto r=decode();
        assert(r.rc==0 && r.data.size()==16 && word(r.data)==uint32_t(count+8) && word(r.data,4)==uint32_t(samples));assert_pcm(expected);
        for(int i=0;i<16;++i)assert(pcm[-16+i]==0x5a && pcm[pcmbytes+i]==0x5a);
        assert(decode().rc==0);assert_pcm(second);
        assert(decode(1).rc==0);assert_pcm(expected);
        // Failed reset+decode must preserve BOTH the old state and the output.
        std::memset(pcm,0x71,pcmbytes);be(packet+4,range^1);
        assert(decode(1).rc!=0);for(size_t i=0;i<pcmbytes;++i)assert(pcm[i]==0x71);
        be(packet+4,range);assert(decode().rc==0);assert_pcm(second);
        std::memset(pcm,0x71,pcmbytes);
        assert(decode(2).rc!=0);assert(decode(0,7).rc!=0);assert(decode(0,0,pcmbytes-1).rc!=0);
        be(packet,uint32_t(count+1));assert(decode(0,uint64_t(count+8)).rc!=0);
        be(packet,0);assert(decode().rc!=0);be(packet,0xffffffff);assert(decode().rc!=0);be(packet,uint32_t(count));
        for(size_t i=0;i<pcmbytes;++i)assert(pcm[i]==0x71);
        // Libopus rejects malformed TOC/frame framing, with no PCM write.
        std::vector<uint8_t> saved(packet,packet+count+8);be(packet,2);packet[8]=0xff;packet[9]=0xff;
        assert(decode(1,10).rc!=0);std::memcpy(packet,saved.data(),saved.size());
        for(size_t i=0;i<pcmbytes;++i)assert(pcm[i]==0x71);
        // zero entropy range is explicitly optional in the public header.
        be(packet+4,0);assert(decode(1).rc==0);assert_pcm(expected);
        for(uint32_t cmd:{0u,1u,4u,7u,999u}) {
            bool failed=false;try{wire(decoder,cmd,{0});}catch(const std::runtime_error& e){failed=std::string(e.what()).find("unsupported decoder")!=std::string::npos;}assert(failed);
        }
        // Clone keeps the same service alive; alias follows protocol-close semantics.
        auto alias=handle_add(handle_get(decoder));auto clone=wire(decoder,2,{}, {},{}, {},0,5).handle;
        assert(clone);protocol_close(decoder);assert(!weak.expired());
        assert(!std::dynamic_pointer_cast<KSession>(handle_get(alias))->svc);handle_close(alias);
        protocol_close(clone);assert(weak.expired());
        for(size_t i=0;i<bytes;++i)assert(((uint8_t*)BASE)[i]==0xa5);
        printf("PASS real libopus %u Hz %u channel: query/open PCM=%d reset/range/errors/clone/close\n",rate,ch,samples);
    }
    auto service=make_service("hwopus");
    auto direct=[&](uint32_t cmd,std::vector<uint8_t>& args) {IpcCtx c;c.type=6;c.cmd=cmd;c.in=args.data();c.in_size=args.size();return c;};
    auto config=scalars(48000,2);
    for(size_t n=0;n<8;++n) {auto c=direct(1,config);c.in_size=n;assert(service->handle(c)!=0 && c.out.empty());}
    for(auto rate:{0u,1u,44100u,UINT32_MAX}) {auto a=scalars(rate,2);auto c=direct(1,a);assert(service->handle(c)!=0);}
    for(auto ch:{0u,3u,UINT32_MAX}) {auto a=scalars(48000,ch);auto c=direct(1,a);assert(service->handle(c)!=0);}
    for(int variant=0;variant<8;++variant) {
        auto c=direct(1,config);
        switch(variant){case 0:c.a={{BASE,1}};break;case 1:c.b={{BASE,1}};break;case 2:c.x={{BASE,1}};break;
        case 3:c.c={{BASE,1}};break;case 4:c.w={{BASE,1}};break;case 5:c.in_copy={123};break;case 6:c.in_move={123};break;case 7:c.in_objects={1};break;}
        assert(service->handle(c)!=0 && c.out.empty() && c.out_objects.empty());
    }
    auto sz=uint32_t((opus_decoder_get_size(2)+4095)&~4095);
    auto tm=std::make_shared<KTransferMemory>();tm->addr=BASE;tm->size=sz;auto h=handle_add(tm);
    auto args=scalars(48000,2,sz,true);
    for(size_t n=0;n<12;++n) {auto c=direct(0,args);c.in_size=n;c.in_copy={h};assert(service->handle(c)!=0);}
    for(auto handle:{0u,0xdeadu,handle_add(std::make_shared<KObject>())}) {auto c=direct(0,args);c.in_copy={handle};assert(service->handle(c)!=0);if(handle_get(handle))handle_close(handle);}
    for(auto bytes:{0u,1u,sz-1,sz+4096,UINT32_MAX}) {auto a=scalars(48000,2,bytes,true);auto c=direct(0,a);c.in_copy={h};assert(service->handle(c)!=0);}
    for(auto addr:{uint64_t(0),BASE+1,UINT64_MAX-4095,BASE+(1<<20)}) {tm->addr=addr;auto c=direct(0,args);c.in_copy={h};assert(service->handle(c)!=0);}tm->addr=BASE;
    regions[0].perm=1;auto c=direct(0,args);c.in_copy={h};assert(service->handle(c)!=0);regions[0].perm=3;
    c=direct(0,args);c.in_copy={h};assert(service->handle(c)==0);auto decoder=c.out_objects[0];c.out_objects.clear();
    auto reset=std::vector<uint8_t>(4);auto d=direct(6,reset);d.a={{BASE+0x40000,8}};d.b={{BASE+0x50000,4000}};
    for(auto bad:{Buffer{0,8},Buffer{UINT64_MAX-3,8},Buffer{BASE+(1<<20),8}}) {auto e=d;e.a={bad};assert(decoder->handle(e)!=0 && e.out.empty());e=d;e.b={bad};assert(decoder->handle(e)!=0);}
    for(size_t n=0;n<4;++n) {auto e=d;e.in_size=n;assert(decoder->handle(e)!=0);}
    for(int variant=0;variant<8;++variant) {auto e=d;switch(variant){case 0:e.a.clear();break;case 1:e.b.clear();break;case 2:e.x=e.a;break;case 3:e.c=e.b;break;case 4:e.w=e.a;break;case 5:e.in_copy={h};break;case 6:e.in_move={h};break;case 7:e.a.push_back(e.a[0]);break;}assert(decoder->handle(e)!=0);}
    // Crossing VM regions checks every page; permissionless tail cannot be used.
    regions={{BASE,0x40004,5,3},{BASE+0x40004,(1<<20)-0x40004,5,0}};assert(decoder->handle(d)!=0);regions={{BASE,1<<20,5,3}};
    decoder.reset();handle_close(h);tm.reset();
    for(uint32_t cmd:{2u,3u,999u}) {bool failed=false;try{wire(manager,cmd,config);}catch(const std::runtime_error&){failed=true;}assert(failed);}
    // Real domain object serialization, clone lifetime and domain object close.
    auto root=word(wire(manager,0,{}, {},{}, {},0,5).data);assert(root);
    auto q=wire(manager,1,config,{}, {},{},root);assert(q.rc==0 && q.data.size()==4);
    tm=std::make_shared<KTransferMemory>();tm->addr=BASE;tm->size=sz;h=handle_add(tm);std::weak_ptr<KTransferMemory> weak=tm;tm.reset();
    auto opened=wire(manager,0,args,{h},{},{},root);assert(opened.rc==0 && opened.object && !opened.handle);handle_close(h);
    auto domain_pcm=wire(manager,6,{1},{},{{BASE+0x40000,uint64_t(8+be32((uint8_t*)(BASE+0x40000)))}},{{BASE+0x50000,3840}},opened.object);
    assert(domain_pcm.rc==0 && domain_pcm.data.size()==16 && word(domain_pcm.data,4)==960);
    auto cloned=wire(manager,2,{}, {},{}, {},0,5).handle;assert(cloned);protocol_close(manager);assert(!weak.expired());
    wire(cloned,0,{}, {},{}, {},opened.object,6,true);assert(weak.expired());protocol_close(cloned);
    manager=acquire();assert(wire(manager,1,config).rc==0);protocol_close(manager);
    assert(handles.empty());assert(munmap(allocation,1<<20)==0);
    puts("PASS scalar/descriptor/range/workspace failures and domain teardown; all handles released");
}
'''


class HwopusTests(unittest.TestCase):
    def test_production_service_and_real_decoder(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip()).resolve()
        reference = common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        self.assertTrue(reference.is_dir(), 'pinned private runtime reference required; missing is not a passing skip')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        pkg = shutil.which('pkg-config')
        self.assertIsNotNone(pkg, 'installed libopus development package required')
        flags = shlex.split(subprocess.check_output([pkg, '--cflags', '--libs', 'opus'], text=True))
        version = subprocess.check_output([pkg, '--modversion', 'opus'], text=True).strip()
        out = ROOT / '.local/hwopus-impl-075' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        source = out / 'source'
        patches = [ROOT / 'runtime/patches' / n for n in
                   ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-ipc-buffer.patch', 'astral-hwopus.patch')]
        runtime.prepare_source(reference, source, patches)
        paths = [line.split(' b/')[1] for line in patches[-1].read_text().splitlines() if line.startswith('diff --git ')]
        self.assertEqual(set(paths), {'CMakeLists.txt', 'runtime/src/svc_hwopus.cpp'})
        fixture = out / 'fixture'; fixture.mkdir(); (fixture / 'nx').mkdir()
        names = ['ipc.h', 'ipc.cpp', 'kernel.h', 'svc_hwopus.cpp']
        for name in names:
            shutil.copyfile(source / 'runtime/src' / name, fixture / name)
        (fixture / 'nx/runtime.h').write_text('// unrelated VM and kernel host declarations supplied by fixture\n')
        (fixture / 'test.cpp').write_text(HOST + TEST)
        command = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-I', str(fixture),
                   str(fixture / 'test.cpp'), '-o', str(fixture / 'test')] + flags
        build = subprocess.run(command, capture_output=True, text=True, timeout=90)
        (out / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        run = subprocess.run([str(fixture / 'test')], capture_output=True, text=True, timeout=30)
        (out / 'test.log').write_text(run.stdout + run.stderr)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.count('PASS'), 11)
        print(run.stdout, end='')
        receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'pin': runtime.PIN, 'opus_version': version,
                   'patches': {p.name: sha(p) for p in patches}, 'command': command,
                   'compiled_sources': {n: sha(fixture / n) for n in names},
                   'binary_sha256': sha(fixture / 'test'), 'compile_exit': build.returncode,
                   'run_exit': run.returncode, 'output': run.stdout}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('retained receipt:', (out / 'receipt.json').relative_to(ROOT), sha(out / 'receipt.json'))


if __name__ == '__main__':
    unittest.main()
