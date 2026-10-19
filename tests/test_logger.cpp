// Original synthetic acceptance of actual patched kernel, IPC and ILogger.
#include <sys/mman.h>
#include "kernel-host.h"

int main() {
    setbuf(stdout,nullptr);
    fixture_guest_memory=true;auto main_handle=create_main_thread(4096);
    auto& t=*self_thread();CPU cpu;alignas(16) uint32_t msg[64]{};
    auto* memory=static_cast<uint8_t*>(mmap(reinterpret_cast<void*>(0x3000000000ull), 0x20000,
        PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON, -1, 0));
    assert(memory!=MAP_FAILED);const uint64_t addr=reinterpret_cast<uint64_t>(memory);
    assert(addr+0x20000 < (1ull<<39));fixture_regions.push_back({addr,0x20000,3,3});
    auto factory=new_session_handle(make_service("lm"));
    auto open=[&](bool pid) {
        std::memset(msg,0,sizeof msg);msg[0]=4;msg[1]=pid?0x8000000au:10u;
        if(pid) {msg[2]=1;msg[3]=0xdeadbeef;}
        auto raw=pid?8u:4u;msg[raw]=kSFCI;
        t.tls=reinterpret_cast<uint64_t>(msg);cpu.x[0]=factory;svc(cpu,0x21,0);
        assert(cpu.x[0]==0);return msg[3];
    };
    auto rejects=[&](auto call,const char* text) {
        bool caught=false;auto count=kstate::g_handles.size();
        try {call();}catch(const std::runtime_error& e) {caught=std::string(e.what()).find(text)!=std::string::npos;}
        assert(caught && count==kstate::g_handles.size());
    };
    rejects([&]{open(false);},"authenticated PID");auto logger=open(true);assert(logger);
    // Header process ID is deliberately forged and is never trusted.
    auto packet=[&](uint8_t flags,std::vector<uint8_t> payload,uint64_t thread=7) {
        std::memset(memory,0,24);st<uint64_t>(addr,0xdeadbeef);st<uint64_t>(addr+8,thread);
        memory[16]=flags;memory[18]=1;st<uint32_t>(addr+20,payload.size());
        std::memcpy(memory+24,payload.data(),payload.size());return 24+payload.size();
    };
    auto invoke=[&](size_t size,bool a=false) {
        std::memset(msg,0,sizeof msg);msg[0]=4|(a?1u<<20:1u<<16);
        unsigned raw=a?8:4;msg[1]=8;
        if(a) {msg[2]=size;msg[3]=uint32_t(addr);msg[4]=(uint32_t((addr>>32)&15)<<28)|(uint32_t((addr>>36)&7)<<2);}
        else {msg[2]=(uint32_t(size)<<16)|uint32_t((addr>>32)&15)<<12|uint32_t((addr>>36)&7)<<6;msg[3]=uint32_t(addr);}
        msg[raw]=kSFCI;t.tls=reinterpret_cast<uint64_t>(msg);cpu.x[0]=logger;svc(cpu,0x21,0);
        assert(cpu.x[0]==0 && msg[4]==kSFCO && msg[6]==0);
    };
    g_trace=true;
    std::string secret="LOGGER_PRIVATE_SECRET_%s_\x1b";
    std::vector<uint8_t> private_payload{2,uint8_t(secret.size()+1)};
    private_payload.insert(private_payload.end(),secret.begin(),secret.end());private_payload.push_back(0);
    invoke(packet(7,private_payload));
    for(const auto& entry:fixture_logs) assert(entry.find("LOGGER_PRIVATE_SECRET")==std::string::npos);
    invoke(packet(7,{2,3,'a',0,'%'}));invoke(packet(7,{6,0}),true);
    puts("PASS serialized factory and Log X/A result-only requests with forged header PID and binary text");
    invoke(packet(5,{2,4,'a'}));invoke(packet(7,{2,1,'z'},8));invoke(packet(6,{'b','c','d'}));
    invoke(packet(5,{2,0x80},9));std::vector<uint8_t> rest(129,'q');rest[0]=1;invoke(packet(6,rest,9));
    puts("PASS chunking and interleaving including chunk data and ULEB128 across packets");
    // Actual domain factory, clone, Log and object ownership use the same handler.
    auto domain=new_session_handle(make_service("lm"));
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,domain,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto root=msg[8];
    std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=0x8000000e;msg[2]=1;
    msg[8]=1u|(24u<<16);msg[9]=root;msg[12]=kSFCI;
    t.tls=reinterpret_cast<uint64_t>(msg);cpu.x[0]=domain;svc(cpu,0x21,0);assert(cpu.x[0]==0);
    auto child=msg[12];assert(child && child!=root);
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;msg[6]=2;
    assert(ipc_request(cpu,domain,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto clone=msg[3];
    close(domain);
    std::memset(msg,0,sizeof msg);msg[0]=6|(1u<<16);msg[1]=12;
    auto domain_size=packet(7,{2,1,'d'});
    msg[2]=(uint32_t(domain_size)<<16)|uint32_t((addr>>32)&15)<<12|uint32_t((addr>>36)&7)<<6;
    msg[3]=uint32_t(addr);msg[4]=1u|(16u<<16);msg[5]=child;msg[8]=kSFCI;
    cpu.x[0]=clone;svc(cpu,0x21,0);assert(cpu.x[0]==0 && msg[8]==kSFCO && msg[10]==0);close(clone);
    puts("PASS actual domain factory, cloned logger and service lifetime");
    IpcCtx saved;auto object=std::dynamic_pointer_cast<KSession>(handle_get(logger))->svc;
    auto actual=object->cmds[0];object->cmds[0]=[&](IpcCtx& c) {saved=c;return actual(c);};
    invoke(packet(7,{2,1,'x'}));LoggerState state(1);
    auto call=[&] {return state.consume(saved);};
    // Both auto-select layouts may contain one inactive all-zero counterpart.
    LoggerState alternatives(1);auto copy=saved;copy.a.push_back({});alternatives.consume(copy);
    copy=saved;copy.a=copy.x;copy.x={{}};alternatives.consume(copy);
    auto original_regions=fixture_regions;
    fixture_regions={{addr,25,3,1},{addr+25,0x20000-25,3,1}};alternatives.consume(saved);
    fixture_regions={{addr,25,3,1},{addr+25,0x20000-25,3,0}};
    rejects([&]{alternatives.consume(saved);},"unreadable");fixture_regions=original_regions;
    auto bad=[&](auto change,const char* expected) {
        auto prior=saved;auto packets=state.packets;auto messages=state.messages;
        change();rejects(call,expected);assert(state.packets==packets && state.messages==messages);
        saved=prior;
    };
    bad([&]{saved.x.clear();},"extent");
    bad([&]{saved.x.push_back(saved.x[0]);},"unsupported Log");
    bad([&]{saved.a=saved.x;},"extent");
    bad([&]{saved.b.push_back({addr,24});},"unsupported Log");
    bad([&]{saved.w.push_back({addr,24});},"unsupported Log");
    bad([&]{saved.in_size=4;},"unsupported Log");
    bad([&]{saved.in_copy.push_back(1);},"unsupported Log");
    bad([&]{saved.in_objects.push_back(1);},"unsupported Log");
    bad([&]{saved.x[0]={0,24};},"descriptor");
    bad([&]{saved.x[0].size=23;},"extent");
    bad([&]{saved.x[0].size=65537;},"extent");
    bad([&]{saved.x[0].addr=~uint64_t(0)-8;},"extent");
    bad([&]{saved.x[0].addr=1;},"unreadable");
    fixture_regions[0].perm=0;rejects(call,"unreadable");fixture_regions[0].perm=3;
    auto malformed=[&](uint8_t flags,std::vector<uint8_t> payload,const char* expected) {
        saved.x[0]={addr,packet(flags,payload)};rejects(call,expected);assert(state.packets==0);
    };
    malformed(3,{2,0},"header");malformed(15,{2,0},"header");
    malformed(7,{11,0},"chunk key");malformed(7,{0x80},"chunk key");
    malformed(7,{2,0x80},"chunk size");malformed(7,{2,4,'a'},"chunk data");
    malformed(7,std::vector<uint8_t>(10,0xff),"overflow");
    malformed(6,{2,0},"sequence");
    saved.x[0]={addr,packet(7,{2,0})};memory[18]=5;rejects(call,"header");memory[18]=1;
    memory[17]=1;rejects(call,"header");memory[17]=0;
    st<uint32_t>(addr+20,999);rejects(call,"length mismatch");
    auto legitimate=saved;
    // Serialized W descriptors must reach the logger, including a null W entry.
    rejects([&]{
        std::memset(msg,0,sizeof msg);msg[0]=4|(1u<<16)|(1u<<28);msg[1]=8;
        auto size=packet(7,{2,0});msg[2]=(uint32_t(size)<<16)|uint32_t((addr>>32)&15)<<12|uint32_t((addr>>36)&7)<<6;
        msg[3]=uint32_t(addr);msg[8]=kSFCI;t.tls=reinterpret_cast<uint64_t>(msg);cpu.x[0]=logger;svc(cpu,0x21,0);
    },"unsupported Log");
    saved=legitimate;
    puts("PASS malformed requests atomic with checked VM extents, headers, ULEB128 and descriptors");
    saved.x[0]={addr,packet(5,{2,3,'a'})};call();auto n=state.packets;
    rejects(call,"sequence");assert(state.packets==n);
    saved.x[0]={addr,packet(6,{'b','c'})};memory[18]=2;rejects(call,"metadata mismatch");memory[18]=1;call();
    assert(state.pending.empty() && state.pending_bytes==0 && state.messages==1);
    for(unsigned i=0;i<80;i++) {saved.x[0]={addr,packet(7,{2,0})};call();}
    assert(state.sink.size()==64 && state.evicted==17 && state.sink_bytes<=state.kLimit);
    for(unsigned i=0;i<16;i++) {saved.x[0]={addr,packet(5,{2,0},100+i)};call();}
    saved.x[0]={addr,packet(5,{2,0},999)};rejects(call,"stream limit");
    LoggerState large(1);std::vector<uint8_t> payload(40000,'r');payload[0]=2;payload[1]=0xbc;payload[2]=0xb8;payload[3]=2;
    // ULEB length 39996, fully contained in one packet.
    saved.x[0]={addr,packet(7,payload)};large.consume(saved);large.consume(saved);
    assert(large.sink.size()==1 && large.evicted==1 && large.sink_bytes==40000);
    saved.x[0]={addr,packet(5,payload)};large.consume(saved);
    saved.x[0]={addr,packet(4,payload)};rejects([&]{large.consume(saved);},"memory limit");
    puts("PASS bounded sink and streams with eviction, byte limits and session-owned state");
    IpcCtx unknown;unknown.cmd=1;rejects([&]{object->handle(unknown);},"strict IPC missing command");
    auto unauth=saved;unauth=IpcCtx{};rejects([&]{state.consume(unauth);},"does not own");
    guest_process->live.store(false);rejects(call,"does not own");guest_process->live.store(true);
    for(const auto& entry:fixture_logs) assert(entry.find("LOGGER_PRIVATE_SECRET")==std::string::npos);
    close(logger);close(factory);close(main_handle);kstate::t_self=nullptr;
    munmap(memory,0x20000);
    puts("PASS strict unsupported commands and ownership including process retirement");
}
