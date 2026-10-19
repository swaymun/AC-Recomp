// Original no-I/O command-10 fixture against the shipped dispatcher and services.
// The pinned contract is AcquireForegroundRights, not an identifier acquisition.
#include "kernel-host.h"

int main() {
    KThread thread; kstate::t_self=&thread;
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto send=[&](uint32_t session,uint32_t type,uint32_t cmd,uint32_t object=0) {
        std::memset(msg,0,sizeof msg);msg[0]=type;msg[1]=8;
        msg[4]=kSFCI;msg[6]=cmd;
        if(object) {
            msg[1]=12;msg[4]=1u|(16u<<16);msg[5]=object;
            msg[8]=kSFCI;msg[10]=cmd;
        }
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto acquire=[&](uint32_t session,uint32_t object=0) {
        auto handles=kstate::g_handles.size();
        assert(send(session,object?6:4,10,object)==0);
        // HIPC: no special header, copy/move handles, domain object or scalar.
        assert(msg[0]==0 && msg[1]==(object?14u:10u));
        auto raw=object?8:4;
        assert(msg[raw]==kSFCO && msg[raw+1]==0 && msg[raw+2]==0 && msg[raw+3]==0);
        for(unsigned i=2;i<64;i++) if(i!=raw) assert(msg[i]==0);
        assert(kstate::g_handles.size()==handles);
    };
    auto handles=kstate::g_handles.size();
    auto service=window_controller();std::weak_ptr<Service> life=service;
    assert(kstate::g_handles.size()==handles);
    auto session=new_session_handle(service);service.reset();
    // Completion must preserve the existing foreground state and notifications.
    auto messages=applet().messages;
    auto probe=std::make_shared<KEvent>(EventEndpoint::Readable, applet().message_event);
    auto signal=probe->signaled();
    for(int i=0;i<3;i++) acquire(session);
    assert(applet().messages==messages && probe->signaled()==signal);
    auto common=common_state_getter();auto cs=new_session_handle(common);
    assert(send(cs,4,9)==0 && msg[8]==1);close(cs);common.reset();
    puts("PASS foreground CMIF no-output serialization, repetition, no handles or notifications");

    // Actual domain conversion and clone control responses; shared service lives
    // past first session Close. No application identity is created or returned.
    assert(send(session,5,0)==0);auto root=msg[8];assert(root==1);
    assert(send(session,5,2)==0);auto clone=msg[3];assert(clone!=session);
    acquire(session,root);acquire(clone,root);
    assert(send(session,2,0)==0xF601);close(session);assert(!life.expired());
    acquire(clone,root);
    assert(send(clone,15,0)==0xF601);close(clone);assert(life.expired());
    auto fresh=window_controller();auto next=new_session_handle(fresh);
    acquire(next);close(next);fresh.reset();
    // Follow the actual registered appletOE -> proxy -> window factory chain.
    auto applet_session=new_session_handle(make_service("appletOE"));
    assert(send(applet_session,4,0)==0);auto proxy=msg[3];
    assert(send(proxy,4,2)==0);auto window=msg[3];
    close(applet_session);close(proxy);acquire(window);
    // Generic shipped TIPC dispatch also has a result-only response here.
    std::memset(msg,0,sizeof msg);msg[0]=26;
    assert(ipc_request(cpu,window,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);
    assert(msg[0]==26 && msg[1]==1);
    for(unsigned i=2;i<64;i++) assert(msg[i]==0);
    close(window);
    puts("PASS foreground domain clone and service lifetime, fresh service has same no-I/O contract");

    // Malformed targets supported by the actual API, without pretending its
    // existing raw-buffer parser validates lengths, magic or arbitrary payloads.
    assert(send(0xdead,4,10)==0xE401);
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    assert(send(wrong,4,10)==0xE401);close(wrong);
    assert(send(next,4,10)==0xE401);
    auto strict=new_session_handle(window_controller());
    assert(send(strict,5,0)==0);root=msg[8];
    assert(send(strict,6,10,root+99)==0xF601);
    for(uint32_t cmd:{0u,2u,11u,12u,20u,21u,0xffffffffu}) {
        bool stopped=false;
        try { send(strict,6,cmd,root); } catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="strict IPC missing command: service=IWindowController command="+std::to_string(cmd);
        }
        assert(stopped);
    }
    acquire(strict,root);assert(send(strict,2,0)==0xF601);
    assert(send(strict,6,10,root)==0xF601);close(strict);
    assert(kstate::g_handles.size()==handles);
    puts("PASS foreground malformed targets and strict unknown commands, closed and stale sessions");
    kstate::t_self=nullptr;
}
