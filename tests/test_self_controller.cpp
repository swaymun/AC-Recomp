// Original command-13/16/91 acceptance fixture. The shared host scaffold compiles full
// shipped kernel, IPC and service sources; it provides no alternate dispatcher.
#include "kernel-host.h"

// Command 13 uses the same shipped kernel/parser/service as command 91.
void focus_mode_tests() {
    using Mode = FocusHandlingMode;
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto send=[&](uint32_t session,uint32_t type,uint32_t cmd,uint32_t flags=0,
                  uint32_t object=0,bool payload=true) {
        std::memset(msg,0,sizeof msg);msg[0]=type;msg[1]=payload?9:8;
        msg[4]=kSFCI;msg[6]=cmd;msg[8]=flags;
        if(object) {
            msg[1]=payload?13:12;msg[4]=1u|((payload?19u:16u)<<16);msg[5]=object;
            msg[8]=kSFCI;msg[10]=cmd;msg[12]=flags;
        }
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto set=[&](uint32_t session,uint32_t flags,uint32_t object=0) {
        auto count=kstate::g_handles.size();
        assert(send(session,object?6:4,13,flags,object)==0);
        assert(msg[0]==0 && msg[1]==(object?14u:10u));
        unsigned raw=object?8:4;
        assert(msg[raw]==kSFCO);
        for(unsigned i=2;i<64;i++) if(i!=raw) assert(msg[i]==0);
        assert(kstate::g_handles.size()==count);
    };
    auto before=kstate::g_handles.size();
    auto service=self_controller();auto session=new_session_handle(service);
    auto common=new_session_handle(common_state_getter());
    assert(send(session,4,91)==0);auto tick_event=msg[3];
    assert(wait(tick_event,0)==0 && op(0x17,tick_event)==0);
    assert((applet().messages==std::deque<uint32_t>{15,30,31}));
    assert(send(common,4,0)==0);auto event=msg[3];assert(wait(event,0)==0);
    // Disable focus delivery, not the other two real initialization messages.
    set(session,0x00010000); // notify=0, background=0, suspend=1
    assert(!applet().focus_notify && (applet().focus_mode == Mode::SuspendHomeSleep));
    assert(send(common,4,1)==0 && msg[8]==30);
    assert(send(common,4,1)==0 && msg[8]==31);
    assert(send(common,4,1)==0 && msg[6]==kAmNoMessage);
    assert(wait(event,0)==0xEA01);
    assert((applet().messages==std::deque<uint32_t>{15}));
    // Restore pending delivery, then repetition must not synthesize a new change.
    for(int i=0;i<3;i++) set(session,0x00000101); // notify=1, background=1, suspend=0
    assert(applet().focus_notify && (applet().focus_mode == Mode::NoSuspend) && wait(event,0)==0);
    assert(send(common,4,1)==0 && msg[8]==15);
    assert(wait(event,0)==0xEA01);
    set(session,0x00000101);
    assert(send(common,4,1)==0 && msg[6]==kAmNoMessage);
    assert(send(common,4,9)==0 && msg[8]==1); // stays InFocus for either policy
    // All canonical boolean triples, independently decoded; background has no
    // behavioral effect in the pinned emulator. Padding is not a fourth flag.
    for(uint32_t notify:{0u,1u}) for(uint32_t background:{0u,1u}) for(uint32_t suspend:{0u,1u}) {
        set(session,notify|(background<<8)|(suspend<<16)|0xa5000000u);
        assert(applet().focus_notify==bool(notify) && applet().focus_mode==(suspend?Mode::SuspendHomeSleep:Mode::NoSuspend));
        assert(applet().messages.empty() && wait(event,0)==0xEA01);
        assert(wait(tick_event,0)==0xEA01);
    }
    puts("PASS command 13 CMIF three-byte policy, result-only output, notification gating and repetition");

    assert(send(session,5,0)==0);auto root=msg[8];assert(root==1);
    assert(send(session,5,2)==0);auto clone=msg[3];assert(clone!=session);
    set(session,0x00010000,root);
    assert(!applet().focus_notify && (applet().focus_mode == Mode::SuspendHomeSleep));
    assert(send(session,2,0)==0xF601);close(session);service.reset();
    set(clone,0x00000101,root);
    assert(applet().focus_notify && (applet().focus_mode == Mode::NoSuspend));
    assert(send(clone,15,0)==0xF601);close(clone);
    // Policy belongs to the application, not a newly acquired controller object.
    auto fresh=self_controller();auto next=new_session_handle(fresh);
    assert(applet().focus_notify && (applet().focus_mode == Mode::NoSuspend));
    set(next,0x00010000);
    assert(!applet().focus_notify && (applet().focus_mode == Mode::SuspendHomeSleep));
    // Registered appletOE -> proxy -> self factory reaches that same applet.
    auto top=new_session_handle(make_service("appletOE"));
    assert(send(top,4,0)==0);auto proxy=msg[3];
    assert(send(proxy,4,1)==0);auto other=msg[3];close(top);close(proxy);
    set(other,0x00000101);close(other);
    assert(applet().focus_notify && (applet().focus_mode == Mode::NoSuspend));
    std::memset(msg,0,sizeof msg);msg[0]=29;msg[1]=1;msg[2]=0x00010000;
    assert(ipc_request(cpu,next,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);
    assert(msg[0]==29 && msg[1]==1);
    for(unsigned i=2;i<64;i++) assert(msg[i]==0);
    assert(!applet().focus_notify && (applet().focus_mode == Mode::SuspendHomeSleep));
    puts("PASS command 13 domain clone, factory and applet-owned lifetime, TIPC result-only output");

    auto malformed=[&](auto call) {
        bool stopped=false;
        try {call();} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="ISelfController SetFocusHandlingMode: malformed boolean payload";
        }
        assert(stopped && !applet().focus_notify && (applet().focus_mode == Mode::SuspendHomeSleep));
        assert(applet().messages.empty() && wait(event,0)==0xEA01);
    };
    malformed([&]{send(next,4,13,0,0,false);});
    for(uint32_t flags:{2u,0x200u,0x20000u,0xff0000u}) malformed([&]{send(next,4,13,flags);});
    // Supported service API exercises precise sub-word truncation that the
    // HIPC word-count parser cannot represent. No alternate dispatcher is used.
    uint8_t bytes[3]={1,1,0};
    for(size_t n:{0u,1u,2u}) malformed([&]{IpcCtx c;c.cmd=13;c.in=bytes;c.in_size=n;fresh->handle(c);});
    malformed([&]{IpcCtx c;c.cmd=13;c.in_size=3;fresh->handle(c);});
    malformed([&]{std::memset(msg,0,sizeof msg);msg[0]=29;ipc_request(cpu,next,reinterpret_cast<uint64_t>(msg),sizeof msg);});
    assert(send(0xdead,4,13)==0xE401);
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    assert(send(wrong,4,13)==0xE401);close(wrong);
    assert(send(next,5,0)==0);root=msg[8];
    assert(send(next,6,13,0,root+99)==0xF601);
    for(uint32_t cmd:{11u,12u,14u,15u,17u,90u,0xffffffffu}) {
        bool stopped=false;
        try {send(next,6,cmd,0,root);} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="strict IPC missing command: service=ISelfController command="+std::to_string(cmd);
        }
        assert(stopped);
    }
    assert(send(next,2,0)==0xF601);
    assert(send(next,6,13,0,root)==0xF601);close(next);fresh.reset();
    assert(send(next,4,13)==0xE401);
    assert(wait(tick_event,0)==0xEA01);close(tick_event);
    close(event);close(common);
    assert(kstate::g_handles.size()==before);
    puts("PASS command 13 malformed payloads and targets, atomic rejection, strict adjacent and unknown gates");
}

