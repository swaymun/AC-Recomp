// Original synthetic requests through the actual patched kernel/CMIF dispatcher.
#include "kernel-host.h"

int main() {
    CPU cpu; alignas(16) uint32_t msg[64]{};
    const auto baseline=kstate::g_handles.size();
    auto send=[&](uint32_t h,uint32_t cmd,std::vector<uint32_t> args={},uint32_t object=0) {
        std::memset(msg,0,sizeof msg);
        msg[0]=object?6:4;msg[1]=(object?12:8)+uint32_t(args.size());
        unsigned raw=4;
        if(object) {msg[4]=1u|((16u+uint32_t(args.size())*4)<<16);msg[5]=object;raw=8;}
        msg[raw]=kSFCI;msg[raw+2]=cmd;
        for(size_t i=0;i<args.size();++i) msg[raw+4+i]=args[i];
        auto rc=ipc_request(cpu,h,reinterpret_cast<uint64_t>(msg),sizeof msg);
        if(!rc) {assert(msg[raw]==kSFCO && msg[raw+2]==0);}
        return rc;
    };
    auto reject=[&](auto fn,const char* text) {
        auto count=kstate::g_handles.size();bool caught=false;
        try{fn();}catch(const std::runtime_error& e){caught=std::string(e.what())==text;}
        assert(caught && count==kstate::g_handles.size());
    };
    auto factory=new_session_handle(make_service("apm"));
    assert(send(factory,0)==0);auto first=msg[3];
    assert(send(factory,0)==0);auto second=msg[3];assert(first!=second);
    reject([&]{send(first,1,{0});},"apm: no acknowledged performance configuration");
    for(uint32_t mode:{0u,1u}) {
        for(uint32_t config:{0x20004u,0x92220007u,0x92220008u}) {
            assert(send(first,0,{mode,config})==0);assert(msg[1]==10 && msg[8]==0);
            assert(send(first,1,{mode})==0);assert(msg[1]==11 && msg[8]==config);
        }
    }
    assert(send(first,0,{0,0x20004})==0);
    assert(send(first,1,{1})==0 && msg[8]==0x92220008);
    reject([&]{send(second,1,{0});},"apm: no acknowledged performance configuration");
    assert(send(second,0,{0,0x92220007})==0);
    assert(send(first,1,{0})==0 && msg[8]==0x20004);
    puts("PASS actual apm OpenSession, Set/Get payload/results, two modes, transitions and independent objects");

    for(uint32_t mode:{2u,0xffffffffu}) {
        reject([&]{send(first,0,{mode,0x20004});},"apm: invalid performance mode");
        reject([&]{send(first,1,{mode});},"apm: invalid performance mode");
    }
    for(uint32_t config:{0u,1u,0x10001u,0x20003u,0x20005u,0x92220009u,0xffffffffu})
        reject([&]{send(first,0,{0,config});},"apm: unsupported performance configuration");
    reject([&]{send(factory,0,{1});},"apm: malformed policy payload");
    reject([&]{send(first,0);},"apm: malformed policy payload");
    reject([&]{send(first,0,{0});},"apm: malformed policy payload");
    reject([&]{send(first,0,{0,0x20004,0});},"apm: malformed policy payload");
    reject([&]{send(first,1);},"apm: malformed policy payload");
    reject([&]{send(first,1,{0,0});},"apm: malformed policy payload");
    for(uint32_t command:{2u,3u,0xffffffffu})
        reject([&]{send(first,command);},("strict IPC missing command: service=ISession command="+std::to_string(command)).c_str());
    assert(send(first,1,{0})==0 && msg[8]==0x20004);
    puts("PASS actual dispatch invalid modes/profiles/payload sizes and unknown commands reject without policy mutation");

    auto service=std::dynamic_pointer_cast<KSession>(handle_get(first))->svc;
    uint32_t args[3]={0,0x20004,0};
    for(uint32_t command:{0u,1u}) {
        const size_t expected=command?4:8;
        for(size_t n=0;n<expected;++n) {
            reject([&]{IpcCtx c;c.cmd=command;c.in=reinterpret_cast<uint8_t*>(args);c.in_size=n;service->handle(c);},"apm: malformed policy payload");
        }
        reject([&]{IpcCtx c;c.cmd=command;c.in_size=expected;service->handle(c);},"apm: malformed policy payload");
        for(unsigned kind=0;kind<7;++kind) {
            reject([&]{IpcCtx c;c.cmd=command;c.in=reinterpret_cast<uint8_t*>(args);c.in_size=expected;
                if(kind==0)c.a.push_back({1,1});if(kind==1)c.b.push_back({1,1});
                if(kind==2)c.x.push_back({1,1});if(kind==3)c.c.push_back({1,1});
                if(kind==4)c.in_objects.push_back(1);if(kind==5)c.in_copy.push_back(1);if(kind==6)c.in_move.push_back(1);
                service->handle(c);},"apm: malformed policy payload");
        }
    }
    puts("PASS actual handlers reject every sub-word truncation, null input and unadvertised descriptors/objects/handles");

    // Convert and clone real IPC session. State belongs to the server object.
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,first,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto object=msg[8];
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;msg[6]=2;
    assert(ipc_request(cpu,first,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto clone=msg[3];
    assert(send(clone,0,{0,0x92220008},object)==0);
    assert(send(first,1,{0},object)==0 && msg[12]==0x92220008);
    // Domain data size is authoritative: backing padding cannot supply a word.
    for(uint32_t n:{0u,1u,3u,4u,7u}) {
        reject([&]{std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=14;
            msg[4]=1u|((16u+n)<<16);msg[5]=object;msg[8]=kSFCI;msg[12]=0;msg[13]=0x20004;
            ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg);},"apm: malformed policy payload");
    }
    reject([&]{std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=14;msg[4]=1u|(65535u<<16);msg[5]=object;
        ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg);},"ipc: malformed request framing");
    assert(send(clone,1,{0},object)==0 && msg[12]==0x92220008);
    assert(send(clone,1,{0},object+100)==0xF601);
    std::memset(msg,0,sizeof msg);msg[0]=2;
    assert(ipc_request(cpu,first,reinterpret_cast<uint64_t>(msg),sizeof msg)==0xF601);close(first);
    assert(send(clone,1,{0},object)==0 && msg[12]==0x92220008);
    // Closing the domain object retires it for every alias of that domain.
    std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=8;msg[4]=2;msg[5]=object;
    assert(ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);
    assert(send(clone,1,{0},object)==0xF601);close(clone);service.reset();
    assert(send(factory,0)==0);auto fresh=msg[3];
    reject([&]{send(fresh,1,{0});},"apm: no acknowledged performance configuration");
    assert(send(0xdead,1,{0})==0xE401);
    close(fresh);close(second);close(factory);assert(kstate::g_handles.size()==baseline);
    puts("PASS actual CMIF domain/clone shared state, malformed framing, close lifetime and fresh-session isolation");
}
