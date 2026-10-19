// Synthetic host and guest memory; actual composed loader registry and HID translation unit.
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include "kernel.h"
#include "platform.h"
namespace nx {
std::vector<std::pair<uint64_t,uint64_t>> regions;
void region(void* p,size_t n) { regions.push_back({reinterpret_cast<uint64_t>(p),n}); }
VmInfo vm_query(uint64_t a) {
    for(auto [p,n]:regions) if(a>=p && a-p<n) return {p,n,kMemHeap,3};
    return {a,4096,kMemFree,0};
}
bool commit(uint64_t,uint64_t) {return true;}
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) {}
void backtrace(CPU&) {}
namespace plat {
PadState host{}; unsigned polls=0;
void read_pad(PadState& p) {++polls;p=host;}
uint64_t monotonic_ns() {return 0;}
void sleep_ns(int64_t) {}
std::string data_root() {return ".";}
void log_line(const char*) {}
[[noreturn]] void exit_process(int) {throw std::runtime_error("strict fatal");}
}
}
#include "loader.cpp"
#include "hle_hid.cpp"
using namespace nx;
uint64_t address(void* p) {return reinterpret_cast<uint64_t>(p);}
uint64_t invoke(const char* suffix,uint64_t a=0,uint64_t b=0,uint64_t d=0,uint64_t e=0) {
    auto name=std::string("_ZN2nn3hid")+suffix;assert(hle_lookup(name.c_str()));
    CPU c{};c.x[0]=a;c.x[1]=b;c.x[2]=d;c.x[3]=e;
    call(c,hle_address(name.c_str()));return c.x[0];
}
void expect_fatal(auto fn) {bool caught=false;try{fn();}catch(const std::runtime_error&){caught=true;}assert(caught);}
const char *style="24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE",
 *ids_name="22SetSupportedNpadIdTypeEPKjm",
 *mode="29SetNpadHandheldActivationModeENS0_26NpadHandheldActivationModeE",
 *get_style="15GetNpadStyleSetERKj";
