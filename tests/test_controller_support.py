"""Execute the actual ordered pinned HID handlers and HLE registry with synthetic input."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime

PATCHES = ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
           'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch',
           'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-hid.patch',
           'astral-controller-support.patch')

FIXTURE = r'''
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include "kernel.h"
#include "platform.h"
namespace nx {
struct Region {uint64_t a,n;uint32_t perm;}; std::vector<Region> regions;
void region(void* p,size_t n,uint32_t perm=3) {regions.push_back({uint64_t(p),n,perm});}
VmInfo vm_query(uint64_t a) {
 for(auto r:regions) if(a>=r.a && a-r.a<r.n) return {r.a,r.n,kMemHeap,r.perm};
 return {a,4096,kMemFree,0};
}
bool commit(uint64_t,uint64_t) {return true;}
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) {}
void backtrace(CPU&) {}
namespace plat {
PadState host{}; unsigned polls=0;
void read_pad(PadState& p) {++polls;p=host;}
uint64_t monotonic_ns() {return 0;} void sleep_ns(int64_t) {}
std::string data_root() {return ".";} void log_line(const char*) {}
[[noreturn]] void exit_process(int) {throw std::runtime_error("strict fatal");}
}}
#include "loader.cpp"
#include "hle_hid.cpp"
using namespace nx;
uint64_t invoke(const char* name,uint64_t a=0,uint64_t b=0) {
 std::string n=std::string("_ZN2nn3hid")+name;assert(hle_lookup(n.c_str()));
 CPU c{};c.x[0]=a;c.x[1]=b;call(c,hle_address(n.c_str()));return c.x[0];
}
void bad(auto fn) {bool caught=false;try{fn();}catch(const std::runtime_error&){caught=true;}assert(caught);}
int main() {
 const char* one="21ShowControllerSupportERKNS0_20ControllerSupportArgE";
 const char* two="21ShowControllerSupportEPNS0_27ControllerSupportResultInfoERKNS0_20ControllerSupportArgE";
 const char* set_ids="22SetSupportedNpadIdTypeEPKjm";
 const char* set_styles="24SetSupportedNpadStyleSetENS_4util10BitFlagSetILi32ENS0_12NpadStyleTagEEE";
 uint8_t arg[0x21c]{},out[24],state[0x28];uint32_t id=0;
 region(arg,sizeof arg,1);region(out,sizeof out);region(&id,4);region(state,sizeof state);
 auto a=uint64_t(arg),o=uint64_t(out+8),i=uint64_t(&id);
 arg[0]=1;arg[1]=1;arg[2]=arg[3]=arg[4]=arg[5]=1;
 bad([&]{invoke(one,a);});invoke("14InitializeNpadEv");
 std::memset(out,0xa5,sizeof out);
 assert(invoke(two,o,a)==0x183aca && out[8]==0xa5); // no configured endpoint
 invoke(set_ids,i,1);invoke(set_styles,7);
 plat::host={plat::kA,100,200,300,400};
 invoke("12GetNpadStateEPNS0_16NpadFullKeyStateERKj",uint64_t(state),i);
 assert(ld<uint64_t>(uint64_t(state)+8)==plat::kA);
 const auto before=plat::polls;
 assert(invoke(one,a,UINT64_MAX)==0 && plat::polls==before); // no output ABI, no invented input
 assert(invoke(two,o,a)==0);
 arg[0]=0;assert(invoke(one,a)==0);arg[0]=1;
 uint8_t overlap[0x21c]{};std::memcpy(overlap,arg,sizeof arg);region(overlap,sizeof overlap);
 assert(invoke(two,uint64_t(overlap),uint64_t(overlap))==0 && overlap[0]==1 && overlap[1]==0);
 assert(out[7]==0xa5 && out[16]==0xa5 && out[8]==1);
 for(unsigned j=9;j<16;j++) assert(out[j]==0);
 // Preserve existing state and host input across automatic confirmation.
 invoke("12GetNpadStateEPNS0_16NpadFullKeyStateERKj",uint64_t(state),i);
 assert(ld<uint64_t>(uint64_t(state)+8)==plat::kA && invoke("15GetNpadStyleSetERKj",i)==1);
 for(int n: {2,4}) {arg[1]=n;std::memset(out,0xa5,sizeof out);assert(invoke(two,o,a)==0x183aca && out[8]==0xa5);}
 arg[1]=1;
 for(unsigned k: {2u,6u,23u}) {auto saved=arg[k];arg[k]=k==2?0:1;assert(invoke(one,a)==0x183aca);arg[k]=saved;}
 invoke(set_styles,2);assert(invoke(one,a)==0x183aca);invoke(set_styles,1);
 invoke(set_ids,0,0);assert(invoke(one,a)==0x183aca);invoke(set_ids,i,1);
 for(auto pair: {std::pair{0,5},std::pair{0,255},std::pair{1,0},std::pair{1,5}}) {
  auto saved=arg[pair.first];arg[pair.first]=pair.second;bad([&]{invoke(one,a);});arg[pair.first]=saved;
 }
 arg[2]=2;bad([&]{invoke(one,a);});arg[2]=1;
 bad([&]{invoke(one,0);});bad([&]{invoke(one,a+1);});bad([&]{invoke(one,UINT64_MAX-16);});
 bad([&]{invoke(two,0,a);});bad([&]{invoke(two,uint64_t(out)+20,a);});bad([&]{invoke(two,UINT64_MAX-3,a);});
 bad([&]{invoke(two,a,a);}); // read-only output
 uint8_t unreadable[0x21c]{};region(unreadable,sizeof unreadable,2);
 bad([&]{invoke(one,uint64_t(unreadable));});
 invoke("14DisconnectNpadERKj",i);assert(invoke(one,a)==0x183aca);
 bad([&]{invoke("18StartSixAxisSensorERKNS0_19SixAxisSensorHandleE",i);});
 bad([&]{invoke("21StartLrAssignmentModeEv");});
 std::cout<<"PASS actual applied HLE: both overload ABIs, configured logical FullKey, absent/disconnected controller, player/style policy, malformed/unmapped/read-only/overflow extents, result canaries, preserved input and strict unsupported boundaries\n";
}
'''

class ControllerSupportTests(unittest.TestCase):
    def test_actual_ordered_handlers(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('HID_REFERENCE', str(common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'clean pinned runtime required via HID_REFERENCE')
        output = ROOT / '.local/controller-051' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / n for n in PATCHES]
        fingerprint = runtime.prepare_source(reference, output / 'source', patches)
        fixture = output / 'fixture.cpp'
        fixture.write_text(FIXTURE)
        source = output / 'source'
        argv = [shutil.which('c++'), '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1',
                '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), str(fixture), '-o', str(output / 'test')]
        build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        result = subprocess.run([str(output / 'test')], cwd=output, capture_output=True, text=True, timeout=10)
        (output / 'result.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS actual applied HLE', result.stdout)
        receipt = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source': fingerprint,
                   'fixture_sha256': runtime.sha(fixture), 'compile': argv, 'binary_sha256': runtime.sha(output / 'test'),
                   'exit_code': result.returncode, 'output': result.stdout}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(result.stdout, end='')
        print('private receipt:', output / 'receipt.json')

if __name__ == '__main__':
    unittest.main()
