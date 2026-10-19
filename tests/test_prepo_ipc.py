"""Original synthetic guest packets exercise the actual patched production IPC.

No guest source, native executable or game input is compiled or run. Fixtures,
local report stores and indexed compiler/run receipts remain ignored.
"""
from datetime import datetime, timezone
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

HARNESS = r'''
#include "kernel-host.h"
#include <sys/mman.h>
#include <fstream>
using namespace nx;
alignas(16) uint32_t packet[256];
CPU cpu;
uint64_t base;
uint32_t session;
size_t raw;
std::vector<uint8_t> good={0xde,0,3,0xa4,'f','l','a','g',0xc3,0xa5,'c','o','u','n','t',0xd3,255,255,255,255,255,255,255,254,0xa4,'n','a','m','e',0xa2,'o','k'};
uint32_t make_request(uint32_t cmd=10103, bool user=true, bool with_pid=true, bool domain=false, uint32_t object=1) {
    std::memset(packet,0,sizeof packet);packet[0]=6|(1<<16)|(1<<20);
    size_t p=2;
    if(with_pid) {packet[1]=1u<<31;packet[p++]=1;packet[p++]=0xdead;packet[p++]=0xbeef;}
    auto e=base, r=base+0x1000;
    packet[p++]=uint32_t(6<<16)|uint32_t((e>>32)&15)<<12|uint32_t((e>>36)&7)<<6;packet[p++]=uint32_t(e);
    packet[p++]=uint32_t(good.size());packet[p++]=uint32_t(r);packet[p++]=uint32_t((r>>32)&15)<<28|uint32_t((r>>36)&7)<<2;
    raw=(p*4+15)&~size_t(15);size_t cmif=raw;
    if(domain) {packet[raw/4]=1|(uint32_t(16+(user?24:8))<<16);packet[raw/4+1]=object;cmif+=16;}
    packet[cmif/4]=kSFCI;packet[cmif/4+2]=cmd;
    if(user) {packet[cmif/4+4]=123;packet[cmif/4+6]=456;}
    packet[1]|=uint32_t((32+(domain?16:0)+(user?24:8))/4);
    return uint32_t(cmif/4+4);
}
uint32_t send(uint32_t h=0, uint64_t size=sizeof packet) {
    cpu.x[0]=(uint64_t)packet;cpu.x[1]=size;cpu.x[2]=h?h:session;svc(cpu,0x22,0);return uint32_t(cpu.x[0]);
}
void expect_fatal(const std::function<void()>& f,const char* contains) {
    bool failed=false;
    try {f();} catch(const std::runtime_error& e) {failed=std::string(e.what()).find(contains)!=std::string::npos; if(!failed)std::fprintf(stderr,"unexpected: %s\n",e.what());}
    assert(failed);
}
uint32_t acquire(const char* name="prepo:u") {
    uint64_t sm=0;assert(ipc_connect("sm:",&sm)==0);
    std::memset(packet,0,sizeof packet);packet[0]=6;packet[1]=10;packet[4]=kSFCI;packet[6]=1;
    std::memcpy(packet+8,name,std::min<size_t>(8,std::strlen(name)));
    try {assert(send(uint32_t(sm))==0);} catch(...) {close(uint32_t(sm));throw;} assert(packet[2]==32);auto h=packet[3];close(uint32_t(sm));return h;
}
std::vector<uint8_t> stored(unsigned slot) {
    std::ifstream f(std::filesystem::path(plat::data_root())/"user/prepo"/std::to_string(slot)/"report.bin",std::ios::binary);
    return {std::istreambuf_iterator<char>(f),{}};
}
int main(int argc,char** argv) {
    assert(argc==2); fixture_guest_memory=true;auto main_handle=create_main_thread(4096);
    void* mem=mmap((void*)0x120000000ull,0x20000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
    assert(mem!=MAP_FAILED);base=(uint64_t)mem;assert(base<(1ull<<39));
    fixture_regions={{base,0x20000,5,3}};
    std::memcpy((void*)base,"event",6);std::memcpy((void*)(base+0x1000),good.data(),good.size());
    if(std::string(argv[1])=="absent") {
        expect_fatal([]{acquire();},"strict IPC missing service: prepo:u");puts("PASS prepatch reproduces strict missing prepo:u");return 0;
    }
    session=acquire();auto service=std::dynamic_pointer_cast<KSession>(handle_get(session))->svc;
    std::weak_ptr<Service> weak=service;service.reset();
    if(std::string(argv[1])=="bad-store" || std::string(argv[1])=="write-failure") {
        make_request();expect_fatal([]{send();},std::string(argv[1])=="bad-store"?"unsafe local store":"write/flush failed");
        puts("PASS unsafe local store or real stream failure never returns success");return 0;
    }
    if(std::string(argv[1])=="reopen") {
        assert(stored(0).size()==56+6+good.size());make_request(10102,false);assert(send()==0);
        assert(stored(1).size()==56+6+good.size());puts("PASS persistent reports survive process restart; second session appends");return 0;
    }
    make_request();assert(send()==0);assert(packet[6]==0);auto bytes=stored(0);
    assert(bytes.size()==56+6+good.size());uint64_t header[7];std::memcpy(header,bytes.data(),56);
    assert(header[0]==1&&header[1]==10103&&header[2]!=0&&header[3]==123&&header[4]==456&&header[5]==6&&header[6]==good.size());
    assert(std::equal(good.begin(),good.end(),bytes.begin()+62));
    puts("PASS real SM, kernel-authenticated PID, CMIF SaveReportWithUser and exact local persisted bytes");
    if(std::string(argv[1])=="dead-process") {
        try {svc(cpu,0x0a,0);} catch(const std::runtime_error&) {}
        make_request();assert(send()==0xE401);close(session);assert(weak.expired());
        puts("PASS exited process cannot use retained prepo session");return 0;
    }
    // Largest SDK report: 100 unique 63-byte keys and 63-byte string values.
    std::vector<uint8_t> maximum={0xde,0,100};
    for(unsigned i=0;i<100;++i) {
        auto key=std::string("k")+std::string(60,'x')+char('0'+i/10)+char('0'+i%10);
        maximum.insert(maximum.end(),{0xd9,63});maximum.insert(maximum.end(),key.begin(),key.end());
        maximum.insert(maximum.end(),{0xd9,63});maximum.insert(maximum.end(),63,'v');
    }
    assert(maximum.size()==13003);std::memcpy((void*)(base+0x1000),maximum.data(),maximum.size());
    make_request();packet[7]=13003;assert(send()==0);assert(stored(1).size()==56+6+13003);
    std::memcpy((void*)(base+0x1000),good.data(),good.size());
    puts("PASS exact 13003-byte, 100-field SDK report limit persists without truncation");
    auto invalid=[&](const std::function<void()>& change,const char* error="prepo:") {
        auto prior=std::filesystem::directory_iterator(std::filesystem::path(plat::data_root())/"user/prepo");
        size_t count=std::distance(prior,std::filesystem::directory_iterator{});
        make_request();change();auto copy=std::vector<uint32_t>(packet,packet+256);
        auto handles=kstate::g_handles.size();auto next=kstate::g_next_handle;
        expect_fatal([]{send();},error);
        assert(std::equal(copy.begin(),copy.end(),packet));
        assert(kstate::g_handles.size()==handles && kstate::g_next_handle==next);
        assert(size_t(std::distance(std::filesystem::directory_iterator(std::filesystem::path(plat::data_root())/"user/prepo"),std::filesystem::directory_iterator{}))==count);
    };
    invalid([]{packet[raw/4+8]=1;}); // reserved process-id parameter
    make_request(10103,true,false);expect_fatal([]{send();},"prepo: malformed");
    invalid([]{packet[1]=(packet[1]&~1023u)|8;},"prepo:");
    invalid([]{packet[0]|=1u<<24;},"ipc: malformed");
    invalid([]{packet[1]|=1u<<10;},"ipc: malformed");
    invalid([]{packet[5]=uint32_t(1u<<16);}); // zero X size/address shape
    invalid([]{packet[7]=13004;});
    invalid([]{packet[7]=2;});invalid([]{packet[8]=0x123456;packet[9]=0;});
    invalid([]{packet[5]=(33u<<16);});
    auto report=[&](std::vector<uint8_t> b) {
        std::memcpy((void*)(base+0x1000),b.data(),b.size());
        invalid([&]{packet[7]=uint32_t(b.size());});
        std::memcpy((void*)(base+0x1000),good.data(),good.size());
    };
    report({0xde,0,1});report({0xde,0,101});report({0xde,0,0,0});
    report({0x81,0xa1,'1',0xc3});report({0x81,0xa1,'a',0xc1});
    report({0x82,0xa1,'A',1,0xa1,'a',2});report({0x81,0xa1,'a',0xa2,0xc0,0x80});
    invalid([]{((char*)base)[5]='x';});((char*)base)[5]=0;
    invalid([]{fixture_regions[0].perm=0;});fixture_regions[0].perm=3;
    make_request();expect_fatal([]{send(0,12);},"ipc: malformed request framing");
    make_request();assert(send(0xdead)==0xE401);auto wrong=handle_add(std::make_shared<KSharedMemory>());
    make_request();assert(send(wrong)==0xE401);close(wrong);
    puts("PASS malformed/truncated framing, bounds, UTF-8, duplicate keys, unsupported values, read permissions and handles fail atomically");
    make_request(10200);expect_fatal([]{send();},"strict IPC missing command");
    expect_fatal([]{acquire("other:u");},"strict IPC missing service: other:u");
    expect_fatal([]{acquire("prepo:a");},"strict IPC missing service: prepo:a");
    puts("PASS unsupported transmission commands and unrelated services remain strict");
    // Domain root and clone share the real service; protocol/object close uses production lifetimes.
    std::memset(packet,0,sizeof packet);packet[0]=5;packet[1]=8;packet[4]=kSFCI;assert(send()==0);auto object=packet[8];assert(object);
    make_request(10102,false,true,true,object);assert(send()==0);assert(stored(2).size()==bytes.size());
    std::memset(packet,0,sizeof packet);packet[0]=5;packet[1]=8;packet[4]=kSFCI;packet[6]=2;assert(send()==0);auto clone=packet[3];assert(clone);
    close(session);session=clone;assert(!weak.expired());
    make_request(10103,true,true,true,object);assert(send()==0);
    make_request(10103,true,true,true,object+100);assert(send()==0xF601);
    make_request(10103,true,true,true,object);packet[raw/4]=2;packet[raw/4]&=0xffff;assert(send()==0);
    make_request(10103,true,true,true,object);assert(send()==0xF601);
    std::memset(packet,0,sizeof packet);packet[0]=2;assert(send()==0xF601);assert(weak.expired());
    make_request();assert(send()==0xF601);close(session);make_request();assert(send()==0xE401);
    puts("PASS domain conversion, clone, object close, protocol close and stale client handle lifetimes");
    session=acquire();
    for(unsigned i=4;i<64;++i) {make_request();assert(send()==0);}
    make_request();expect_fatal([]{send();},"capacity exhausted");
    puts("PASS bounded 64-record local store fails explicitly at capacity without claiming delivery");
    close(session);close(main_handle);munmap(mem,0x20000);
}
'''


