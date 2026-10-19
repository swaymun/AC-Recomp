// Original synthetic requests through actual production kernel/CMIF/AM handlers.
#include <sys/mman.h>
#include "kernel-host.h"

int main() {
    KThread thread; kstate::t_self=&thread;
    CPU cpu; alignas(16) uint32_t msg[64]{};
    const auto baseline=kstate::g_handles.size();
    auto send=[&](uint32_t handle,uint32_t command,std::vector<uint32_t> args={},uint32_t object=0) {
        std::memset(msg,0,sizeof msg);msg[0]=object?6:4;msg[1]=(object?12:8)+args.size();
        unsigned raw=object?8:4;
        if(object){msg[4]=1u|((16u+args.size()*4)<<16);msg[5]=object;}
        msg[raw]=kSFCI;msg[raw+2]=command;
        for(size_t i=0;i<args.size();++i)msg[raw+4+i]=args[i];
        return ipc_request(cpu,handle,reinterpret_cast<uint64_t>(msg),sizeof msg);
    };
    auto acquire=[&](uint32_t h,uint32_t cmd,std::vector<uint32_t> args={}) {
        assert(send(h,cmd,args)==0 && msg[4]==kSFCO && msg[6]==0);return msg[3];
    };
    auto reject=[&](auto fn,const char* text) {
        auto count=kstate::g_handles.size();auto bytes=applet_storage_budget()->bytes,objects=applet_storage_budget()->objects;
        bool caught=false;
        try{fn();}catch(const std::runtime_error& e){caught=std::string(e.what()).find(text)!=std::string::npos;
            if(!caught)std::fprintf(stderr,"expected [%s], got [%s]\n",text,e.what());}
        assert(caught && count==kstate::g_handles.size());
        assert(bytes==applet_storage_budget()->bytes && objects==applet_storage_budget()->objects);
    };
    auto controller=new_session_handle(self_controller());
    reject([&]{send(controller,9);},"strict IPC missing command: service=ISelfController command=9");
    close(controller);
    auto top=new_session_handle(make_service("appletOE"));auto proxy=acquire(top,0);
    auto creator=acquire(proxy,11);close(top);close(proxy);
    for(auto capacity:std::vector<std::vector<uint32_t>>{{0xffffffff,0xffffffff},{65537,0},{0,1}})
        reject([&]{send(creator,10,capacity);},"unsupported storage capacity");
    auto storage=acquire(creator,10,{32,0});auto accessor=acquire(storage,0);
    auto object=std::dynamic_pointer_cast<KSession>(handle_get(accessor))->svc;
    assert(send(accessor,0)==0 && msg[8]==32 && msg[9]==0);
    auto* memory=static_cast<uint8_t*>(mmap(reinterpret_cast<void*>(0x3000000000ull),4096,
        PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0));
    assert(memory!=MAP_FAILED);const uint64_t addr=reinterpret_cast<uint64_t>(memory);
    assert(addr+4096 < (1ull<<39));fixture_regions={{addr,4096,3,3}};
    // Exact libnx output auto-buffer signature: one B, one C, 8-byte
    // offset, one u16 variable receive size (including inactive C's zero).
    auto make_read=[&](bool pointer,int64_t offset,Buffer buffer,uint32_t id=0) {
        std::memset(msg,0,sizeof msg);msg[0]=(id?6:4)|(1u<<24);
        const unsigned ndata=id?15:11, raw=id?12:8;
        msg[1]=ndata|(3u<<10);
        if(!pointer) {msg[2]=uint32_t(buffer.size);msg[3]=uint32_t(buffer.addr);
            msg[4]=(uint32_t((buffer.addr>>32)&15)<<28)|
                (uint32_t((buffer.addr>>36)&7)<<2)|(uint32_t((buffer.size>>32)&15)<<24);}
        if(id) {msg[8]=1u|(24u<<16);msg[9]=id;}
        msg[raw]=kSFCI;msg[raw+2]=11;std::memcpy(msg+raw+4,&offset,8);
        msg[5+ndata-1]=pointer?uint16_t(buffer.size):0;
        if(pointer) {msg[5+ndata]=uint32_t(buffer.addr);
            msg[6+ndata]=uint32_t(buffer.addr>>32)|(uint32_t(buffer.size)<<16);}
    };
    auto dispatch=[&](uint32_t handle,unsigned bytes=sizeof msg) {
        assert(ipc_request(cpu,handle,reinterpret_cast<uint64_t>(msg),bytes)==0);
    };
    auto atomic_reject=[&](uint32_t handle,unsigned bytes=sizeof msg) {
        const auto packet=std::vector<uint32_t>(msg,msg+64);
        const auto guest=std::vector<uint8_t>(memory,memory+4096);
        const auto next=kstate::g_next_handle;
        auto session=std::dynamic_pointer_cast<KSession>(handle_get(handle));
        const auto objects=session->dom->objects.size();
        const auto next_object=session->dom->next_object;
        reject([&]{dispatch(handle,bytes);}, "");
        assert(std::equal(packet.begin(),packet.end(),msg));
        assert(std::equal(guest.begin(),guest.end(),memory));
        assert(next==kstate::g_next_handle && objects==session->dom->objects.size());
        assert(next_object==session->dom->next_object);
    };
    for(bool pointer:{false,true}) {
        std::memset(memory,0x5a,32);make_read(pointer,0,{addr,4});dispatch(accessor);
        for(unsigned i=0;i<32;++i)assert(memory[i]==(i<4?0:0x5a));
        make_read(pointer,0,{addr,4});msg[15]=pointer?5:1;atomic_reject(accessor);
        make_read(pointer,0,{addr,4});msg[1]=10|(3u<<10);
        msg[15]=msg[16];msg[16]=msg[17];atomic_reject(accessor); // missing table
        make_read(pointer,0,{addr,4});atomic_reject(accessor,61); // truncated table
        make_read(pointer,0,{addr,4});atomic_reject(accessor,71); // truncated C
        make_read(pointer,0,{addr,4});msg[1]=12|(3u<<10);
        msg[18]=msg[17];msg[17]=msg[16];atomic_reject(accessor); // extra raw word
        make_read(pointer,0,{addr,4});msg[1]=11|(4u<<10);atomic_reject(accessor); // extra C/table
        make_read(pointer,0,{addr,4});
        if(pointer) {msg[2]=4;msg[3]=uint32_t(addr);msg[4]=uint32_t(addr>>32)<<28;}
        else {msg[16]=uint32_t(addr);msg[17]=uint32_t(addr>>32)|(4u<<16);}
        atomic_reject(accessor); // two active
        make_read(pointer,0,{addr,4});if(pointer)msg[2]=1;else msg[17]=1u<<16;
        atomic_reject(accessor); // inactive address zero but size nonzero
        make_read(pointer,0,{addr,4});if(pointer)msg[3]=1;else msg[16]=1;
        atomic_reject(accessor); // inactive nonzero address, zero size
        for(int64_t off:{-1ll,31ll,0x7fffffffffffffffll}) {
            make_read(pointer,off,{addr,4});atomic_reject(accessor);
        }
        make_read(pointer,0,{1,4});atomic_reject(accessor);
        fixture_regions={{addr,2,3,3},{addr+2,4094,3,1}};
        make_read(pointer,0,{addr,4});atomic_reject(accessor);
        fixture_regions={{addr,4096,3,3}};
    }
    // Structurally complete packets with an extra B or wrong-direction A/X/W
    // must reach the consumer and reject, even when the extra slot is zero.
    for(unsigned descriptor:{0u,1u,2u,3u}) {
        make_read(false,0,{addr,4});
        if(descriptor==2) {
            msg[0]|=1u<<16;
            msg[5]=msg[3];msg[6]=msg[4];msg[4]=msg[2];msg[2]=msg[3]=0;
            msg[17]=0;msg[18]=0;msg[19]=0; // table at raw_start+40, then C
        } else {
            if(descriptor==0)msg[0]+=1u<<24;
            if(descriptor==1) {
                msg[0]|=1u<<20;
                for(unsigned i=0;i<3;++i){msg[5+i]=msg[2+i];msg[2+i]=0;}
            }
            if(descriptor==3)msg[0]|=1u<<28;
            msg[18]=0;msg[19]=0;msg[20]=0;
        }
        atomic_reject(accessor);
    }
    make_read(false,0,{addr,4});msg[1]=11;atomic_reject(accessor); // missing C
    make_read(false,0,{addr,4});msg[0]=4;atomic_reject(accessor); // missing B
    puts("PASS actual serialized extra/missing descriptors and wrong-direction A/X/W rejected atomically");
    puts("PASS actual serialized Read B-active/table0 and C-active/table4; malformed table1/5, missing/truncated/extra table, two-active/nonzero-inactive, offsets/ranges/permissions reject atomically");
    auto rw=[&](bool write,int64_t offset,Buffer b,bool pointer=false) {
        if(!write) {make_read(pointer,offset,b);dispatch(accessor);return;}
        IpcCtx c;c.cmd=10;c.in=reinterpret_cast<uint8_t*>(&offset);c.in_size=8;
        (pointer?c.x:c.a).push_back(b);
        auto rc=object->handle(c);assert(rc==0 && c.out.empty() && c.out_objects.empty());
    };
    rw(false,0,{addr,32});for(unsigned i=0;i<32;++i)assert(memory[i]==0);
    for(unsigned i=0;i<16;++i)memory[i]=i+1;
    rw(true,8,{addr,16});std::memset(memory,0,32);rw(false,0,{addr,32},true);
    for(unsigned i=0;i<32;++i)assert(memory[i]==(i>=8 && i<24?i-7:0));
    // Serialized X Write remains compatible with the existing input path.
    std::memset(msg,0,sizeof msg);msg[0]=4|(1u<<16);msg[1]=10;
    msg[2]=(4u<<16)|uint32_t((addr>>32)&15)<<12|uint32_t((addr>>36)&7)<<6;
    msg[3]=uint32_t(addr);msg[4]=kSFCI;msg[6]=10;
    memory[0]=42;dispatch(accessor);memory[0]=0;rw(false,0,{addr,4});assert(memory[0]==42);
    rw(true,32,{addr,0});rw(false,32,{addr,0});
    puts("PASS actual factory/creator/storage/accessor, zero initialization, offsets, A/X/B/C and serialized buffers");

    for(bool write:{false,true}) {
        for(int64_t offset:{-1ll,33ll,0x7fffffffffffffffll})
            reject([&]{rw(write,offset,{addr,1});},"range exceeds capacity");
        reject([&]{rw(write,31,{addr,2});},"range exceeds capacity");
        for(Buffer b:std::vector<Buffer>{{0,1},{addr,65537}})
            reject([&]{rw(write,0,b);},"applet:");
        reject([&]{rw(write,0,{1,1});},"inaccessible");
        fixture_regions={{addr,1,3,3},{addr+1,4095,3,0}};
        reject([&]{rw(write,0,{addr,2});},"inaccessible");
        fixture_regions={{addr,4096,3,write?2u:1u}};
        reject([&]{rw(write,0,{addr,1});},"inaccessible");
        fixture_regions={{addr,4096,3,3}};
    }
    reject([&]{rw(true,0,{~uint64_t(0)-1,4});},"extent");
    fixture_regions={{addr,~uint64_t(0),3,3}};
    for(bool write:{false,true})reject([&]{rw(write,0,{addr,1});},"inaccessible");
    fixture_regions={{addr,4096,3,3}};
    // Auto-select placeholders and multi-block valid permissions use the same
    // production validation path. No fallback to an unadvertised direction.
    { int64_t offset=0;IpcCtx c;c.cmd=10;c.in=reinterpret_cast<uint8_t*>(&offset);c.in_size=8;
      c.a={{}};c.x={{addr,1}};assert(object->handle(c)==0); }
    fixture_regions={{addr,1,3,3},{addr+1,4095,3,3}};rw(false,0,{addr,2});
    fixture_regions={{addr,1,3,3},{addr+1,4095,3,0}};memory[0]=99;
    reject([&]{rw(false,0,{addr,2});},"inaccessible");assert(memory[0]==99);
    fixture_regions={{addr,4096,3,3}};
    // A rejected write across a later unreadable region cannot modify a prefix.
    memory[0]=99;fixture_regions={{addr,1,3,3},{addr+1,4095,3,0}};
    reject([&]{rw(true,0,{addr,2});},"inaccessible");
    fixture_regions={{addr,4096,3,3}};rw(false,0,{addr,1});assert(memory[0]==42);
    for(unsigned kind=0;kind<12;++kind) {
        reject([&]{int64_t offset=0;IpcCtx c;c.cmd=10;c.in=reinterpret_cast<uint8_t*>(&offset);c.in_size=8;c.a={{addr,1}};
            if(kind==0)c.in=nullptr;if(kind==1)c.in_size=7;if(kind==2)c.in_size=9;
            if(kind==3)c.a.clear();if(kind==4)c.x={{addr,1}};if(kind==5)c.a.push_back({addr,1});
            if(kind==6)c.b={{addr,1}};if(kind==7)c.in_objects={1};if(kind==8)c.in_copy={1};
            if(kind==9)c.in_move={1};if(kind==10)c.w={{addr,1}};if(kind==11)c.c={{addr,1}};
            object->handle(c);},"applet:");
    }
    for(uint32_t cmd:{0u,10u}) {
        reject([&]{send(creator,cmd);},"malformed");
        reject([&]{send(creator,cmd,{1});},"malformed");
        reject([&]{send(creator,cmd,{1,0,0});},"malformed");
    }
    for(size_t n=0;n<8;++n) {
        for(auto service:{object,std::dynamic_pointer_cast<KSession>(handle_get(creator))->svc}) {
            int64_t value=0;reject([&]{IpcCtx c;c.cmd=10;c.in=reinterpret_cast<uint8_t*>(&value);
                c.in_size=n;service->handle(c);},"malformed storage request");
        }
    }
    reject([&]{send(accessor,0,{0});},"malformed");
    reject([&]{send(storage,0,{0});},"malformed");
    reject([&]{send(creator,0,{0x10,0});},"user selector unsupported: configured account/UI policy unavailable");
    reject([&]{send(creator,0,{0x10,1});},"unsupported library applet or mode");
    for(auto pair:{std::pair{creator,11u},std::pair{storage,1u},std::pair{accessor,12u}})
        reject([&]{send(pair.first,pair.second);},"strict IPC missing command");
    puts("PASS malformed inputs/descriptors, checked VM permissions/overflow, atomic failure and honest unsupported selection");

    // State survives parent/creator close and is shared across accessor opens.
    auto accessor2=acquire(storage,0);close(storage);close(creator);
    assert(send(accessor2,0)==0 && msg[8]==32);close(accessor2);
    assert(applet_storage_budget()->objects==1);close(accessor);assert(applet_storage_budget()->objects==1);
    object.reset();assert(applet_storage_budget()->objects==0 && applet_storage_budget()->bytes==0);
    auto next=new_session_handle(library_applet_creator());
    std::vector<uint32_t> live;
    for(unsigned i=0;i<16;++i)live.push_back(acquire(next,10,{65536,0}));
    reject([&]{send(next,10,{1,0});},"resource limit");
    auto another=new_session_handle(library_applet_creator());
    reject([&]{send(another,10,{1,0});},"resource limit");
    close(live.back());live.pop_back();live.push_back(acquire(another,10,{65536,0}));
    for(auto h:live)close(h);live.clear();
    for(unsigned i=0;i<32;++i)live.push_back(acquire(next,10,{0,0}));
    reject([&]{send(another,10,{0,0});},"resource limit");
    for(auto h:live)close(h);close(another);
    assert(applet_storage_budget()->objects==0 && applet_storage_budget()->bytes==0);
    // CloseHandle destroys a last backing alias under the real kernel lock.
    // It must not wait for the independent applet event mutex.
    auto closing=acquire(next,10,{1,0});std::atomic<bool> finished=false;
    { std::lock_guard lk(g_applet_events);
      std::thread closer([&]{close(closing);finished.store(true);});
      for(unsigned i=0;i<100 && !finished.load();++i) std::this_thread::sleep_for(std::chrono::milliseconds(1));
      assert(finished.load());closer.join(); }
    assert(applet_storage_budget()->objects==0);
    puts("PASS global capacity/object quotas across creators, parent-close lifetime and budget reclamation");

    auto s=acquire(next,10,{8,0});auto a=acquire(s,0);close(s);close(next);
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,a,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto id=msg[8];
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;msg[6]=2;
    assert(ipc_request(cpu,a,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto clone=msg[3];close(a);
    assert(send(clone,0,{},id)==0 && msg[12]==8);
    reject([&]{send(clone,10,{0},id);},"malformed storage request");
    reject([&]{std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=12;msg[4]=1u|(65535u<<16);msg[5]=id;
        ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg);},"malformed request framing");
    assert(send(clone,0,{},id+99)==0xF601);
    std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=8;msg[4]=2;msg[5]=id;
    assert(ipc_request(cpu,clone,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);
    assert(send(clone,0,{},id)==0xF601);close(clone);
    assert(applet_storage_budget()->objects==0 && applet_storage_budget()->bytes==0);
    assert(kstate::g_handles.size()==baseline);
    // Domain creator returns real child objects, not move handles. Opening a
    // domain storage returns an accessor sharing the same byte budget.
    auto dc=new_session_handle(library_applet_creator());
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,dc,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);auto root=msg[8];
    assert(send(dc,10,{32,0},root)==0 && msg[4]==1);auto ds=msg[12];assert(ds!=root);
    assert(send(dc,0,{},ds)==0 && msg[4]==1);auto da=msg[12];assert(da!=ds);
    assert(send(dc,0,{},da)==0 && msg[12]==32 && msg[13]==0);
    for(bool pointer:{false,true}) {
        make_read(pointer,0,{addr,4},da);dispatch(dc);
        for(unsigned i=0;i<4;++i)assert(memory[i]==0);
        make_read(pointer,0,{addr,4},da);msg[0]=(msg[0]&~0xffffu)|4;dispatch(dc);
        make_read(pointer,0,{addr,4},da);msg[19]=pointer?5:1;atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);msg[1]=14|(3u<<10);
        msg[19]=msg[20];msg[20]=msg[21];atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);atomic_reject(dc,77);
        make_read(pointer,0,{addr,4},da);msg[1]=16|(3u<<10);
        msg[22]=msg[21];msg[21]=msg[20];atomic_reject(dc);
        make_read(pointer,-1,{addr,4},da);atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);msg[8]=1u|(23u<<16);atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);msg[8]=1u|(25u<<16);atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);msg[8]=1u|(65535u<<16);atomic_reject(dc);
        make_read(pointer,0,{addr,4},da);msg[8]|=1u<<8;msg[18]=root;atomic_reject(dc);
    }
    // Malformed creator domain shape must not allocate storage or objects.
    send(dc,0,{},da); // fresh response, then explicit malformed creator frame
    std::memset(msg,0,sizeof msg);msg[0]=6;msg[1]=14;
    msg[4]=1u|(1u<<8)|(24u<<16);msg[5]=root;
    msg[8]=kSFCI;msg[10]=10;msg[12]=8;msg[14]=root;
    atomic_reject(dc);
    puts("PASS actual serialized domain B/C Read and malformed size/object shape reject atomically before copy/object allocation");
    reject([&]{send(dc,0,{0x10,0},root);},"configured account/UI policy unavailable");
    close(dc);assert(applet_storage_budget()->objects==0 && applet_storage_budget()->bytes==0);
    assert(kstate::g_handles.size()==baseline);
    munmap(memory,4096);kstate::t_self=nullptr;
    puts("PASS real domain/clone/close, malformed framing, stale objects and no leaked handles/storage");
}