// Domain byte sizes are representable at the real HIPC dispatcher, unlike
// sub-word non-domain truncation. All malformed requests target a live object.
void domain_framing_tests() {
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto session=new_session_handle(self_controller());
    auto common=new_session_handle(common_state_getter());
    auto dispatch=[&](uint64_t size=sizeof msg) {
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),size);
    };
    msg[0]=5;msg[1]=8;msg[4]=kSFCI;assert(dispatch()==0);auto root=msg[8];
    auto request=[&](uint32_t size=19,uint32_t words=13,uint32_t objects=0) {
        std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=words;
        msg[4]=1u|(objects<<8)|(size<<16);msg[5]=root;
        msg[8]=kSFCI;msg[10]=13;
        msg[12]=0x00000101; // tempting padding: notify on, suspend off
    };
    // Seed meaningful pending messages, then set policy through real dispatch.
    applet().messages={15,30,31};
    request();msg[12]=0x00010000;assert(dispatch()==0);
    alignas(16) uint32_t query[64]{};
    query[0]=4;query[1]=8;query[4]=kSFCI;
    assert(ipc_request(cpu,common,reinterpret_cast<uint64_t>(query),sizeof query)==0);
    auto event=query[3];
    auto rejected=[&](auto call) {
        auto messages=applet().messages;auto ready=wait(event,0);
        auto handles=kstate::g_handles.size();
        auto objects=std::dynamic_pointer_cast<KSession>(handle_get(session))->dom->objects.size();
        bool failed=false;
        try {failed=call()!=0;} catch(const std::runtime_error& e) {
            auto error=std::string(e.what());
            failed=error=="ipc: malformed request framing" ||
                error=="ISelfController SetFocusHandlingMode: malformed boolean payload";
        }
        if (!failed) std::fprintf(stderr,"domain rejection failed: notify=%u suspend=%u\n",
                                  unsigned(applet().focus_notify),unsigned((applet().focus_mode == FocusHandlingMode::SuspendHomeSleep)));
        assert(failed);
        assert(!applet().focus_notify && (applet().focus_mode == FocusHandlingMode::SuspendHomeSleep));
        assert(applet().messages==messages && wait(event,0)==ready);
        assert(kstate::g_handles.size()==handles);
        assert(std::dynamic_pointer_cast<KSession>(handle_get(session))->dom->objects.size()==objects);
    };
    // Original defect: a CMIF header alone must not expose padding as booleans.
    request(16,12);rejected([&]{return dispatch();});
    for(uint32_t size:{0u,1u,15u,17u,18u,45u,65535u}) {
        request(size);rejected([&]{return dispatch();});
    }
    // Header, alignment, raw-section and actual-storage boundaries.
    for(uint32_t words:{0u,1u,5u,6u,9u,10u,1023u}) {
        request(19,words);rejected([&]{return dispatch();});
    }
    for(uint64_t size:{0ull,4ull,7ull,15ull,31ull,47ull,50ull,59ull}) {
        request();rejected([&]{return dispatch(size);});
    }
    // Give the dispatcher genuinely short allocations, not only a shorter
    // size argument into the larger fixture buffer.
    for(size_t words:{2u,4u,8u,12u,14u}) {
        request();std::vector<uint32_t> short_message(msg,msg+words);
        rejected([&]{return ipc_request(cpu,session,reinterpret_cast<uint64_t>(short_message.data()),words*4);});
    }
    rejected([&]{return ipc_request(cpu,session,0,256);});
    rejected([&]{return ipc_request(cpu,session,~uint64_t(0)-3,8);});
    request();msg[8]=0;rejected([&]{return dispatch();});
    // Object IDs start at CMIF-header + data_size, possibly unaligned. Their
    // entire extent must be in raw data, not a receive-list or backing padding.
    request(19,13,3);rejected([&]{return dispatch();});
    request(19,13,255);rejected([&]{return dispatch();});
    request(19,13,3);msg[1]|=3u<<10;rejected([&]{return dispatch();});
    // Special/PID, handle and descriptor truncations fail before any read/use.
    request();msg[1]|=0x80000000u;msg[2]=1u|(15u<<1)|(15u<<5);
    rejected([&]{return dispatch(16);});
    request();msg[0]|=15u<<16;rejected([&]{return dispatch(32);});
    request();msg[0]|=15u<<20;rejected([&]{return dispatch(32);});
    request();msg[1]|=15u<<10;rejected([&]{return dispatch(64);});
    // Malformed close cannot erase the valid root object before validation.
    request(65535);msg[4]=(msg[4]&~255u)|2u;rejected([&]{return dispatch();});
    // Suppressed focus-only notification must also remain unavailable.
    applet().messages={15};request();msg[12]=0x00010000;assert(dispatch()==0);
    assert(wait(event,0)==0xEA01);
    for(uint32_t size:{16u,17u,18u}) {request(size);rejected([&]{return dispatch();});}
    // A declared byte beyond raw data fails even with ample backing storage.
    request(29);rejected([&]{return dispatch();});
    puts("PASS domain framing command 13 rejects missing/truncated data, extents and object overruns atomically");
    // Exact byte extent: fourth byte is padding, and an input object's bytes
    // cannot replace the third boolean. The existing handler is unchanged.
    request(18,13,1);uint32_t id=0;
    std::memcpy(reinterpret_cast<uint8_t*>(msg)+50,&id,4);
    rejected([&]{return dispatch();});
    request(19,13,1);id=root;
    std::memcpy(reinterpret_cast<uint8_t*>(msg)+51,&id,4);
    assert(dispatch()==0 && applet().focus_notify && (applet().focus_mode == FocusHandlingMode::NoSuspend));
    // A fixture-only observation handler inspects the actual parser's exact input/object
    // separation, with no substitute parser or new production service.
    auto target=std::dynamic_pointer_cast<KSession>(handle_get(session))->svc;
    unsigned calls=0;
    target->cmds[200]=[&](IpcCtx& c) {
        ++calls;assert(c.in_size==3 && c.in_objects==std::vector<uint32_t>{root});
        assert(c.arg<uint8_t>(0)==1 && c.arg<uint8_t>(1)==1 && c.arg<uint8_t>(2)==0);
        return 0u;
    };
    request(19,13,1);msg[10]=200;
    std::memcpy(reinterpret_cast<uint8_t*>(msg)+51,&root,4);
    assert(dispatch()==0 && calls==1);
    // A word-aligned user buffer need not have a 16-byte aligned base. CMIF
    // aligns offsets relative to that base for both request and response.
    alignas(16) uint32_t shifted[65]{};
    request();std::memcpy(shifted+1,msg,sizeof msg);
    assert(ipc_request(cpu,session,reinterpret_cast<uint64_t>(shifted+1),sizeof msg)==0);
    assert(shifted[9]==kSFCO && applet().focus_notify && (applet().focus_mode == FocusHandlingMode::NoSuspend));
    // Exact raw end: 32 data bytes after the domain header end at byte 64.
    request(32,14);msg[10]=13;
    for(unsigned i=16;i<64;i++) msg[i]=0xa5a5a5a5;
    assert(dispatch(64)==0 && applet().focus_notify && (applet().focus_mode == FocusHandlingMode::NoSuspend));
    for(unsigned i=16;i<64;i++) assert(msg[i]==0xa5a5a5a5);
    // Exact object-table end, including a fourth payload padding byte.
    target->cmds[200]=[&](IpcCtx& c) {
        ++calls;assert(c.in_size==8 && (c.in_objects==std::vector<uint32_t>{root,root}));
        return 0u;
    };
    request(24,14,2);msg[10]=200;msg[14]=root;msg[15]=root;
    assert(dispatch(64)==0 && calls==2);
    target->cmds.erase(200);
    // Preserve domain close's zero-data contract (libnx cmifMakeCloseRequest).
    request(0,8);msg[4]=2;assert(dispatch()==0);
    request();assert(dispatch()==0xF601);
    close(session);close(event);close(common);
    puts("PASS domain framing exact boolean/object boundary and zero-data close");
}