class PrepoIpcTests(unittest.TestCase):
    def test_production_wire_storage_and_lifetime(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++20 compiler required')
        self.assertTrue(reference.is_dir(), 'clean pinned public runtime reference required')
        out = ROOT / '.local/prepo-ipc-083' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        names = ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
                 'astral-audio.patch', 'astral-notifications.patch', 'astral-apm.patch', 'astral-ipc-buffer.patch')
        patches = [ROOT / 'runtime/patches' / n for n in names]
        source = out / 'source'
        runtime.prepare_source(reference, source, patches)
        overlay = ROOT / 'runtime/patches/astral-prepo.patch'
        paths = [line.split(' b/')[1] for line in overlay.read_text().splitlines() if line.startswith('diff --git ')]
        self.assertEqual(paths, ['runtime/src/svc_misc.cpp'])
        fixture = out / 'fixture'
        (fixture / 'nx').mkdir(parents=True)
        compiled = ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_misc.cpp', 'svc_am.cpp', 'hle_audio.cpp', 'hle_vi.cpp')
        for name in compiled:
            shutil.copyfile(source / 'runtime/src' / name, fixture / name)
        for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
            (fixture / name).write_text('// Unrelated host declarations supplied by original synthetic fixture.\n')
        (fixture / 'astral_control_context.h').write_text('#pragma once\n#define NX_CONTROL_CONTEXT {0x1234000000000000ull,0x1234000000000000ull,0,{0},"' + 'a' * 64 + '"}\n')
        host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
        host = host.replace('#include <cassert>', '#include <cassert>\n#include <filesystem>\n#include <cstdlib>\n#include <algorithm>')
        host = host.replace('VmInfo vm_query(uint64_t) { unexpected(); }', '''std::vector<VmInfo> fixture_regions;
VmInfo vm_query(uint64_t a) {
    for(auto v:fixture_regions) if(a>=v.addr && a-v.addr<v.size) return v;
    return {a,1,0,0};
}''')
        host = host.replace('namespace plat {', '''namespace plat {
std::string data_root() { return std::getenv("PREPO_TEST_ROOT"); }
FILE* fopen_utf8(const std::string& p,const char* m) {
    // Fault injection at the host boundary retains actual fwrite/flush failure.
    if(std::getenv("PREPO_TEST_WRITE_FAILURE")) return std::fopen("/dev/null","r");
    return std::fopen(p.c_str(),m);
}
''')
        (fixture / 'kernel-host.h').write_text(host)
        (fixture / 'test.cpp').write_text(HARNESS)
        receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'overlays': {p.name: runtime.sha(p) for p in [*patches, overlay]}, 'runs': []}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        def build(label):
            binary = out / label
            argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-I', str(fixture),
                    str(fixture / 'test.cpp'), '-o', str(binary)]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            (out / (label + '-compile.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt[label] = {'command': argv, 'compile_exit': result.returncode, 'binary_sha256': runtime.sha(binary)}
            return binary
        def run(binary, label, scratch):
            scratch.mkdir(exist_ok=True)
            result = subprocess.run([str(binary), label], env=dict(os.environ, PREPO_TEST_ROOT=str(scratch), **({"PREPO_TEST_WRITE_FAILURE":"1"} if label=="write-failure" else {})),
                                    capture_output=True, text=True, timeout=30)
            (out / (label + '.log')).write_text(result.stdout + result.stderr)
            receipt['runs'].append({'label': label, 'exit_code': result.returncode, 'output': result.stdout + result.stderr})
            (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS ', result.stdout)
            print(result.stdout, end='')
        before = build('before')
        run(before, 'absent', out / 'absent-root')
        subprocess.run(['git', 'apply', '--check', str(overlay)], cwd=source, check=True)
        subprocess.run(['git', 'apply', str(overlay)], cwd=source, check=True)
        shutil.copyfile(source / 'runtime/src/svc_misc.cpp', fixture / 'svc_misc.cpp')
        receipt['compiled_sources'] = {n: runtime.sha(fixture / n) for n in compiled}
        after = build('after')
        run(after, 'full', out / 'full-root')
        run(after, 'dead-process', out / 'dead-root')
        run(after, 'write-failure', out / 'failure-root')
        unsafe = out / 'unsafe-root'
        unsafe.mkdir()
        outside = out / 'outside'
        outside.mkdir()
        (unsafe / 'user').symlink_to(outside, target_is_directory=True)
        run(after, 'bad-store', unsafe)
        self.assertEqual(list(outside.iterdir()), [])
        # Separate process demonstrates file persistence; it starts with one real
        # saved record so the second process must append rather than overwrite.
        persistence = out / 'restart-root'
        (persistence / 'user/prepo').mkdir(parents=True)
        shutil.copytree(out / 'full-root/user/prepo/0', persistence / 'user/prepo/0')
        run(after, 'reopen', persistence)
        # Re-run accepted independent regression bodies against this SAME
        # composed production source, including the new registrar/service.
        for name in ('test_apm_service', 'test_parental_control', 'test_ipc_caller'):
            src = ROOT / 'tests' / (name + '.cpp')
            binary = out / name
            argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-I', str(fixture),
                    str(src), '-o', str(binary)]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            (out / (name + '-compile.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for args in ([[], ['exit']] if name == 'test_ipc_caller' else [[]]):
                result = subprocess.run([str(binary), *args], capture_output=True, text=True, timeout=15)
                receipt['runs'].append({'label': name + str(args), 'exit_code': result.returncode,
                                       'output': result.stdout + result.stderr, 'test_sha256': runtime.sha(src),
                                       'binary_sha256': runtime.sha(binary), 'compile': argv})
                (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS ', result.stdout)
                print(result.stdout, end='')
        receipt['test_sha256'] = runtime.sha(Path(__file__))
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('retained production receipt:', (out / 'receipt.json').relative_to(ROOT), runtime.sha(out / 'receipt.json'))


if __name__ == '__main__':
    unittest.main()