int main() {
    alignas(16) uint8_t out[16*0x28+32], raw[0x290+32];
    uint32_t ids[10]={0,32,1,2,3,4,5,6,7,16},invalid=99,other=1,handheld=32;
    region(out,sizeof out);region(raw,sizeof raw);region(ids,sizeof ids);region(&invalid,4);region(&other,4);region(&handheld,4);
    auto p=address(out+16),r=address(raw+16),id=address(ids);
    const char* single[5]={"12GetNpadStateEPNS0_16NpadFullKeyStateERKj","12GetNpadStateEPNS0_17NpadHandheldStateERKj",
        "12GetNpadStateEPNS0_16NpadJoyDualStateERKj","12GetNpadStateEPNS0_16NpadJoyLeftStateERKj","12GetNpadStateEPNS0_17NpadJoyRightStateERKj"};
    const char* plural[5]={"13GetNpadStatesEPNS0_16NpadFullKeyStateEiRKj","13GetNpadStatesEPNS0_17NpadHandheldStateEiRKj",
        "13GetNpadStatesEPNS0_16NpadJoyDualStateEiRKj","13GetNpadStatesEPNS0_16NpadJoyLeftStateEiRKj","13GetNpadStatesEPNS0_17NpadJoyRightStateEiRKj"};
    expect_fatal([&]{invoke(single[0],p,id);});
    invoke("14InitializeNpadEv");invoke("14InitializeNpadEv");
    invoke(ids_name,id,2);invoke(mode,0);invoke(style,7); // Exact observed main startup sequence.
    assert(invoke(get_style,id)==1 && invoke(get_style,address(&other))==0 && invoke(get_style,address(&handheld))==0);
    plat::host={plat::kA|plat::kZR,-32767,20000,45000,-45000};
    for(int i=0;i<5;i++) {
        std::memset(out,0xa5,sizeof out);invoke(single[i],p,id);
        assert(out[15]==0xa5 && out[16+0x28]==0xa5 && ld<uint64_t>(p)>0);
        assert(ld<uint32_t>(p+32)==unsigned(i==0));
        if(i==0) {
            assert((ld<uint64_t>(p+8)&(plat::kA|plat::kZR|plat::kStickLLeft|plat::kStickLUp))==(plat::kA|plat::kZR|plat::kStickLLeft|plat::kStickLUp));
            assert(ld<int32_t>(p+16)==-32767 && ld<int32_t>(p+20)==20000 && ld<int32_t>(p+24)==32767 && ld<int32_t>(p+28)==-32767);
        } else for(int k=8;k<0x28;k++) assert(out[16+k]==0);
        auto before=plat::polls;
        assert(invoke(plural[i],0,0,0)==0 && invoke(plural[i],0,UINT32_MAX,0)==0 && plat::polls==before);
        assert(invoke(plural[i],p,16,id)==1);
        for(int j=0;j<20;j++) invoke(plural[i],p,16,id);
        std::memset(out,0xa5,sizeof out);assert(invoke(plural[i],p,100,id)==16);
        assert(out[15]==0xa5 && out[16+16*0x28]==0xa5);
        for(int j=1;j<16;j++) assert(ld<uint64_t>(p+(j-1)*0x28)>ld<uint64_t>(p+j*0x28));
        expect_fatal([&]{invoke(single[i],0,id);});expect_fatal([&]{invoke(single[i],p,0);});
        expect_fatal([&]{invoke(single[i],address(out)+sizeof(out)-8,id);});
        expect_fatal([&]{invoke(single[i],p,address(&invalid));});
        expect_fatal([&]{invoke(plural[i],UINT64_MAX-8,1,id);});
    }
    // Histories are isolated between ids and styles, and policy transitions flush old presses.
    invoke(style,1);assert(invoke(plural[0],p,16,id)==1);
    assert(invoke(plural[0],p,16,address(&other))==1 && ld<uint64_t>(p+8)==0);
    plat::host={};assert(invoke(plural[0],p,16,id)==2);
    assert(ld<uint64_t>(p+8)==0 && ld<uint64_t>(p+0x28+8)!=0);
    invoke(style,6);invoke(single[0],p,id);assert(ld<uint32_t>(p+32)==0 && ld<uint64_t>(p+8)==0);
    invoke(style,1);invoke(ids_name,0,0);assert(invoke(get_style,id)==0);invoke(ids_name,id,2);
    invoke(single[0],p,address(&other));assert(ld<uint32_t>(p+32)==0);
    // Invalid policy updates are atomic: the enabled endpoint survives rejection.
    expect_fatal([&]{invoke(ids_name,address(&invalid),1);});assert(invoke(get_style,id)==1);
    expect_fatal([&]{invoke(ids_name,0,1);});expect_fatal([&]{invoke(ids_name,id,11);});
    ids[1]=0;expect_fatal([&]{invoke(ids_name,id,2);});ids[1]=32;
    expect_fatal([&]{invoke(mode,3);});expect_fatal([&]{invoke(style,32);});
    invoke("14DisconnectNpadERKj",id);assert(invoke(get_style,id)==0);
    std::memset(out,0xa5,sizeof out);assert(invoke(plural[0],p,16,id)==1);
    assert(ld<uint64_t>(p+8)==0 && ld<uint32_t>(p+32)==0 && out[16+0x28]==0xa5);
    invoke(ids_name,id,2);invoke(style,1);assert(invoke(get_style,id)==0); // No invented reconnect.
    const char* raw_names[]={"13GetMouseStateEPNS0_10MouseStateE","16GetKeyboardStateEPNS0_13KeyboardStateE",
        "19GetTouchScreenStateILm16EEEvPNS0_16TouchScreenStateIXT_EEE"};
    const int sizes[]={0x28,0x30,0x290};
    invoke("15InitializeMouseEv");invoke("18InitializeKeyboardEv");invoke("21InitializeTouchScreenEv");
    for(int i=0;i<3;i++) {
        std::memset(raw,0xa5,sizeof raw);invoke(raw_names[i],r);
        for(int k=0;k<sizes[i];k++) assert(raw[16+k]==0);
        assert(raw[15]==0xa5 && raw[16+sizes[i]]==0xa5);
        expect_fatal([&]{invoke(raw_names[i],0);});
    }
    assert(invoke("14GetMouseStatesEPNS0_10MouseStateEi",0,0)==0);
    std::memset(raw,0xa5,sizeof raw);
    assert(invoke("23GetSixAxisSensorHandlesEPNS0_19SixAxisSensorHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE",r,4,id,1)==0 && raw[16]==0xa5);
    assert(invoke("22GetSixAxisSensorStatesEPNS0_18SixAxisSensorStateEiRKNS0_19SixAxisSensorHandleE",r,4,id)==0 && raw[16]==0xa5);
    expect_fatal([&]{invoke("21GetSixAxisSensorStateEPNS0_18SixAxisSensorStateERKNS0_19SixAxisSensorHandleE",r,id);});
    expect_fatal([&]{invoke("21ShowControllerSupportERKNS0_20ControllerSupportArgE",r);});
    expect_fatal([&]{invoke("18StartSixAxisSensorERKNS0_19SixAxisSensorHandleE",id);});
    expect_fatal([&]{invoke("21ShowControllerSupportEPNS0_27ControllerSupportResultInfoERKNS0_20ControllerSupportArgE",r,id);});
    assert(raw[16]==0xa5 && invoke("20IsVibrationPermittedEv")==0);
    assert(invoke("25GetVibrationDeviceHandlesEPNS0_21VibrationDeviceHandleEiRKjNS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE",r,4,id,1)==0 && raw[16]==0xa5);
    std::cout<<"PASS actual HLE registry/call dispatch: exact startup API, five Npad ABIs, host buttons/sticks, styles/ids, bounded isolated histories, disconnection, canaries, null/invalid arguments, raw device absence, honest unsupported sensors/applet\n";
}