// Exercise command 16 through the shipped parser/dispatcher and singleton applet.
void out_of_focus_tests() {
    using Mode = FocusHandlingMode;
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto send=[&](uint32_t session,uint32_t type,uint32_t cmd,uint32_t flags=0,
                  uint32_t object=0,bool payload=true) {
        std::memset(msg,0,sizeof msg);msg[0]=type;msg[1]=payload?9:8;
        msg[4]=kSFCI;msg[6]=cmd;msg[8]=flags;
        if(object) {
            msg[1]=payload?13:12;msg[4]=1u|((payload?17u:16u)<<16);msg[5]=object;
            msg[8]=kSFCI;msg[10]=cmd;msg[12]=flags;
        }
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto before=kstate::g_handles.size();
    auto service=self_controller();auto session=new_session_handle(service);
    auto common=new_session_handle(common_state_getter());
    assert(applet().focus_mode==Mode::SuspendHomeSleep && applet().focus_notify);
    assert(send(common,4,0)==0);auto event=msg[3];
    auto pending=applet().messages;
    assert((pending==std::deque<uint32_t>{15,30,31}));
    assert(send(session,4,91)==0);auto tick=msg[3];assert(op(0x17,tick)==0);
    auto set=[&](uint32_t target,uint32_t enabled,Mode expected,uint32_t object=0) {
        auto count=kstate::g_handles.size();auto notify=applet().focus_notify;
        assert(send(target,object?6:4,16,enabled,object)==0);
        unsigned raw=object?8:4;
        assert(msg[0]==0 && msg[1]==(object?14u:10u) && msg[raw]==kSFCO);
        for(unsigned i=2;i<64;i++) if(i!=raw) assert(msg[i]==0);
        assert(kstate::g_handles.size()==count && applet().focus_mode==expected);
        assert(applet().focus_notify==notify && applet().messages==pending);
        assert(wait(event,0)==0 && wait(tick,0)==0xEA01);
        assert(send(common,4,9)==0 && msg[8]==1); // existing foreground remains InFocus
    };
    // Independent expected transition table from the pinned lifecycle contract.
    // Obtain each start mode using real commands, never direct state assignment.
    for(auto initial:{Mode::SuspendHomeSleep,Mode::NoSuspend,Mode::AlwaysSuspend}) {
        for(uint32_t enabled:{0u,1u}) {
            assert(send(session,4,13,initial==Mode::NoSuspend?1:0x10001)==0);
            if(initial==Mode::AlwaysSuspend) set(session,1,Mode::AlwaysSuspend);
            else if(initial==Mode::SuspendHomeSleep) set(session,0,Mode::SuspendHomeSleep);
            assert(applet().focus_mode==initial);
            auto expected=enabled?Mode::AlwaysSuspend:
                          initial==Mode::NoSuspend?Mode::NoSuspend:Mode::SuspendHomeSleep;
            for(int repeat=0;repeat<3;repeat++) set(session,enabled|0xa5ff0000u,expected);
        }
    }
    // Command 16 must also preserve disabled notification policy and its queue.
    assert(send(session,4,13,0x10000)==0 && !applet().focus_notify);
    set(session,1,Mode::AlwaysSuspend);
    set(session,0,Mode::SuspendHomeSleep);
    assert(send(session,4,13,0x10001)==0 && applet().focus_notify);
    // Command 13 must preserve AlwaysSuspend on true, and leave it on false.
    set(session,1,Mode::AlwaysSuspend);
    assert(send(session,4,13,0x10001)==0 && applet().focus_mode==Mode::AlwaysSuspend);
    assert(send(session,4,13,1)==0 && applet().focus_mode==Mode::NoSuspend);
    set(session,0,Mode::NoSuspend);
    puts("PASS command 16 CMIF single-byte result-only, all mode transitions, padding, repetition and foreground effect");

    assert(send(session,5,0)==0);auto root=msg[8];
    assert(send(session,5,2)==0);auto clone=msg[3];
    set(session,1,Mode::AlwaysSuspend,root);
    assert(send(session,2,0)==0xF601);close(session);service.reset();
    set(clone,0,Mode::SuspendHomeSleep,root);
    assert(send(clone,15,0)==0xF601);close(clone);
    auto fresh=self_controller();auto next=new_session_handle(fresh);
    assert(applet().focus_mode==Mode::SuspendHomeSleep);
    set(next,1,Mode::AlwaysSuspend);
    auto top=new_session_handle(make_service("appletOE"));
    assert(send(top,4,0)==0);auto proxy=msg[3];
    assert(send(proxy,4,1)==0);auto other=msg[3];close(top);close(proxy);
    set(other,0,Mode::SuspendHomeSleep);close(other);
    auto count=kstate::g_handles.size();
    std::memset(msg,0,sizeof msg);msg[0]=32;msg[1]=1;msg[2]=0x00ff0001;
    assert(ipc_request(cpu,next,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);
    assert(msg[0]==32 && msg[1]==1);
    for(unsigned i=2;i<64;i++) assert(msg[i]==0);
    assert(applet().focus_mode==Mode::AlwaysSuspend && kstate::g_handles.size()==count);
    assert(applet().messages==pending && applet().focus_notify);
    assert(wait(event,0)==0 && wait(tick,0)==0xEA01);
    puts("PASS command 16 domain clone, shared policy across factory/service lifetimes and TIPC serialization");

    auto malformed=[&](auto call) {
        auto count=kstate::g_handles.size();bool stopped=false;
        try {call();} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="ISelfController SetOutOfFocusSuspendingEnabled: malformed boolean payload";
        }
        assert(stopped && applet().focus_mode==Mode::AlwaysSuspend);
        assert(applet().focus_notify && applet().messages==pending);
        assert(kstate::g_handles.size()==count && wait(event,0)==0 && wait(tick,0)==0xEA01);
    };
    malformed([&]{send(next,4,16,0,0,false);});
    for(uint32_t invalid:{2u,255u}) malformed([&]{send(next,4,16,invalid);});
    uint8_t byte=0;
    malformed([&]{IpcCtx c;c.cmd=16;c.in=&byte;c.in_size=0;fresh->handle(c);});
    malformed([&]{IpcCtx c;c.cmd=16;c.in_size=1;fresh->handle(c);});
    malformed([&]{std::memset(msg,0,sizeof msg);msg[0]=32;ipc_request(cpu,next,reinterpret_cast<uint64_t>(msg),sizeof msg);});
    assert(send(0xdead,4,16)==0xE401);
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    assert(send(wrong,4,16)==0xE401);close(wrong);
    assert(send(next,5,0)==0);root=msg[8];
    assert(send(next,6,16,0,root+99)==0xF601);
    for(uint32_t cmd:{14u,15u,17u,18u,90u,0xffffffffu}) {
        bool stopped=false;
        try {send(next,6,cmd,0,root);} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="strict IPC missing command: service=ISelfController command="+std::to_string(cmd);
        }
        assert(stopped && applet().focus_mode==Mode::AlwaysSuspend && applet().messages==pending);
    }
    assert(send(next,2,0)==0xF601);
    assert(send(next,6,16,0,root)==0xF601);close(next);fresh.reset();
    assert(send(next,4,16)==0xE401);
    // Fresh factory still observes applet-owned policy; restore initial mode for
    // command-13's independent real-initial-message notification regression.
    auto last=new_session_handle(self_controller());
    set(last,0,Mode::SuspendHomeSleep);close(last);
    close(tick);close(event);close(common);
    assert(kstate::g_handles.size()==before);
    puts("PASS command 16 atomic malformed rejection, invalid targets and strict adjacent/unknown gates");
}

