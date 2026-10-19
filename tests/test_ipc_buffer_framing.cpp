// Original wire-level fixture: the real patched parser dispatches this observer.
#include "kernel-host.h"
#include <limits>
#include <sys/mman.h>
#include <unistd.h>

int main() {
    CPU cpu;
    alignas(16) uint32_t msg[256]{};
    const uint64_t address=0x3000000000ull;
    size_t arguments=8, table_count=1, effects=0, calls=0;
    bool enforce=true, accepted=false;
    ReceiveSizeTable observed;
    IpcFraming frame;
    std::vector<ReceiveSelection> selected;
    std::vector<uint8_t> input;
    auto service=std::make_shared<Service>("framing-observer");
    service->cmds[11]=[&](IpcCtx& c) {
        ++calls; frame=c.framing(); input.assign(c.in,c.in+c.in_size);
        accepted=c.receive_size_table(arguments,table_count,observed);
        selected.clear();
        for(size_t i=0;i<std::min(table_count,c.c.size());++i) {
            auto selection=c.receive_selection(i);selected.push_back(selection);
            if(accepted && enforce) {
                if(c.b.size()!=table_count || c.c.size()!=table_count) accepted=false;
                else if(selection.source==ReceiveDescriptor::B)
                    accepted=c.c[i].addr==0 && c.c[i].size==0 && observed.values[i]==0;
                else
                    accepted=c.b[i].addr==0 && c.b[i].size==0 &&
                        observed.values[i]==c.c[i].size;
            }
        }
        if(accepted) ++effects; // stands for caller mutation, only after all checks
        return accepted?0u:0x1234u;
    };
    service->cmds[77]=[&](IpcCtx& c) {
        ++calls;input.assign(c.in,c.in+c.in_size);frame=c.framing();++effects;return 0u;
    };
    auto session=new_session_handle(service);
    uint32_t root=0;
    size_t raw_start=0, raw_end=0, table_offset=0, cmif=0;
    auto wire=[&](std::vector<bool> pointer,std::vector<uint16_t> sizes,
                  size_t arg_bytes=8,bool domain=false,size_t objects=0,size_t fixed=0,size_t leading_x=0) {
        std::memset(msg,0xa5,sizeof msg); // padding deliberately nonzero
        arguments=arg_bytes;table_count=sizes.size();
        const size_t nb=pointer.size(), nc=sizes.size()+fixed;
        msg[0]=4|(uint32_t(nb)<<24)|(uint32_t(leading_x)<<16);
        size_t p=2;
        for(size_t i=0;i<leading_x;++i) {msg[p++]=0;msg[p++]=0;}
        for(bool use_c:pointer) {
            msg[p++]=use_c?0:4;msg[p++]=use_c?0:uint32_t(address);
            msg[p++]=use_c?0:((uint32_t((address>>32)&15)<<28)|(uint32_t((address>>36)&7)<<2));
        }
        raw_start=p*4;cmif=(raw_start+15)&~size_t(15);
        if(domain) {
            msg[cmif/4]=1u|(uint32_t(objects)<<8)|(uint32_t(16+arg_bytes)<<16);
            msg[cmif/4+1]=root;msg[cmif/4+2]=0;msg[cmif/4+3]=0;cmif+=16;
        }
        msg[cmif/4]=kSFCI;msg[cmif/4+1]=0;msg[cmif/4+2]=11;msg[cmif/4+3]=0;
        std::memset(reinterpret_cast<uint8_t*>(msg)+cmif+16,0,arg_bytes);
        for(size_t i=0;i<objects;++i) st<uint32_t>(reinterpret_cast<uint64_t>(msg)+cmif+16+arg_bytes+i*4,root);
        table_offset=raw_start+((32+(domain?16:0)+arg_bytes+objects*4+1)&~size_t(1));
        for(size_t i=0;i<sizes.size();++i) st<uint16_t>(reinterpret_cast<uint64_t>(msg)+table_offset+2*i,sizes[i]);
        raw_end=(table_offset+2*sizes.size()+3)&~size_t(3);
        msg[1]=uint32_t((raw_end-raw_start)/4)|(nc?uint32_t(nc+2)<<10:0);
        p=raw_end/4;
        for(size_t i=0;i<nc;++i) {
            bool use_c=i<pointer.size()?pointer[i]:true;
            msg[p++]=use_c?uint32_t(address):0;
            msg[p++]=use_c?(uint32_t(address>>32)|(4u<<16)):0;
        }
    };
    auto send=[&](uint64_t bytes=sizeof msg) {
        accepted=false;observed={};
        assert(ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),bytes)==0);
    };
    wire({false},{0});send();
    assert(accepted && observed.offset==60 && observed.values==std::vector<uint16_t>{0});
    assert(input.size()==12 && frame.raw_offset==20 && frame.raw_size==44 && frame.aligned_offset==32);
    assert(frame.receive_list_offset==64 && selected[0].source==ReceiveDescriptor::B);
    auto good_input=input;wire({false},{1});auto before=effects;send();
    assert(!accepted && effects==before && input==good_input && observed.values[0]==1);
    puts("PASS serialized B-active/C-inactive: valid table=0 accepted; malformed table=1 observable/rejected; in_size=12 identical");
    wire({true},{4});send();assert(accepted && selected[0].source==ReceiveDescriptor::C);
    good_input=input;wire({true},{5});before=effects;send();
    assert(!accepted && effects==before && input==good_input && observed.values[0]==5);
    puts("PASS serialized C-active/B-inactive: valid table=4 accepted; malformed table=5 observable/rejected; in_size=12 identical");
    // Missing table with C moved up: structurally valid HIPC, invalid signature.
    wire({false},{0});msg[1]=10|(3u<<10);msg[15]=msg[16];msg[16]=msg[17];
    before=effects;send();assert(!accepted && effects==before && observed.values.empty() && input.size()==8);
    wire({false,true},{1,4});before=effects;send();assert(!accepted && effects==before);
    // Both active is observable but is not a valid auto-select signature.
    wire({false},{0});msg[16]=uint32_t(address);msg[17]=uint32_t(address>>32)|(4u<<16);
    before=effects;send();assert(!accepted && effects==before);
    // Extra words cannot masquerade as the expected signature either.
    wire({false},{0});msg[1]=12|(3u<<10);msg[17]=msg[16];msg[18]=0;
    before=effects;send();assert(!accepted && effects==before);
    puts("PASS missing table and overlong raw length rejected before observer side effect");
    for(size_t nx=0;nx<4;++nx) for(size_t arg:{0u,1u,2u,3u,7u,8u,9u}) {
        wire({false,true},{0,4},arg,false,0,0,nx);send();
        assert(accepted && observed.offset==table_offset && observed.values.size()==2);
        assert(selected[0].source==ReceiveDescriptor::B && selected[1].source==ReceiveDescriptor::C);
    }
    std::vector<bool> choices;std::vector<uint16_t> sizes;
    for(size_t i=0;i<13;++i) {choices.push_back(i%2);sizes.push_back(i%2?4:0);}
    wire(choices,sizes);send();assert(accepted && observed.values.size()==13);
    enforce=false;wire({true},{4},8,false,0,1);send();
    assert(accepted && observed.values.size()==1); // fixed C pointer has no table entry
    enforce=true;
    puts("PASS multiple B/C descriptors, all four alignment pads, odd argument lengths, nonzero padding and fixed C pointer");
    auto malformed=[&](uint64_t bytes=sizeof msg) {
        auto saved=std::vector<uint32_t>(msg,msg+256);auto n=calls,e=effects;
        auto handles=kstate::g_handles.size();auto next=kstate::g_next_handle;
        bool rejected=false;
        try {ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),bytes);}
        catch(const std::runtime_error& ex) {rejected=std::string(ex.what())=="ipc: malformed request framing";}
        assert(rejected && calls==n && effects==e && std::equal(saved.begin(),saved.end(),msg));
        assert(handles==kstate::g_handles.size() && next==kstate::g_next_handle);
    };
    wire({false},{0});malformed(71); // C descriptor exceeds packet
    wire({false},{0});malformed(19); // B descriptor truncated
    wire({false},{0});msg[1]=0x3ff;malformed();
    wire({false},{0});msg[1]|=1u<<20;malformed();
    wire({false},{0});msg[1]=(msg[1]&~(15u<<10))|(1u<<10);malformed();
    wire({false},{0});malformed(std::numeric_limits<uint64_t>::max());
    // Back the exact 72-byte packet with an inaccessible next page. Relative
    // alignment must work even when the packet base is only eight-byte aligned.
    const size_t page=size_t(sysconf(_SC_PAGESIZE));
    auto* pages=static_cast<uint8_t*>(mmap(nullptr,page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0));
    assert(pages!=MAP_FAILED && mprotect(pages+page,page,PROT_NONE)==0);
    wire({false},{0});auto* boundary=pages+page-72;std::memcpy(boundary,msg,72);
    assert(ipc_request(cpu,session,reinterpret_cast<uint64_t>(boundary),72)==0 && accepted);
    wire({false},{0});msg[1]=12|(3u<<10);std::memcpy(boundary,msg,72);
    auto old_calls=calls;bool guard_rejected=false;
    try {ipc_request(cpu,session,reinterpret_cast<uint64_t>(boundary),72);}
    catch(const std::runtime_error&) {guard_rejected=true;}
    assert(guard_rejected && calls==old_calls);assert(munmap(pages,page*2)==0);
    // Signature-size overflow cannot escape the bounded helper.
    wire({false},{0});arguments=std::numeric_limits<size_t>::max();before=effects;send();assert(!accepted && effects==before);
    wire({false},{0});table_count=std::numeric_limits<size_t>::max();
    // Test the helper directly here; an absurd count is not a loop bound in a real handler.
    IpcCtx direct;ReceiveSizeTable table;assert(!direct.receive_size_table(0,table_count,table));
    before=effects;send();assert(!accepted && effects==before && observed.values.empty());
    table_count=1;
    puts("PASS truncated descriptors/raw data, guard-page packet boundary, unsupported framing and overflowing lengths rejected atomically");
    // Convert through the real CMIF control path, then dispatch through domain.
    std::memset(msg,0,sizeof msg);msg[0]=5;msg[1]=8;msg[4]=kSFCI;
    assert(ipc_request(cpu,session,reinterpret_cast<uint64_t>(msg),sizeof msg)==0);root=msg[8];assert(root);
    wire({false,true},{0,4},8,true,2);send();
    assert(accepted && frame.domain && frame.domain_data_size==24 && frame.domain_object_count==2 && input.size()==8);
    wire({true},{4},8,true);msg[(cmif-16)/4]=(1u|(60u<<16));malformed();
    // Same packet bytes cannot declare overlapping signature/object/table regions.
    wire({true},{4},8,true,1);arguments=9;before=effects;send();assert(!accepted && effects==before);
    // Ordinary domain request does not require a table.
    wire({}, {},8,true);msg[cmif/4+2]=77;send();assert(input.size()==8 && frame.domain);
    puts("PASS domain table/object framing, declared-size overlap rejection and ordinary domain request");
    handle_close(session);
    session=new_session_handle(service);
    wire({}, {},8);msg[cmif/4+2]=77;send();assert(input.size()==8 && !frame.domain);
    // TIPC preserves its unaligned raw payload and never claims CMIF table metadata.
    std::memset(msg,0,sizeof msg);msg[0]=16+77;msg[1]=2;msg[2]=123;send();
    assert(input.size()==8 && frame.raw_offset==8 && frame.raw_size==8);
    IpcCtx ctx;ctx.in_size=8;ctx.in=reinterpret_cast<const uint8_t*>(msg);
    assert(ctx.arg<uint32_t>(std::numeric_limits<size_t>::max())==0);
    handle_close(session);
    puts("PASS ordinary non-domain and TIPC dispatch unchanged; bounded argument overflow check");
}
