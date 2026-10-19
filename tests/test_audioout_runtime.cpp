// Original synthetic host boundary; actual composed HLE, loader registry and call dispatcher.
#include <cassert>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <thread>
#include "kernel.h"
#include "platform.h"
namespace nx {
std::map<uint32_t,std::shared_ptr<KObject>> handles;
std::mutex host_lock;
std::vector<std::pair<uint64_t,uint64_t>> regions;
void region(void* p,size_t n) { regions.push_back({reinterpret_cast<uint64_t>(p),n}); }
VmInfo vm_query(uint64_t a) {
    for(auto [p,n]:regions) if(a>=p && a-p<n) return {p,n,kMemHeap,3};
    return {a,4096,kMemFree,0};
}
bool commit(uint64_t,uint64_t) { return true; }
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) {}
uint64_t kernel_alloc(uint64_t,uint64_t) { throw std::runtime_error("unexpected allocation"); }
void backtrace(CPU&) {}
uint32_t handle_add(std::shared_ptr<KObject> o) { static uint32_t next=1;handles[++next]=o;return next; }
void event_signal(const std::shared_ptr<EventState>& e) {std::lock_guard lk(host_lock);e->signaled=true;}
void event_clear(const std::shared_ptr<EventState>& e) {std::lock_guard lk(host_lock);e->signaled=false;}
namespace plat {
AudioDone done;
struct Submission {void* ctx;std::vector<uint8_t> bytes;};
std::deque<Submission> submissions;
bool available=true,reject=false;
bool audio_open(AudioDone fn) { done=fn;return available; }
bool audio_submit(const void* p,size_t n,void* ctx) {
    std::lock_guard lk(host_lock);
    if(reject) return false;
    submissions.push_back({ctx,{static_cast<const uint8_t*>(p),static_cast<const uint8_t*>(p)+n}});return true;
}
uint32_t audio_queued() {std::lock_guard lk(host_lock);return uint32_t(submissions.size());}
uint64_t monotonic_ns() {return 0;}
void sleep_ns(int64_t) {}
std::string data_root() {return ".";}
void log_line(const char*) {}
[[noreturn]] void exit_process(int) {throw std::runtime_error("strict fatal");}
}
}
#include "loader.cpp"
#include "hle_audio.cpp"
using namespace nx;
std::string symbol(const char* suffix) {return std::string("_ZN2nn5audio")+suffix;}
uint64_t invoke(const char* suffix,uint64_t a=0,uint64_t b=0,uint64_t d=0,uint64_t e=0) {
    auto s=symbol(suffix);assert(hle_lookup(s.c_str()));CPU c{};c.x[0]=a;c.x[1]=b;c.x[2]=d;c.x[3]=e;
    call(c,hle_address(s.c_str()));return c.x[0];
}
const char *open_name="19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE",
 *start_name="13StartAudioOutEPNS0_8AudioOutE",*stop_name="12StopAudioOutEPNS0_8AudioOutE",
 *close_name="13CloseAudioOutEPNS0_8AudioOutE",*state_name="16GetAudioOutStateEPKNS0_8AudioOutE",
 *channel_name="23GetAudioOutChannelCountEPKNS0_8AudioOutE",
 *append_name="20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE",
 *released_name="25GetReleasedAudioOutBufferEPNS0_8AudioOutE",
 *info_name="21SetAudioOutBufferInfoEPNS0_14AudioOutBufferEPvmm",
 *list_name="19ListAudioDeviceNameEPNS0_15AudioDeviceNameEi";
