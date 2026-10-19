// Original fixture: actual serialized kernel/IPC dispatch, synthetic metadata.
#include "kernel-host.h"
#include <type_traits>

int main() {
    fixture_guest_memory=true;auto main_handle=create_main_thread(4096);
    auto& thread=*self_thread();CPU cpu;alignas(16) uint32_t msg[64]{};
    auto invoke=[&](uint32_t session,uint32_t cmd,bool factory=false,uint32_t object=0,uint64_t supplied=0,uint64_t reserved=0) {
        std::memset(msg,0,sizeof msg);msg[0]=object?6:4;
        unsigned raw=factory?8:4;
        msg[1]=(factory?0x8000000au:8u)+(object?4u:0u);
        if(factory) {msg[2]=1;msg[3]=uint32_t(supplied);msg[4]=uint32_t(supplied>>32);}
        if(object) {msg[raw]=1u|((factory?24u:16u)<<16);msg[raw+1]=object;raw+=4;}
        msg[raw]=kSFCI;msg[raw+2]=cmd;
        if(reserved) {msg[raw+4]=uint32_t(reserved);if(!factory) msg[1]+=2;}
        thread.tls=reinterpret_cast<uint64_t>(msg);cpu.x[0]=session;svc(cpu,0x21,0);
        assert(cpu.x[0]==0);assert(msg[object?8:4]==kSFCO);
    };
    auto rejects=[&](auto call,const std::string& expected) {
        auto handles=kstate::g_handles.size();bool caught=false;
        try {call();} catch(const std::runtime_error& e) {caught=e.what()==expected;}
        assert(caught && kstate::g_handles.size()==handles);
    };
    auto binding=process_control_metadata(1);
    assert(!process_control_metadata(0) && !process_control_metadata(2));
    static_assert(std::is_const_v<std::remove_reference_t<decltype(*binding)>>);
    auto before=kstate::g_handles.size();
#if defined(NX_TEST_NO_CONTROL) || defined(NX_TEST_BAD_CONTROL)
    auto invalid_factory=new_session_handle(make_service("pctl:a"));
    rejects([&]{invoke(invalid_factory,1,true);},"parental: missing or unsupported process control metadata");
    close(invalid_factory);close(main_handle);kstate::t_self=nullptr;
    puts("PASS parental missing/unsupported metadata rejects before publishing an object");return 0;
#endif
    assert(binding && binding->application_id==0x1234000000000000ull);
    for(const char* name:{"pctl","pctl:s","pctl:a","pctl:r"}) {
        auto factory=new_session_handle(make_service(name));
        // Parsed descriptor bytes are never the factory's process identity.
        for(uint64_t supplied:{0ull,0x4f43465300000000ull}) {
            invoke(factory,1,true,0,supplied);auto child=msg[3];
            assert(child && msg[6]==0 && msg[1]==0x80000008u);
            // Direct IPC entry with no kernel caller cannot use the bound child.
            rejects([&]{
                std::memset(msg,0,sizeof msg);msg[0]=4;msg[1]=8;msg[4]=kSFCI;msg[6]=1;
                ipc_request(cpu,child,reinterpret_cast<uint64_t>(msg),sizeof msg);
            },"parental: caller does not own bound application context");
            rejects([&]{invoke(child,1001);},"parental: service not initialized");
            rejects([&]{invoke(child,1,false,0,0,1);},"parental: unsupported Initialize payload");
            invoke(child,1);assert(msg[6]==0);
            rejects([&]{invoke(child,1);},"parental: repeated Initialize unsupported");
            for(uint32_t cmd:{1001u,1403u}) rejects([&]{invoke(child,cmd);},
                "parental: account policy unavailable command="+std::to_string(cmd));
            rejects([&]{invoke(child,999);},"strict IPC missing command: service=IParentalControlService command=999");
            close(child);
        }
        invoke(factory,0,true);auto initialized=msg[3];
        rejects([&]{invoke(initialized,1);},"parental: repeated Initialize unsupported");close(initialized);
        rejects([&]{invoke(factory,1,false);},"parental: factory requires authenticated PID and reserved-zero argument");
        rejects([&]{invoke(factory,1,true,0,0,1);},"parental: factory requires authenticated PID and reserved-zero argument");
        close(factory);
    }
    puts("PASS parental factories actual serialized objects bind immutable authenticated process metadata");
    puts("PASS parental Initialize loads context without granting unknown account permissions");
    auto factory=new_session_handle(make_service("pctl:a"));
    // Convert and clone using actual control dispatch; both sessions share objects.
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,factory,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto root=msg[8];
    invoke(factory,1,true,root);auto object=msg[12];assert(object && object!=root);
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;msg[6]=2;
    assert(ipc_request(cpu,factory,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto clone=msg[3];
    invoke(clone,1,false,object);assert(msg[10]==0);
    rejects([&]{invoke(factory,1,false,object);},"parental: repeated Initialize unsupported");
    close(factory);rejects([&]{invoke(clone,1001,false,object);},"parental: account policy unavailable command=1001");
    rejects([&]{
        std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=12;
        msg[4]=1u|(15u<<16);msg[5]=object;
        ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg);
    },"ipc: malformed request framing");
    close(clone);
    assert(ipc_request(cpu,0xdead,reinterpret_cast<uint64_t>(msg),sizeof msg)==0xE401);
    puts("PASS parental domain clone shared lifetime retains initialized application binding");
    assert(kstate::g_handles.size()==before);
    // A retired authenticated process cannot keep using the captured context.
    auto service=new_session_handle(make_service("pctl:a"));invoke(service,1,true);auto child=msg[3];
    guest_process->live.store(false);assert(!process_control_metadata(1));
    cpu.x[0]=child;svc(cpu,0x21,0);assert(cpu.x[0]==0xE401);
    close(child);close(service);close(main_handle);kstate::t_self=nullptr;
    puts("PASS parental malformed framing and invalid targets remain rejected; retired process has no authority");
}
