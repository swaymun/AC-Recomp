// Original actual-patched kernel/IPC identity fixture. No substitute dispatch.
#include "kernel-host.h"
#include <type_traits>
static_assert(!std::is_constructible_v<KernelCaller,uint64_t,const std::atomic<bool>*>);
static_assert(!std::is_copy_constructible_v<KernelCaller>);
static_assert(!std::is_aggregate_v<IpcCtx>);

int main(int argc, char**) {
    fixture_guest_memory=true;
    auto main_handle=create_main_thread(4096);auto* main=self_thread();
    auto main_owner=handle_get(0xFFFF8001u);assert(main_owner);
    auto process_handle=handle_add(main_owner);
    CPU cpu;alignas(16) uint32_t msg[64]{};
    auto process_id=[&](uint32_t handle,uint32_t expected=0) {
        CPU c;c.x[1]=handle;svc(c,0x24,0);assert(c.x[0]==expected);
        if(expected) assert(c.x[1]==handle);return c.x[1];
    };
    auto pid=process_id(0xFFFF8001u);assert(pid && pid!=0x51);
    assert(process_id(main_handle)==pid && process_id(0xFFFF8000u)==pid);
    assert(process_id(process_handle)==pid);
    assert(op(0x16,0xFFFF8001u)==0xE401 && process_id(0xFFFF8001u)==pid);
    if(argc>1) {
        try {svc(cpu,0x0A,0);} catch(const std::runtime_error&) {}
        assert(main->exited && !handle_get(0xFFFF8001u));
        process_id(main_handle,0xE401);process_id(process_handle,0xE401);
        cpu.x[0]=0xdead;svc(cpu,0x21,0);assert(cpu.x[0]==0xE401);
        close(process_handle);close(main_handle);kstate::t_self=nullptr;
        assert(kstate::g_handles.empty());
        puts("PASS caller last-thread teardown revokes owner and dispatch without public-handle lifetime dependency");
        return 0;
    }
    unsigned calls=0;uint64_t observed=0;bool descriptor=false;
    auto service=std::make_shared<Service>("caller-observer");
    service->cmds[77]=[&](IpcCtx& c) {
        ++calls;observed=c.pid();descriptor=c.has_pid_descriptor();return 0;
    };
    auto session=new_session_handle(service);
    auto request=[&](bool with_pid=true,uint64_t supplied=0,uint32_t object=0,uint32_t type=4,uint32_t command=77) {
        std::memset(msg,0,sizeof msg);msg[0]=type;
        unsigned raw=with_pid?8:4;msg[1]=(with_pid?0x80000000u:0u)+(with_pid?10:8);
        if(with_pid) {msg[2]=1;msg[3]=uint32_t(supplied);msg[4]=uint32_t(supplied>>32);}
        if(object) {msg[1]+=4;msg[raw]=1u|(16u<<16);msg[raw+1]=object;raw+=4;}
        msg[raw]=kSFCI;msg[raw+2]=command;
    };
    auto send=[&](uint32_t path,uint32_t handle,uint64_t size=sizeof msg) {
        if (self_thread()) self_thread()->tls=reinterpret_cast<uint64_t>(msg);
        if(path==0x21) cpu.x[0]=handle;
        else {cpu.x[0]=reinterpret_cast<uint64_t>(msg);cpu.x[1]=size;cpu.x[2]=handle;}
        svc(cpu,path,0);return uint32_t(cpu.x[0]);
    };
    for(auto path:{0x21u,0x22u}) for(uint64_t supplied:{0ull,0x4f43465300000000ull,~0ull,0xfffe000000001234ull}) {
        request(true,supplied);assert(send(path,session)==0 && observed==pid && descriptor);
        request(false);assert(send(path,session)==0 && observed==0 && !descriptor);
    }
    for(auto path:{0x21u,0x22u}) {
        std::memset(msg,0,sizeof msg);msg[0]=16+77;msg[1]=0x80000000u;
        msg[2]=1;msg[3]=0xffffffffu;msg[4]=0xffffffffu;
        assert(send(path,session)==0 && observed==pid && descriptor);
        std::memset(msg,0,sizeof msg);msg[0]=16+77;
        assert(send(path,session)==0 && observed==0 && !descriptor);
    }
    // The parser without the private kernel token must never authenticate bytes.
    request();auto prior_calls=calls;auto next_handle=kstate::g_next_handle;
    bool rejected=false;try {ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg);}
    catch(const std::runtime_error& e) {rejected=std::string(e.what())=="ipc: send-PID requires kernel caller";}
    assert(rejected && calls==prior_calls && kstate::g_next_handle==next_handle);
    IpcCtx direct;direct.cmd=77;assert(direct.pid()==0 && !direct.has_pid_descriptor());
    service->handle(direct);assert(observed==0 && !descriptor);
    puts("PASS caller both SVC paths replace zero/garbage/passthrough slots; absent and direct contexts unauthenticated");

    request(false,0,0,5,0);assert(send(0x21,session)==0);auto root=msg[8];
    request(false,0,0,5,2);assert(send(0x22,session)==0);auto clone=msg[3];
    for(auto handle:{session,clone}) for(auto path:{0x21u,0x22u}) {
        request(true,~0ull,root,6);assert(send(path,handle)==0 && observed==pid && descriptor);
    }
    auto dom=std::dynamic_pointer_cast<KSession>(handle_get(session))->dom;
    auto malformed=[&](uint64_t size) {
        auto bytes=std::vector<uint32_t>(msg,msg+64);auto count=kstate::g_handles.size();
        auto next=kstate::g_next_handle;auto objects=dom->objects;auto object_next=dom->next_object;auto n=calls;
        auto mode=applet().focus_mode;auto messages=applet().messages;
        bool stopped=false;try {send(0x22,session,size);} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="ipc: malformed request framing";
        }
        assert(stopped && std::equal(bytes.begin(),bytes.end(),msg) && calls==n);
        assert(kstate::g_handles.size()==count && kstate::g_next_handle==next);
        assert(dom->objects==objects && dom->next_object==object_next);
        assert(applet().focus_mode==mode && applet().messages==messages);
    };
    request();malformed(8);request();malformed(12);request();malformed(16);
    request();msg[1]=0x800003ffu;malformed(sizeof msg);
    request(true,~0ull,root,6);msg[8]=1u|(15u<<16);malformed(sizeof msg);
    request(true,~0ull,root,6);msg[12]=0;malformed(sizeof msg);
    // TLS path also checks malformed framing before dispatch or mutation.
    request(true,~0ull,root,6);msg[8]=1u|(15u<<16);
    auto bytes=std::vector<uint32_t>(msg,msg+64);prior_calls=calls;
    rejected=false;try {send(0x21,session);} catch(const std::runtime_error& e) {
        rejected=std::string(e.what())=="ipc: malformed request framing";
    }
    assert(rejected && calls==prior_calls && std::equal(bytes.begin(),bytes.end(),msg));
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    for(auto path:{0x21u,0x22u}) for(auto handle:{0xdeadU,wrong}) {
        request();auto n=calls;assert(send(path,handle)==0xE401 && calls==n);
    }
    request(true,0,root+99,6);assert(send(0x22,session)==0xF601);
    puts("PASS caller malformed atomic framing, handles, policy and domain ownership; clones share caller identity");

    CPU child_create;child_create.x[1]=123;child_create.x[3]=456;
    svc(child_create,0x08,0);assert(child_create.x[0]==0);auto child_handle=uint32_t(child_create.x[1]);
    auto child=std::dynamic_pointer_cast<KThread>(handle_get(child_handle));assert(child);
    assert(process_id(child_handle)==pid);
    // Host scheduler scaffold enters the actual thread_main; the guest entry
    // boundary is deliberately fatal, leaving the context available to probe.
    rejected=false;CPU start;start.x[0]=child_handle;
    try {svc(start,0x09,0);} catch(const std::runtime_error&) {rejected=true;}
    assert(rejected && child->started && self_thread()==child.get());
    assert(process_id(0xFFFF8001u)==pid && process_id(main_handle)==pid);
    request(true,~0ull,root,6);child->tls=reinterpret_cast<uint64_t>(msg);
    cpu.x[0]=clone;svc(cpu,0x21,0);assert(cpu.x[0]==0 && observed==pid);
    kstate::t_self=main;
    auto foreign=std::make_shared<KThread>();foreign->self=foreign;foreign->started=true;
    auto foreign_handle=handle_add(foreign);
    for(auto h:{0u,0xdeadU,session,wrong,foreign_handle}) process_id(h,0xE401);
    close(foreign_handle);process_id(foreign_handle,0xE401);
    kstate::t_self=foreign.get();request();assert(send(0x22,session)==0xE401);
    assert(!handle_get(0xFFFF8001u));process_id(main_handle,0xE401);
    kstate::t_self=nullptr;request();assert(send(0x21,session)==0xE401);
    kstate::t_self=main;
    close(process_handle);process_id(process_handle,0xE401);
    puts("PASS caller process handles current-process/current-thread, enrolled child, stale/foreign/invalid rejection");

    auto closing=new_session_handle(service);
    for(auto type:{2u,15u}) {
        if(type==15) closing=new_session_handle(service);
        request(false,0,0,type,0);assert(send(0x22,closing)==0xF601);
        for(auto path:{0x21u,0x22u}) {
            request(true);auto n=calls;assert(send(path,closing)==0xF601 && calls==n);
        }
        close(closing);
        for(auto path:{0x21u,0x22u}) {request();assert(send(path,closing)==0xE401);}
    }
    // The registry, rather than a public handle, owns an executing thread.
    close(main_handle);process_id(main_handle,0xE401);assert(process_id(0xFFFF8001u)==pid);
    // ExitThread revokes execution, but an exited thread still identifies its
    // live owner while another thread survives, as GetProcessId specifies.
    kstate::t_self=child.get();try {svc(cpu,0x0A,0);} catch(const std::runtime_error&) {}
    request();assert(send(0x22,clone)==0xE401);kstate::t_self=main;
    assert(process_id(child_handle)==pid);
    // ExitProcess revokes the entire lifetime before the host exit boundary.
    try {svc(cpu,0x07,0);} catch(const std::runtime_error&) {}
    process_id(main_handle,0xE401);process_id(0xFFFF8001u,0xE401);
    request();assert(send(0x21,clone)==0xE401 && !handle_get(0xFFFF8001u));
    auto stale_process=handle_add(main_owner);process_id(stale_process,0xE401);
    rejected=false;try {create_main_thread(4096);} catch(const std::runtime_error& e) {
        rejected=std::string(e.what())=="kernel: guest relaunch requires loader teardown";
    }
    assert(rejected);close(stale_process);
    // Teardown revokes all synchronous dispatch even while old handles retain
    // service objects. It does not pretend the loader reset this address space.
    for(auto path:{0x21u,0x22u}) for(auto h:{session,clone}) {
        request(true,~0ull,root,6);auto n=calls;auto count=kstate::g_handles.size();
        assert(send(path,h)==0xE401 && calls==n && kstate::g_handles.size()==count);
    }
    close(child_handle);close(wrong);close(session);close(clone);
    kstate::t_self=nullptr;assert(kstate::g_handles.empty());
    puts("PASS caller lifetime ExitThread/ExitProcess revoke; unsupported relaunch rejects pending loader teardown; no handle leaks");
}