// Regression for the independently rejected head: domain data_size, not raw
// word padding or input-object bytes, bounds command 16's required boolean.
void out_of_focus_domain_framing_tests() {
    using Mode = FocusHandlingMode;
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto before=kstate::g_handles.size();
    auto session=new_session_handle(self_controller());
    auto common=new_session_handle(common_state_getter());
    auto dispatch=[&](uint32_t target) {
        return ipc_request(cpu,target,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto plain=[&](uint32_t target,uint32_t cmd,uint32_t value=0) {
        std::memset(msg,0,sizeof msg);msg[0]=4;msg[1]=9;
        msg[4]=kSFCI;msg[6]=cmd;msg[8]=value;assert(dispatch(target)==0);
    };
    plain(common,0);auto event=msg[3];
    plain(session,91);auto tick=msg[3];
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(dispatch(session)==0);auto root=msg[8];
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;msg[6]=2;
    assert(dispatch(session)==0);auto clone=msg[3];
    auto server=std::dynamic_pointer_cast<KSession>(handle_get(session));
    auto request=[&](uint32_t data_size,uint32_t value,uint32_t objects=0,uint32_t type=6) {
        std::memset(msg,0,sizeof msg);msg[0]=type;msg[1]=14;
        msg[4]=1u|(objects<<8)|(data_size<<16);msg[5]=root;
        msg[8]=kSFCI;msg[10]=16;msg[12]=value;
    };
    auto reject=[&](uint32_t target) {
        auto mode=applet().focus_mode;auto notify=applet().focus_notify;
        auto messages=applet().messages;auto message_state=applet().message_event;
        auto ready=wait(event,0),tick_ready=wait(tick,0);
        auto handles=kstate::g_handles;auto next_handle=kstate::g_next_handle;
        auto objects=server->dom->objects;auto next_object=server->dom->next_object;
        auto svc=server->svc;auto dom=server->dom;bool failed=false;
        try {failed=dispatch(target)!=0;} catch(const std::runtime_error& e) {
            auto error=std::string(e.what());
            failed=error=="ipc: malformed request framing" ||
                error=="ISelfController SetOutOfFocusSuspendingEnabled: malformed boolean payload";
        }
        assert(failed && applet().focus_mode==mode && applet().focus_notify==notify);
        assert(applet().messages==messages && applet().message_event==message_state);
        assert(wait(event,0)==ready && wait(tick,0)==tick_ready);
        assert(kstate::g_handles==handles && kstate::g_next_handle==next_handle);
        assert(server->dom==dom && server->svc==svc && server->domain);
        assert(dom->objects==objects && dom->next_object==next_object);
    };
    // Use a genuine pending focus message so notify=false suppresses readiness.
    applet().messages={15};
    auto policy=new_session_handle(self_controller());
    for(uint32_t notify:{0u,1u}) {
        plain(policy,13,notify|0x10000);
        for(uint32_t initial:{0u,1u}) {
            plain(policy,16,initial);
            assert(applet().focus_mode==(initial?Mode::AlwaysSuspend:Mode::SuspendHomeSleep));
            if(initial==1 && wait(tick,0)==0) assert(op(0x17,tick)==0); // both readiness states
            for(uint32_t target:{session,clone}) for(uint32_t type:{4u,6u}) {
                // Opposite valid booleans in padding would mutate this policy.
                request(16,initial?0:1,0,type);reject(target);
                // The first input-object ID is also a tempting true boolean.
                request(16,root,1,type);reject(target);
                request(16,0xa5000000u,2,type);msg[13]=root;reject(target);
                // Declared exact boolean, but invalid value or invalid extents.
                for(uint32_t bad:{2u,255u}) {request(17,bad,0,type);reject(target);}
                request(15,0,0,type);reject(target);
                request(65535,0,0,type);reject(target);
                request(17,0,255,type);reject(target);
                request(17,0,0,type);msg[5]=root+99;reject(target);
            }
            // Valid one-byte true/false with unaligned object table and padding
            // are accepted through both shared domain handles and request types.
            for(uint32_t target:{session,clone}) for(uint32_t type:{4u,6u}) for(uint32_t value:{1u,0u}) {
                request(17,value|0xa5a50000u,1,type);
                std::memcpy(reinterpret_cast<uint8_t*>(msg)+49,&root,4);
                auto handles=kstate::g_handles;auto objects=server->dom->objects;
                auto tick_ready=wait(tick,0);auto messages=applet().messages;
                assert(dispatch(target)==0 && msg[0]==0 && msg[1]==14 && msg[8]==kSFCO);
                for(unsigned i=2;i<64;i++) if(i!=8) assert(msg[i]==0);
                assert(wait(tick,0)==tick_ready && applet().messages==messages);
                assert(applet().focus_mode==(value?Mode::AlwaysSuspend:Mode::SuspendHomeSleep));
                assert(kstate::g_handles==handles && server->dom->objects==objects);
                assert(applet().focus_notify==bool(notify) && wait(event,0)==(notify?0u:0xEA01u));
            }
        }
    }
    close(policy);close(clone);close(session);close(tick);close(event);close(common);
    assert(kstate::g_handles.size()==before);
    puts("PASS command 16 domain header-only padding/object rejection preserves policy, notifications, events, handles and membership");
}

int main() {
    KThread thread; kstate::t_self=&thread;
    CPU cpu;
    alignas(16) uint32_t msg[64]{};
    auto send=[&](uint32_t session,uint32_t type,uint32_t cmd,uint32_t object=0) {
        std::memset(msg,0,sizeof msg); msg[0]=type; msg[1]=8;
        msg[4]=kSFCI; msg[6]=cmd;
        if(object) {
            msg[1]=12;msg[4]=1u|(16u<<16);msg[5]=object;
            msg[8]=kSFCI;msg[10]=cmd;
        }
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto acquire=[&](uint32_t session,uint32_t object=0) {
        assert(send(session,object?6:4,91,object)==0);
        assert(msg[0]==0 && msg[1]==(0x80000000u|(object?12u:8u)));
        assert(msg[2]==2); // exactly one HIPC copy, zero move, no PID
        auto raw=object?8:4;
        assert(msg[raw]==kSFCO && msg[raw+1]==0 && msg[raw+2]==0 && msg[raw+3]==0);
        if(object) assert(msg[4]==0); // no domain object/scalar output
        return msg[3];
    };
    assert(send(0xdead,4,91)==0xE401);
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    assert(send(wrong,4,91)==0xE401);close(wrong);
    for(bool server_first:{false,true}) {
        auto before=kstate::g_handles.size();
        auto service=self_controller();
        std::weak_ptr<Service> service_life=service;
        // Factory construction creates no kernel handles; lazy state is created
        // inside command 91, as the full service source shows.
        assert(kstate::g_handles.size()==before);
        auto session=new_session_handle(service); service.reset();
        assert(kstate::g_handles.size()==before+1);
        auto first=acquire(session);
        auto event=std::dynamic_pointer_cast<KEvent>(handle_get(first));
        assert(event && event->endpoint==EventEndpoint::Readable);
        std::weak_ptr<EventState> life=event->state;
        assert(wait(first,0)==0 && wait(first,0)==0); // initial signal; manual reset
        assert(op(0x11,first)==0xE401 && wait(first,0)==0);
        auto initial_copy=acquire(session);
        assert(initial_copy!=first && wait(initial_copy,0)==0);
        assert(op(0x17,initial_copy)==0 && wait(first,0)==0xEA01);
        close(initial_copy);
        assert(op(0x17,first)==0xFA01);
        auto second=acquire(session);
        auto second_event=std::dynamic_pointer_cast<KEvent>(handle_get(second));
        assert(second!=first && second_event->state==event->state);
        assert(wait(first,0)==0xEA01 && wait(second,0)==0xEA01);
        assert(op(0x11,second)==0xE401); // acquisition did not re-signal
        // The actual CreateEvent writable endpoint is rejected by ResetSignal.
        CPU pair; svc(pair,0x45,0);
        assert(op(0x17,pair.x[1])==0xE401 && wait(pair.x[1],0)==0xE401);
        close(pair.x[1]);close(pair.x[2]);
        event.reset();second_event.reset();
        if(server_first) {
            assert(send(session,2,0)==0xF601 && service_life.expired()); close(session);
            assert(!life.expired() && wait(first,0)==0xEA01);
            close(first); assert(!life.expired()); close(second); assert(life.expired());
        } else {
            close(first);close(second);assert(!life.expired());
            auto third=acquire(session);assert(wait(third,0)==0xEA01);
            close(third);assert(!life.expired());
            assert(send(session,15,0)==0xF601 && service_life.expired());close(session);
            assert(life.expired());
        }
        assert(op(0x16,first)==0xE401 && wait(first,0)==0xE401);
        assert(op(0x11,first)==0xE401 && op(0x17,first)==0xE401);
    }
    puts("PASS command 91 actual CMIF copied readable event, initial signal, reset/reacquire and both close orders");
    // The real startup uses a domain request (type 6). CMIF clones retain the
    // same service, so closing the first session must not create a fresh signal.
    {
        auto service=self_controller();std::weak_ptr<Service> service_life=service;
        auto session=new_session_handle(service);service.reset();
        assert(send(session,5,0)==0);auto root=msg[8];assert(root==1);
        assert(send(session,5,2)==0);auto clone=msg[3];assert(clone!=session);
        auto first=acquire(session,root);
        std::weak_ptr<EventState> life;
        { auto event=std::dynamic_pointer_cast<KEvent>(handle_get(first));life=event->state; }
        assert(wait(first,0)==0 && op(0x17,first)==0);
        assert(send(session,2,0)==0xF601);close(session);assert(!service_life.expired());
        auto second=acquire(clone,root);assert(wait(second,0)==0xEA01);
        { auto event=std::dynamic_pointer_cast<KEvent>(handle_get(second));assert(event->state==life.lock()); }
        assert(send(clone,15,0)==0xF601);close(clone);assert(service_life.expired());
        close(second);assert(!life.expired());close(first);assert(life.expired());
    }
    puts("PASS actual domain type 6 and CMIF clone share event state across session close");
    // The factory's new service lifetime has its own lazy event, initially signaled.
    auto service=self_controller();auto session=new_session_handle(service);
    auto first=acquire(session);assert(wait(first,0)==0);
    for(uint32_t cmd:{90u,0xffffffffu}) {
        bool stopped=false;
        try { send(session,4,cmd); } catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="strict IPC missing command: service=ISelfController command="+std::to_string(cmd);
        }
        assert(stopped);
    }
    close(first);close(session);service.reset();
    puts("PASS actual invalid handles, strict command 90 and unknown IPC gates");
    out_of_focus_tests();
    focus_mode_tests();
    domain_framing_tests();
    out_of_focus_domain_framing_tests();
    kstate::t_self=nullptr;
}

// Shared protocol declarations used to form the fixture's host-boundary ipc.h.
#if 0
struct Buffer {
    uint64_t addr = 0, size = 0;
};

struct Service;

struct IpcCtx {
    CPU* cpu = nullptr;
    uint32_t cmd = 0;
    uint32_t type = 0;
    const uint8_t* in = nullptr;  // raw arguments (after the SFCI header)
    size_t in_size = 0;
    std::vector<uint32_t> in_copy, in_move;
    uint64_t pid = 0;
    std::vector<Buffer> a, b, x, c;  // send, receive, pointer (X), receive list (C)
    std::vector<uint32_t> in_objects;  // domain objects passed in

    std::vector<uint8_t> out;
    std::vector<uint32_t> out_copy, out_move;
    std::vector<std::shared_ptr<Service>> out_objects;

    template <typename T>
    T arg(size_t off) const {
        T v{};
        if (off + sizeof(T) <= in_size) std::memcpy(&v, in + off, sizeof(T));
        return v;
    }
    template <typename T>
    void push(const T& v) {
        size_t o = out.size();
        out.resize(o + sizeof(T));
        std::memcpy(out.data() + o, &v, sizeof(T));
    }
    void push_object(std::shared_ptr<Service> s) { out_objects.push_back(std::move(s)); }
    // Buffer of either kind for "the n-th input/output buffer" (A or X / B or C).
    Buffer in_buf(size_t n) const { return n < a.size() && a[n].addr ? a[n] : (n < x.size() ? x[n] : Buffer{}); }
    Buffer out_buf(size_t n) const { return n < b.size() && b[n].addr ? b[n] : (n < c.size() ? c[n] : Buffer{}); }
};

struct Service : std::enable_shared_from_this<Service> {
    std::string name;
    explicit Service(std::string n) : name(std::move(n)) {}
    virtual ~Service() = default;
    // Production Service::handle is compiled below with NX_ASTRAL_STRICT.
    virtual uint32_t handle(IpcCtx& ctx);
    std::map<uint32_t, std::function<uint32_t(IpcCtx&)>> cmds;
};

using ServiceFactory = std::function<std::shared_ptr<Service>()>;
void register_service(const std::string& name, ServiceFactory f);
std::shared_ptr<Service> make_service(const std::string& name);

struct ServiceRegistrar {
    ServiceRegistrar(const char* name, ServiceFactory f) { register_service(name, std::move(f)); }
};

std::shared_ptr<Service> make_storage(std::vector<uint8_t> data);
std::shared_ptr<Service> preselected_user_storage();


#endif
