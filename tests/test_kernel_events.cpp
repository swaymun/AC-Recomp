// Original actual-kernel endpoint acceptance fixture. Full shipped kernel sources
// implement handles, events, waits and dispatch; unrelated host calls are fatal.
#include <cassert>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <vector>
#include <stdexcept>
#include <string>
#include <thread>
namespace nx {
struct CPU { uint64_t x[32]{}, tpidr = 0, tpidrro = 0; };
bool g_trace = false;
void log(const char*, ...) {}
[[noreturn]] void fatal(const char* fmt, ...) {
    char s[512]; va_list a; va_start(a, fmt); vsnprintf(s, sizeof s, fmt, a); va_end(a);
    throw std::runtime_error(s);
}
[[noreturn]] void unexpected() { throw std::runtime_error("unexpected host boundary"); }
template<class T> T ld(uint64_t p) { T v; std::memcpy(&v, reinterpret_cast<void*>(p), sizeof v); return v; }
template<class T> void st(uint64_t p, T v) { std::memcpy(reinterpret_cast<void*>(p), &v, sizeof v); }
std::string describe(uint64_t) { return "synthetic caller"; }
enum class HostCall { None, AttachAbort, AttachReturn, OpenRenderer };
HostCall expected_call=HostCall::None;
uint32_t attached_read=0, attached_write=0;
struct AttachBoundary {};
void call(CPU& c, uint64_t target) {
    if (target==1 && (expected_call==HostCall::AttachAbort || expected_call==HostCall::AttachReturn)) {
        attached_read=c.x[1]; attached_write=c.x[3];
        assert(c.x[2]==1 && c.x[4]==1);
        if(expected_call==HostCall::AttachAbort) throw AttachBoundary{};
        c.x[0]=0; return;
    }
    if(target==2 && expected_call==HostCall::OpenRenderer) { c.x[0]=0; return; }
    unexpected();
}
uint64_t find_symbol(const char* name) {
    if(std::string(name)=="_ZN2nn2os17AttachSystemEventEPNS0_15SystemEventTypeEjbjbNS0_14EventClearModeE") return 1;
    if(std::string(name)=="_ZN2nn5audio17OpenAudioRendererEPNS0_19AudioRendererHandleEPNS_2os11SystemEventERKNS0_22AudioRendererParameterEPvm") return 2;
    if(std::string(name)=="nvnBootstrapLoader") return 3;
    unexpected();
}
uint64_t hle_address(const char*) { unexpected(); }
struct LoadedModule { uint64_t base; };
const LoadedModule* module_at(uint64_t target) { if(target==3) return nullptr; unexpected(); }
constexpr uint64_t kModuleBase=0x1000000000, kKernelBase=0x2000000000, kKernelSize=0x1000000;
bool fixture_guest_memory = false;
std::vector<std::unique_ptr<unsigned char[]>> fixture_allocations;
uint64_t kernel_alloc(uint64_t size) {
    if (!fixture_guest_memory) unexpected();
    auto bytes=std::make_unique<unsigned char[]>(size);
    auto addr=reinterpret_cast<uint64_t>(bytes.get());
    fixture_allocations.push_back(std::move(bytes));return addr;
}
bool commit(uint64_t, uint64_t) { unexpected(); }
void decommit(uint64_t, uint64_t) { unexpected(); }
void vm_set(uint64_t, uint64_t, uint32_t, uint32_t) { if (!fixture_guest_memory) unexpected(); }
struct VmInfo { uint64_t addr, size; uint32_t state, perm; };
VmInfo vm_query(uint64_t) { unexpected(); }
constexpr uint64_t kHeapMax=1, kHeapBase=2, kStackBase=3, kStackSize=4, kAliasBase=5, kAliasSize=6;
constexpr uint32_t kMemStack=1, kMemInaccessible=2, kMemHeap=3, kMemAlias=4, kMemFree=5;
namespace game { struct Info { const char* id; }; const Info kInfo{"fixture"}; }
namespace plat {
uint64_t monotonic_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
void sleep_ns(int64_t ns) { std::this_thread::sleep_for(std::chrono::nanoseconds(ns)); }
void yield() { std::this_thread::yield(); }
int64_t current_thread_id() { return 1; }
void set_thread_name(const char*) {}
bool audio_open(void (*)(void*)) { unexpected(); }
uint32_t audio_queued() { unexpected(); }
bool audio_submit(const void*, uint64_t, void*) { unexpected(); }
void* create_window() { unexpected(); }
void release_window(void*) { unexpected(); }
void start_thread(void (*entry)(void*), void* arg, size_t) {
    if (!fixture_guest_memory) unexpected();
    entry(arg);
}
[[noreturn]] void exit_thread() { unexpected(); }
[[noreturn]] void exit_process(int) { unexpected(); }
}
}
#define NX_HLE(sym, fn)
#include "kernel.h"
namespace nx {
void backtrace(CPU&) { unexpected(); }
void init_tls_block(uint64_t) { if (!fixture_guest_memory) unexpected(); }
uint64_t get_info(uint32_t, uint32_t, uint64_t, uint32_t&) { unexpected(); }
uint32_t set_thread_core_mask(uint32_t, int32_t, uint64_t) { unexpected(); }
uint32_t map_transfer_memory(uint32_t, uint64_t, uint64_t) { unexpected(); }
uint32_t unmap_transfer_memory(uint32_t, uint64_t, uint64_t) { unexpected(); }

namespace kstate {
constexpr uint32_t kPseudoCurrentThread = 0xFFFF8000, kHandleWaitMask = 0x40000000;
}
}
#include "kernel.cpp"
#include "ipc.h"
namespace nx {
uint64_t desired_language() { unexpected(); }
std::shared_ptr<Service> preselected_user_storage() { unexpected(); }
}
#include "ipc.cpp"
#include "svc_am.cpp"
#include "svc_misc.cpp"
#include "hle_audio.cpp"
#include "hle_vi.cpp"
using namespace nx;
static uint32_t op(uint32_t svcno, uint32_t h) {
    CPU c; c.x[0]=h; svc(c,svcno,0); return uint32_t(c.x[0]);
}
static uint32_t wait(uint32_t h, int64_t timeout, uint64_t* index=nullptr) {
    CPU c; c.x[1]=reinterpret_cast<uint64_t>(&h); c.x[2]=1; c.x[3]=uint64_t(timeout);
    svc(c,0x18,0); if(index) *index=c.x[1]; return uint32_t(c.x[0]);
}
static void close(uint32_t h) { assert(op(0x16,h)==0); }
int main() {
    KThread main_thread; kstate::t_self=&main_thread;
    CPU c; svc(c,0x45,0); assert(c.x[0]==0);
    uint32_t w=c.x[1], r=c.x[2];
    auto writable=std::dynamic_pointer_cast<KEvent>(handle_get(w));
    auto readable=std::dynamic_pointer_cast<KEvent>(handle_get(r));
    assert(writable && readable && writable!=readable && writable->state==readable->state);
    assert(readable->endpoint==EventEndpoint::Readable && writable->endpoint==EventEndpoint::Writable);
    static_assert(!std::is_default_constructible_v<KEvent>);
    assert(!readable->signaled());
    assert(wait(r,0)==0xEA01);
    assert(op(0x12,r)==0 && op(0x12,w)==0); // ClearEvent is idempotent on both.
    assert(op(0x17,r)==0xFA01); // ResetSignal on an unsignaled readable endpoint.
    assert(op(0x11,w)==0);
    uint64_t index=99; assert(wait(r,0,&index)==0 && index==0);
    assert(wait(r,0)==0); // Manual-reset event is not consumed by waiting.
    assert(op(0x17,r)==0 && wait(r,0)==0xEA01);
    puts("PASS actual CreateEvent shared state, initial clear, manual wait/reset and ClearEvent");
    // Permission failures must not mutate shared state, in either state.
    assert(op(0x11,r)==0xE401 && wait(r,0)==0xEA01);
    assert(op(0x17,w)==0xE401 && wait(w,0)==0xE401);
    assert(op(0x11,w)==0);
    assert(op(0x11,r)==0xE401 && wait(r,0)==0);
    assert(wait(w,0)==0xE401 && op(0x17,w)==0xE401 && wait(r,0)==0);
    assert(op(0x12,w)==0 && op(0x12,w)==0 && wait(r,0)==0xEA01);
    puts("PASS actual readable SignalEvent, writable wait and writable ResetSignal rejected without mutation");
    auto wrong=handle_add(std::make_shared<KSharedMemory>());
    for (auto s : {0x11u,0x12u,0x17u}) {
        assert(op(s,wrong)==0xE401 && op(s,0xDEAD)==0xE401);
    }
    assert(wait(0xDEAD,0)==0xE401);
    assert(wait(wrong,0)==0xE401); // Nonwaitable objects are invalid, not a timeout.
    close(wrong); assert(wait(wrong,0)==0xE401);
    assert(op(0x16,wrong)==0xE401); // Double close must fail.
    puts("PASS actual nonwaitable wait and stale CloseHandle rejected");
    puts("PASS actual invalid/stale event SVC handles return InvalidHandle");
    // handle_add(handle_get(...)) is the actual host-side shared ownership path;
    // HIPC serialization and a guest DuplicateHandle syscall are not emulated here.
    std::weak_ptr<EventState> lifetime=readable->state;
    writable.reset(); readable.reset();
    auto copy=handle_add(handle_get(r)); close(r); assert(!handle_get(r));
    for (auto s : {0x11u,0x12u,0x17u}) assert(op(s,r)==0xE401);
    assert(wait(r,0)==0xE401);
    assert(op(0x11,w)==0 && wait(copy,0)==0 && op(0x12,copy)==0);
    close(w); assert(!handle_get(w));
    assert(wait(copy,0)==0xEA01); // Reader/state survive writable close.
    assert(op(0x11,copy)==0xE401 && op(0x17,copy)==0xFA01);
    assert(!lifetime.expired()); close(copy); assert(lifetime.expired());
    svc(c,0x45,0); w=c.x[1];r=c.x[2];
    auto wcopy=handle_add(handle_get(w)); close(w); close(r);
    assert(op(0x11,wcopy)==0 && op(0x12,wcopy)==0);
    assert(wait(wcopy,0)==0xE401 && op(0x17,wcopy)==0xE401); close(wcopy);
    puts("PASS actual duplicate reference and both copy/endpoint close orders");
    svc(c,0x45,0); w=c.x[1];r=c.x[2];
    auto begin=std::chrono::steady_clock::now();
    assert(wait(r,20'000'000)==0xEA01);
    auto elapsed=std::chrono::steady_clock::now()-begin;
    assert(elapsed>=std::chrono::milliseconds(10) && elapsed<std::chrono::seconds(2));
    auto waiter_copy=handle_add(handle_get(r));
    uint32_t result=0xFFFFFFFF;
    std::thread waiter([&] {
        KThread t; kstate::t_self=&t;
        result=wait(r,1'000'000'000);
        kstate::t_self=nullptr;
    });
    // Observe actual wait queue enrollment under its lock before signaling.
    auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    bool enrolled=false;
    while (std::chrono::steady_clock::now()<deadline) {
        { std::lock_guard lk(kstate::g_k); enrolled=!kstate::g_sync_waiters.empty(); }
        if(enrolled) break;
        std::this_thread::yield();
    }
    assert(enrolled); close(r); // The already-enrolled wait retains its object.
    assert(wait(r,0)==0xE401 && op(0x11,w)==0); waiter.join();
    assert(result==0 && wait(waiter_copy,0)==0);
    { std::lock_guard lk(kstate::g_k); assert(kstate::g_sync_waiters.empty()); }
    close(waiter_copy);close(w);
    puts("PASS actual bounded timeout and enrolled native waiter notification/wakeup");
    // Host producers share the kernel lock/notification path with SVCs.
    auto state=std::make_shared<EventState>();
    auto host_read=handle_add(std::make_shared<KEvent>(EventEndpoint::Readable,state));
    std::thread producer([&] { event_signal(state); }); producer.join();
    assert(wait(host_read,0)==0 && wait(host_read,0)==0);
    event_clear(state); event_clear(state); assert(wait(host_read,0)==0xEA01);
    close(host_read);
    // Threads remain waitable; unrelated objects do not become waitable.
    auto ended=std::make_shared<KThread>(); ended->exited=true;
    auto th=handle_add(ended); assert(wait(th,0)==0);
    for(auto code:{0x11u,0x12u,0x17u}) assert(op(code,th)==0xE401);
    close(th);
    puts("PASS actual host signal/clear helpers and thread waitability");
    // All six changed producer TUs are included unchanged. Exercise service events
    // against actual kernel permissions/ownership; device and guest-call boundaries
    // stay synthetic and unexpected calls remain fatal.
    auto common=common_state_getter(); IpcCtx get; get.cmd=0;
    assert(common->handle(get)==0 && get.out_copy.size()==1);
    auto message=get.out_copy[0]; assert(wait(message,0)==0 && op(0x11,message)==0xE401);
    for(uint32_t value:{15u,30u,31u}) {
        IpcCtx receive; receive.cmd=1; assert(common->handle(receive)==0);
        uint32_t actual=0; std::memcpy(&actual,receive.out.data(),4); assert(actual==value);
    }
    assert(wait(message,0)==0xEA01);
    IpcCtx empty; empty.cmd=1; assert(common->handle(empty)==0x680); close(message);
    auto aoc=make_service("aoc:u"); IpcCtx notify; notify.cmd=8;
    assert(aoc->handle(notify)==0 && notify.out_copy.size()==1);
    assert(op(0x11,notify.out_copy[0])==0xE401 && wait(notify.out_copy[0],0)==0xEA01);
    close(notify.out_copy[0]);
    auto controller=self_controller();
    for(uint32_t cmd:{90u,91u}) {
        IpcCtx missing; missing.cmd=cmd; bool stopped=false;
        try { controller->handle(missing); } catch(const std::runtime_error& e) {
            stopped=std::string(e.what()).find("strict IPC missing command: service=ISelfController command=")==0;
        }
        assert(stopped && missing.out_copy.empty() && missing.out.empty());
    }
    puts("PASS actual applet queue signal/drain, aoc readable output and strict command 90/91");
    // Actual IPC protocol Close releases server state but preserves each client
    // handle for the SDK's separate SVC CloseHandle. Exercise CMIF and TIPC.
    alignas(16) uint32_t request[64]{};
    auto send=[&](uint32_t client,uint32_t type,uint32_t cmd=0) {
        std::memset(request,0,sizeof request); request[0]=type; request[1]=8;
        request[4]=kSFCI; request[6]=cmd;
        return ipc_request(c,client,reinterpret_cast<uint64_t>(request),sizeof request);
    };
    for(uint32_t type:{2u,15u}) {
        auto service=std::make_shared<Service>("close-lifetime");
        service->cmds[0]=[](IpcCtx&) { return 0u; };
        std::weak_ptr<Service> life=service;
        auto client=new_session_handle(service); service.reset();
        auto alias=handle_add(handle_get(client));
        std::weak_ptr<KObject> session_life=handle_get(client);
        assert(send(client,type)==0xF601 && life.expired());
        assert(handle_get(client) && handle_get(alias));
        assert(send(alias,16)==0xF601 && send(client,type)==0xF601);
        close(client); assert(op(0x16,client)==0xE401);
        assert(send(client,type)==0xE401 && !session_life.expired());
        close(alias); assert(op(0x16,alias)==0xE401 && session_life.expired());
        // CloseHandle alone releases one alias, without closing the live server.
        service=std::make_shared<Service>("handle-only");
        service->cmds[0]=[](IpcCtx&) { return 0u; };
        life=service; client=new_session_handle(service); service.reset();
        alias=handle_add(handle_get(client)); close(client);
        assert(send(alias,16)==0 && !life.expired());
        close(alias); assert(life.expired());
    }
    puts("PASS actual CMIF/TIPC Close, client CloseHandle, stale rejection and alias/service lifetime");
    // Exercise real CMIF control conversion/clone serialization, domain subobject
    // close and a copied event. Closing one cloned session must not clear the
    // shared domain table or revoke independent output handles.
    for(uint32_t type:{2u,15u}) {
        auto service=std::make_shared<Service>("domain-lifetime");
        service->cmds[0]=[](IpcCtx&) { return 0u; };
        std::weak_ptr<Service> life=service;
        auto client=new_session_handle(service); service.reset();
        assert(send(client,5,0)==0); auto root_id=request[8]; assert(root_id==1);
        assert(send(client,5,2)==0); auto clone=request[3]; assert(handle_get(clone));
        auto child=std::make_shared<Service>("domain-child");
        std::weak_ptr<Service> child_life=child;
        { // Populate through actual service output and IPC domain serialization.
            auto root=std::dynamic_pointer_cast<KSession>(handle_get(client));
            root->svc->cmds[1]=[child](IpcCtx& out) { out.push_object(child); return 0u; };
        }
        auto domain_send=[&](uint32_t h,uint32_t obj,uint32_t command,uint32_t domain_command=1) {
            std::memset(request,0,sizeof request); request[0]=4; request[1]=12;
            request[4]=domain_command | (16u<<16); request[5]=obj;
            request[8]=kSFCI; request[10]=command;
            return ipc_request(c,h,reinterpret_cast<uint64_t>(request),sizeof request);
        };
        assert(domain_send(client,root_id,1)==0); auto child_id=request[12]; assert(child_id==2);
        { auto root=std::dynamic_pointer_cast<KSession>(handle_get(client)); root->svc->cmds.erase(1); }
        child.reset(); assert(!child_life.expired());
        // Actual service returns a readable output handle; wire copy remains live.
        auto source_event=std::make_shared<EventState>();
        { auto root=std::dynamic_pointer_cast<KSession>(handle_get(client));
          root->svc->cmds[2]=[source_event](IpcCtx& out) {
              out.out_copy.push_back(handle_add(std::make_shared<KEvent>(EventEndpoint::Readable,source_event)));
              return 0u;
          }; }
        assert(domain_send(client,root_id,2)==0); auto copied_event=request[3];
        assert(wait(copied_event,0)==0xEA01);
        assert(send(client,type)==0xF601); close(client);
        assert(!life.expired() && !child_life.expired());
        assert(domain_send(clone,root_id,0)==0);
        assert(domain_send(clone,child_id,0,2)==0 && child_life.expired());
        assert(domain_send(clone,child_id,0)==0xF601);
        event_signal(source_event); assert(wait(copied_event,0)==0);
        assert(send(clone,type)==0xF601 && life.expired()); close(clone);
        assert(op(0x16,clone)==0xE401 && wait(copied_event,0)==0); close(copied_event);
    }
    puts("PASS actual domain clone/subobject close and independent IPC event copy lifetime");
    // Validate actual HLE pair construction up to AttachSystemEvent, deliberately
    // aborting at that declared boundary before an immortal device thread starts.
    auto check_pair=[&](uint32_t read,uint32_t write) {
        auto re=std::dynamic_pointer_cast<KEvent>(handle_get(read));
        auto we=std::dynamic_pointer_cast<KEvent>(handle_get(write));
        assert(re && we && re->state==we->state);
        assert(re->endpoint==EventEndpoint::Readable && we->endpoint==EventEndpoint::Writable);
        assert(op(0x11,read)==0xE401 && wait(write,0)==0xE401);
    };
    expected_call=HostCall::AttachAbort;
    bool attach_stopped=false;
    try { GetDisplayVsyncEvent(c); } catch(const AttachBoundary&) { attach_stopped=true; }
    assert(attach_stopped); check_pair(attached_read,attached_write);
    event_signal(g_vsync); assert(wait(attached_read,0)==0); event_clear(g_vsync);
    close(attached_read); close(attached_write);
    attach_stopped=false;
    try { OpenDefaultAudioOut(c); } catch(const AttachBoundary&) { attach_stopped=true; }
    assert(attach_stopped); check_pair(attached_read,attached_write);
    auto audio_read=attached_read, audio_write=attached_write;
    // Exercise actual audio completion producer and released queue consumer.
    release(reinterpret_cast<void*>(0x1234)); assert(wait(audio_read,0)==0);
    release(reinterpret_cast<void*>(0x5678)); GetReleasedAudioOutBuffer(c);
    assert(c.x[0]==0x1234 && wait(audio_read,0)==0);
    GetReleasedAudioOutBuffer(c); assert(c.x[0]==0x5678 && wait(audio_read,0)==0xEA01);
    GetReleasedAudioOutBuffer(c); assert(c.x[0]==0);
    // Native callback/drain overlap: final queued release must remain signaled.
    std::thread completions([] { for(uint64_t i=1;i<=200;i++) release(reinterpret_cast<void*>(i)); });
    for(int i=0;i<200;i++) GetReleasedAudioOutBuffer(c);
    completions.join();
    { std::lock_guard lk(g_out.lock); assert(wait(audio_read,0)==(g_out.released.empty()?0xEA01u:0u)); }
    do { GetReleasedAudioOutBuffer(c); } while(c.x[0]);
    assert(wait(audio_read,0)==0xEA01); close(audio_read); close(audio_write);
    expected_call=HostCall::AttachReturn; AcquireAudioDeviceNotificationForOutput(c);
    check_pair(attached_read,attached_write); assert(wait(attached_read,0)==0xEA01);
    close(attached_read); close(attached_write);
    uint64_t renderer_handle[16]{}; uint8_t system_event[64]{};
    c.x[0]=reinterpret_cast<uint64_t>(renderer_handle); c.x[1]=reinterpret_cast<uint64_t>(system_event);
    expected_call=HostCall::OpenRenderer; OpenAudioRenderer(c);
    auto renderer_read=ld<uint32_t>(reinterpret_cast<uint64_t>(system_event)+0x14);
    auto renderer_write=ld<uint32_t>(reinterpret_cast<uint64_t>(system_event)+0x18);
    check_pair(renderer_read,renderer_write);
    event_signal(g_audio_frame); assert(wait(renderer_read,0)==0); event_clear(g_audio_frame);
    close(renderer_read); close(renderer_write); expected_call=HostCall::None;
    puts("PASS actual audio/display endpoint producers, audio callback/drain overlap and renderer fallback");
    bool fatal_gate=false;
    try { svc(c,0xFFFFFFFF,0); } catch(const std::runtime_error& e) {
        fatal_gate=std::string(e.what()).find("strict unhandled SVC")!=std::string::npos;
    }
    assert(fatal_gate); puts("PASS actual unknown SVC remains fatal");
}
