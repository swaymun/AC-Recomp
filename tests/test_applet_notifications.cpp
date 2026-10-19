// Original serialized service acceptance. Full production IPC/kernel/AM code is
// compiled through kernel-host.h; only unrelated host facilities are synthetic.
#include "kernel-host.h"

struct Wire {
    CPU cpu;
    alignas(16) uint32_t words[64]{};
    uint32_t send(uint32_t session, uint32_t cmd, uint32_t value=0,
                  uint32_t object=0, int bytes=1, uint32_t type=4) {
        std::memset(words,0,sizeof words);
        words[0]=type;
        words[1]=bytes ? 9 : 8;
        words[4]=kSFCI; words[6]=cmd; words[8]=value;
        if(object) {
            words[0]=6; words[1]=bytes ? 13 : 12;
            words[4]=1u|(uint32_t(16+bytes)<<16); words[5]=object;
            words[8]=kSFCI; words[10]=cmd; words[12]=value;
        }
        return ipc_request(cpu,session,reinterpret_cast<uint64_t>(words),sizeof words);
    }
    uint32_t acquire(uint32_t session,uint32_t cmd) {
        assert(send(session,cmd,0,0,0)==0); return words[3];
    }
    void set(uint32_t session,uint32_t cmd,uint32_t value,uint32_t object=0,int bytes=1) {
        auto count=kstate::g_handles.size();
        assert(send(session,cmd,value,object,bytes)==0);
        auto raw=object?8u:4u;
        assert(words[0]==0 && words[1]==(object?14u:10u) && words[raw]==kSFCO);
        for(unsigned i=2;i<64;++i) if(i!=raw) assert(words[i]==0);
        assert(kstate::g_handles.size()==count);
    }
};