void attach(CPU& c) {
    assert(c.x[2]==1 && c.x[4]==1 && c.x[5]==1 && !ld<uint8_t>(c.x[0]+0x28));
    st<uint32_t>(c.x[0]+0x14,uint32_t(c.x[1]));st<uint32_t>(c.x[0]+0x18,uint32_t(c.x[3]));
    st<uint8_t>(c.x[0]+0x28,1);
}
void finalize_event(uint64_t event) { // guest-owned event lifetime, separate from CloseAudioOut
    assert(ld<uint8_t>(event+0x28));
    assert(handles.erase(ld<uint32_t>(event+0x14))==1);
    assert(handles.erase(ld<uint32_t>(event+0x18))==1);
    std::memset(reinterpret_cast<void*>(event),0,0x30);
}
void expect_fatal(auto fn) {bool caught=false;try{fn();}catch(const std::runtime_error&){caught=true;}assert(caught);}
void wait_for(auto predicate) {
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(!predicate()) {assert(std::chrono::steady_clock::now()<until);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
void complete_one() {void* ctx;{std::lock_guard lk(host_lock);assert(!plat::submissions.empty());ctx=plat::submissions.front().ctx;plat::submissions.pop_front();}plat::done(ctx);}
bool signaled(uint32_t h) {std::lock_guard lk(host_lock);return handles.at(h)->signaled();}
int main(int argc,char** argv) {
    plat::available=!(argc>1 && std::string(argv[1])=="no-device");
    plat::reject=argc>1 && std::string(argv[1])=="reject";
    const char* attach_name="_ZN2nn2os17AttachSystemEventEPNS0_15SystemEventTypeEjbjbNS0_14EventClearModeE";
    HleRegistrar reg(attach_name,attach);g_exports[attach_name]=hle_address(attach_name);
    alignas(16) uint8_t out[0x178]{},event[0x30]{},param[8]{},names[768];
    alignas(4096) uint8_t pcm[4096];std::memset(pcm,0x5a,sizeof pcm);
    alignas(8) uint64_t buffers[66][5]{};
    region(out,sizeof out);region(event,sizeof event);region(param,sizeof param);region(names,sizeof names);region(pcm,sizeof pcm);region(buffers,sizeof buffers);
    auto o=reinterpret_cast<uint64_t>(out),ev=reinterpret_cast<uint64_t>(event),pa=reinterpret_cast<uint64_t>(param),data=reinterpret_cast<uint64_t>(pcm);
    invoke("27InitializeAudioOutParameterEPNS0_17AudioOutParameterE",pa);assert(ld<uint64_t>(pa)==0xcafe000000000000ull);
    st<uint32_t>(pa,44100);assert(invoke(open_name,o,ev,pa)==0x899);assert(handles.empty());st<uint32_t>(pa,48000);
    st<uint16_t>(pa+6,0);assert(invoke(open_name,o,ev,pa)==0x899);st<uint16_t>(pa+6,0xcafe);
    assert(invoke(open_name,0,ev,pa)==0x899 && invoke(open_name,o,0,pa)==0x899);
    st<uint16_t>(pa+4,6);assert(invoke(open_name,o,ev,pa)==0x899);st<uint16_t>(pa+4,2);
    assert(invoke(open_name,o,ev,pa)==0);auto hr=ld<uint32_t>(ev+0x14),hw=ld<uint32_t>(ev+0x18);
    assert(handles.size()==2 && handles.at(hr)->waitable() && !handles.at(hw)->waitable());
    assert(invoke(open_name,o,ev,pa)==0x1299);assert(handles.size()==2);
    assert(ld<uint32_t>(o)==48000 && ld<uint32_t>(o+4)==2 && ld<uint32_t>(o+8)==2 && ld<uint32_t>(o+12)==1);
    assert(out[0x168]==0 && invoke(channel_name,o)==2 && invoke(state_name,o)==1);
    out[0x168]=0x69;
    std::memset(names,0x77,sizeof names);
    assert(invoke(list_name,reinterpret_cast<uint64_t>(names),0)==0);
    assert(invoke(list_name,reinterpret_cast<uint64_t>(names),UINT32_MAX)==0 && names[0]==0x77);
    assert(invoke(list_name,0,1)==0);
    assert(invoke(list_name,reinterpret_cast<uint64_t>(names)+sizeof(names)-128,1)==0);
    assert(invoke(list_name,UINT64_MAX-16,1)==0);
    assert(invoke(list_name,reinterpret_cast<uint64_t>(names),3)==1);
    assert(std::strcmp(reinterpret_cast<char*>(names),"AudioTvOutput")==0 && names[256]==0x77);
    expect_fatal([&]{invoke(state_name,0);});expect_fatal([&]{invoke(start_name,o+8);});
    st<uint32_t>(o+4,6);expect_fatal([&]{invoke(channel_name,o);});st<uint32_t>(o+4,2);
    auto buf=reinterpret_cast<uint64_t>(buffers[0]);
    invoke(info_name,buf,data,4096,16);assert(buffers[0][1]==data && buffers[0][2]==4096 && buffers[0][3]==16);
    assert(invoke("28GetAudioOutBufferDataPointerEPKNS0_14AudioOutBufferE",buf)==data);
    buffers[0][3]=4097;assert(!invoke(append_name,o,buf));buffers[0][3]=15;assert(!invoke(append_name,o,buf));
    buffers[0][3]=16;buffers[0][4]=1;assert(!invoke(append_name,o,buf));buffers[0][4]=0;
    buffers[0][1]=data+1;assert(!invoke(append_name,o,buf));buffers[0][1]=data;
    buffers[0][2]=8*1024*1024;assert(!invoke(append_name,o,buf));buffers[0][2]=4096;
    assert(!invoke(append_name,o,1));assert(invoke(append_name,o,buf)==1);assert(!invoke(append_name,o,buf));
    std::memset(pcm,0x11,sizeof pcm); // sink must consume the accepted snapshot
    buffers[0][1]=1;buffers[0][3]=UINT64_MAX; // descriptor lifetime does not affect the submitted packet
    std::this_thread::sleep_for(std::chrono::milliseconds(10));assert(plat::audio_queued()==0 && !signaled(hr));
    assert(invoke(start_name,o)==0 && invoke(state_name,o)==0);
    if(plat::available && !plat::reject) {
        wait_for([]{return plat::audio_queued()==1;});
        {std::lock_guard lk(host_lock);assert(plat::submissions.front().bytes==std::vector<uint8_t>(16,0x5a));}
        assert(!invoke(released_name,o));complete_one();
    }
    wait_for([&]{return signaled(hr);});assert(invoke(released_name,o)==buf && !signaled(hr));assert(!invoke(released_name,o));
    invoke(stop_name,o);assert(invoke(state_name,o)==1);
    for(int i=0;i<64;i++) {auto b=reinterpret_cast<uint64_t>(buffers[i]);invoke(info_name,b,data,4096,16);assert(invoke(append_name,o,b));}
    auto overflow=reinterpret_cast<uint64_t>(buffers[64]);invoke(info_name,overflow,data,4096,16);assert(!invoke(append_name,o,overflow));
    invoke(close_name,o);assert(ld<uint32_t>(o+12)==1 && !signaled(hr) && out[0x168]==0x69);expect_fatal([&]{invoke(state_name,o);});finalize_event(ev);assert(handles.empty());
    invoke("27InitializeAudioOutParameterEPNS0_17AudioOutParameterE",pa);
    assert(invoke(open_name,o,ev,pa)==0);assert(!invoke(released_name,o) && invoke(channel_name,o)==2);
    if(plat::available && !plat::reject) {
        assert(invoke(append_name,o,buf));invoke(start_name,o);wait_for([]{return plat::audio_queued()==1;});
        invoke(close_name,o);finalize_event(ev);assert(invoke(open_name,o,ev,pa)==0);complete_one();assert(!invoke(released_name,o));
    }
    invoke(close_name,o);finalize_event(ev);assert(handles.empty());
    std::cout<<"PASS real HLE registry/call dispatch: SDK layouts, stereo, state, bounds, buffer ownership, release event, close/reopen ("<<(argc>1?argv[1]:"device")<<")\n";
}