static void notification_tests() {
    Wire w;
    auto count=kstate::g_handles.size();
    // Exercise the registered factory, application proxy and real object dispatch.
    auto top=new_session_handle(make_service("appletOE"));
    auto proxy=w.acquire(top,0);
    auto self=w.acquire(proxy,1), common=w.acquire(proxy,0);
    close(top);close(proxy);
    auto event=w.acquire(common,0), event2=w.acquire(common,0);
    assert(event!=event2);
    assert(std::dynamic_pointer_cast<KEvent>(handle_get(event))->state==
           std::dynamic_pointer_cast<KEvent>(handle_get(event2))->state);
    assert(applet().operation_notify && applet().performance_notify && !applet().resume_notify);
    assert((applet().messages==std::deque<uint32_t>{15,30,31}));
    assert(wait(event,0)==0 && op(0x11,event)==0xE401);
    // Pending messages survive disabling, matching lifecycle pending bits.
    for(auto cmd:{11u,12u,14u}) w.set(self,cmd,0);
    for(auto message:{15u,30u,31u}) {
        assert(w.send(common,1,0,0,0)==0 && w.words[8]==message);
    }
    assert(w.send(common,1,0,0,0)==0 && w.words[6]==kAmNoMessage);
    assert(wait(event,0)==0xEA01 && wait(event2,0)==0xEA01);
    for(auto cmd:{11u,12u,14u}) for(int i=0;i<3;++i) w.set(self,cmd,1);
    assert(applet().operation_notify && applet().performance_notify && applet().resume_notify);
    assert(applet().messages.empty() && wait(event,0)==0xEA01);
    puts("PASS factory CMIF booleans, result-only replies, pending preservation and no synthetic transitions");

    // Exercise the production coalescing producer used by initial foreground
    // mode publication. No host mode transition or resume is claimed here.
    for(uint32_t operation:{0u,1u}) for(uint32_t performance:{0u,1u}) {
        w.set(self,11,operation);w.set(self,12,performance);
        {
            std::lock_guard lk(g_applet_events);
            for(int n=0;n<1000;++n) applet().enqueue_mode_notifications();
            update_message_event(applet());
        }
        assert(applet().messages.size()==operation+performance);
        assert(wait(event,0)==(operation||performance?0u:0xEA01u));
        // Turning flags off does not hide or delete a latched notification.
        w.set(self,11,0);w.set(self,12,0);
        for(auto pair:{std::pair{operation,30u},std::pair{performance,31u}}) if(pair.first) {
            assert(w.send(common,1,0,0,0)==0 && w.words[8]==pair.second);
        }
        assert(w.send(common,1,0,0,0)==0 && w.words[6]==kAmNoMessage);
        assert(wait(event,0)==0xEA01 && wait(event2,0)==0xEA01);
    }
    // A previously pending performance bit does not outrank a later operation
    // bit. Both remain queued when subsequently disabled.
    w.set(self,11,0);w.set(self,12,1);
    {
        std::lock_guard lk(g_applet_events);
        applet().enqueue_mode_notifications();update_message_event(applet());
    }
    w.set(self,11,1);
    {
        std::lock_guard lk(g_applet_events);
        applet().enqueue_mode_notifications();update_message_event(applet());
    }
    assert((applet().messages==std::deque<uint32_t>{30,31}));
    w.set(self,11,0);w.set(self,12,0);
    for(auto message:{30u,31u}) assert(w.send(common,1,0,0,0)==0 && w.words[8]==message);
    assert(wait(event,0)==0xEA01);
    puts("PASS all mode enable/disable combinations, bounded coalescing, queue ordering and event draining");

    // Domain clone and a newly obtained self controller share applet policy.
    assert(w.send(self,0,0,0,0,5)==0);auto root=w.words[8];
    assert(w.send(self,2,0,0,0,5)==0);auto clone=w.words[3];
    w.set(self,11,1,root);w.set(self,14,0,root);
    assert(w.send(self,0,0,0,0,2)==0xF601);close(self);
    w.set(clone,12,1,root);w.set(clone,14,1,root);
    assert(applet().operation_notify && applet().performance_notify && applet().resume_notify);
    auto fresh=self_controller();auto next=new_session_handle(fresh);
    w.set(next,11,0);assert(!applet().operation_notify);
    // HIPC/CMIF padding is not additional bools; real domain byte count is 1.
    w.set(clone,11,0xa5ffff01,root);
    assert(applet().operation_notify);
    // TIPC word padding also leaves the single canonical bool unchanged.
    for(auto cmd:{11u,12u,14u}) {
        std::memset(w.words,0,sizeof w.words);w.words[0]=cmd+16;w.words[1]=1;
        w.words[2]=0xa5ffff00;
        assert(ipc_request(w.cpu,next,reinterpret_cast<uint64_t>(w.words),sizeof w.words)==0);
        assert(w.words[0]==cmd+16 && w.words[1]==1);
        for(unsigned i=2;i<64;++i) assert(w.words[i]==0);
    }
    assert(!applet().operation_notify && !applet().performance_notify && !applet().resume_notify);
    close(event);assert(wait(event2,0)==0xEA01);
    puts("PASS domain clone, reacquisition and applet-owned lifetime, copied event and TIPC padding");

    for(auto cmd:{11u,12u,14u}) {
        auto reject=[&](auto call) {
            auto queue=applet().messages;auto count=kstate::g_handles.size();bool rejected=false;
            try {rejected=call()!=0;} catch(const std::runtime_error& e) {
                auto error=std::string(e.what());
                rejected=error=="ipc: malformed request framing" || error==
                    "ISelfController notification command "+std::to_string(cmd)+": malformed boolean payload";
            }
            assert(rejected);
            assert(!applet().operation_notify && !applet().performance_notify && !applet().resume_notify);
            assert(applet().messages==queue && wait(event2,0)==0xEA01);
            assert(kstate::g_handles.size()==count);
        };
        reject([&]{return w.send(next,cmd,1,0,0);});
        reject([&]{return w.send(clone,cmd,1,root,0);});
        for(auto value:{2u,255u}) {
            reject([&]{return w.send(next,cmd,value);});
            reject([&]{return w.send(clone,cmd,value,root);});
        }
        reject([&]{IpcCtx c;c.cmd=cmd;c.in_size=1;return fresh->handle(c);});
        uint8_t value=1;
        reject([&]{IpcCtx c;c.cmd=cmd;c.in=&value;return fresh->handle(c);});
        // A domain object ID byte after a header-only body cannot be a bool.
        reject([&]{
            std::memset(w.words,0,sizeof w.words);w.words[0]=6;w.words[1]=13;
            w.words[4]=1u|(1u<<8)|(16u<<16);w.words[5]=root;
            w.words[8]=kSFCI;w.words[10]=cmd;w.words[12]=root;
            return ipc_request(w.cpu,clone,reinterpret_cast<uint64_t>(w.words),sizeof w.words);
        });
        reject([&]{
            std::memset(w.words,0,sizeof w.words);w.words[0]=cmd+16;
            return ipc_request(w.cpu,next,reinterpret_cast<uint64_t>(w.words),sizeof w.words);
        });
        reject([&]{
            std::memset(w.words,0,sizeof w.words);w.words[0]=cmd+16;w.words[1]=1;w.words[2]=2;
            return ipc_request(w.cpu,next,reinterpret_cast<uint64_t>(w.words),sizeof w.words);
        });
        // Domain byte count cannot run into word padding or outside storage.
        for(uint32_t declared:{17u,65535u}) reject([&]{
            std::memset(w.words,0,sizeof w.words);w.words[0]=6;w.words[1]=12;
            w.words[4]=1u|(declared<<16);w.words[5]=root;
            w.words[8]=kSFCI;w.words[10]=cmd;w.words[12]=1;
            return ipc_request(w.cpu,clone,reinterpret_cast<uint64_t>(w.words),48);
        });
        assert(w.send(clone,cmd,1,root+99)==0xF601);
        assert(w.send(0xdead,cmd,1)==0xE401);
    }
    puts("PASS malformed bool/null/size and domain object boundaries reject atomically through actual dispatch");

    // Foreground remains runnable, no resume is synthesized by any setter;
    // unsupported suspend accounting and neighboring lifecycle routes stay fatal.
    w.set(next,14,1);
    assert(w.send(common,9,0,0,0)==0 && w.words[8]==1);
    for(auto cmd:{1u,2u,3u,4u,15u,17u,18u,90u,0xffffffffu}) {
        bool stopped=false;
        try {w.send(next,cmd);} catch(const std::runtime_error& e) {
            stopped=std::string(e.what())=="strict IPC missing command: service=ISelfController command="+std::to_string(cmd);
        }
        assert(stopped && applet().messages.empty() && wait(event2,0)==0xEA01);
    }
    assert(w.send(clone,0,0,0,0,2)==0xF601);close(clone);
    assert(w.send(next,0,0,0,0,2)==0xF601);close(next);fresh.reset();
    assert(wait(event2,0)==0xEA01);close(event2);close(common);
    assert(kstate::g_handles.size()==count);
    puts("PASS unsupported lifecycle remains strict, foreground unchanged, no fabricated resume and no handle leaks");
}

int main() {
    KThread thread;kstate::t_self=&thread;
    notification_tests();
    kstate::t_self=nullptr;
}
