"""Execute the patched production decode, recording, replay and fence paths with synthetic adapters.

Applies the real overlay to the pinned public source without downloads. No game inputs, credentials,
VMs or cloud calls are used. SPIR-V fixtures are original and validated by SPIRV-Tools.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime
import test_astral_shader_cache as previous

OVERLAY = 'astral-nvn-gaps.patch'
ORDER = (*previous.ORDER, OVERLAY)


def region(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


COMMON = r'''
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include "nvn/nvn_draw_state.h"
#include "nvn/nvn_gap_helpers.h"
#include "platform.h"
namespace nx {
void log(const char*, ...) {}
[[noreturn]] void fatal(const char* f, ...) { throw std::runtime_error(f); }
}
'''

DRAW = COMMON + r'''
namespace nx::nvn {
std::vector<Cmd> recorded;
void record(uint64_t, Cmd c, const void*, size_t) { recorded.push_back(c); }
std::atomic<uint64_t> g_recorded_draws{0};
@RECORD@
namespace replay {
uint8_t args[24]{};
bool args_written = false, indices_written = false, separate = false;
const uint8_t* guest_bytes(uint64_t a) { return a == 0x404 ? args+1 : args; }
bool written_separate() { return separate; }
bool written_overlaps(const uint8_t* p, uint64_t n) {
    if (p == args+1) { assert(n == 20); return args_written; }
    return indices_written;
}
}
int checkpoints = 0, draws = 0;
Cmd drawn{Cmd::DrawElements};
VkCommandBuffer replay_checkpoint(VkCommandBuffer cb) {
    ++checkpoints;
    uint32_t values[] = {9, 3, 7, uint32_t(-5), 11};
    std::memcpy(replay::args+1, values, sizeof values);  // stand in for completed compute write-back
    return cb;
}
void draw_command(VkCommandBuffer, const Cmd& c, const CmdList&, const Targets&) { drawn=c; ++draws; }
void indirect_replay(VkCommandBuffer cb, const Cmd& c, const CmdList& list, Targets st) {
    switch (c.op) { @REPLAY@ default: break; }
}
}
int main() {
    using namespace nx; using namespace nx::nvn;
    CPU c{}; c.x[0]=1; c.x[1]=5; c.x[2]=1; c.x[3]=0x1000; c.x[4]=0x404;
    DrawElementsIndirect(c); assert(recorded.size()==1 && recorded[0].a[1]==0x404);
    assert(checkpoints==0 && replay::args[1]==0);  // recording must not read arguments
    replay::args_written = true;
    indirect_replay({}, recorded[0], {}, {});
    assert(checkpoints==1 && draws==1 && drawn.n==5 && drawn.mask==1);
    assert(drawn.a[0]==0x100e && drawn.i[0]==9 && drawn.i[1]==-5 && drawn.i[2]==11 && drawn.i[3]==3);
    // CPU-produced arguments must draw without flushing any work. Native 16/32-bit GPU
    // index reads stay ordered through written_read; CPU 8-bit widening needs completion.
    replay::args_written = false;
    indirect_replay({}, recorded[0], {}, {}); assert(checkpoints==1 && draws==2);
    replay::indices_written = true;
    indirect_replay({}, recorded[0], {}, {}); assert(checkpoints==1 && draws==3);
    auto narrow = recorded[0]; narrow.mask=0;
    indirect_replay({}, narrow, {}, {}); assert(checkpoints==2 && draws==4);
    replay::indices_written = false; replay::separate = true;
    indirect_replay({}, recorded[0], {}, {}); assert(checkpoints==3 && draws==5);
    replay::separate = false;
    for (uint32_t type=0; type<3; ++type) {
        Cmd in=recorded[0], out{Cmd::DrawElements}; in.mask=type;
        assert(replay::decode_indexed_indirect(in,replay::args+1,out));
        assert(out.a[0]==0x1000+7*(1u<<type));
    }
    uint32_t zero_count[]={0,2,0,0,0}, zero_instances[]={2,0,0,0,0};
    assert(!replay::decode_indexed_indirect(recorded[0],reinterpret_cast<uint8_t*>(zero_count),drawn));
    assert(!replay::decode_indexed_indirect(recorded[0],reinterpret_cast<uint8_t*>(zero_instances),drawn));
    auto fails=[&](Cmd in,const uint8_t* bytes) {try {replay::decode_indexed_indirect(in,bytes,drawn);} catch(const std::runtime_error&) {return true;}return false;};
    assert(fails(recorded[0],nullptr));
    Cmd bad=recorded[0]; bad.mask=3; assert(fails(bad,replay::args+1));
    bad=recorded[0];bad.a[0]=UINT64_MAX-1;assert(fails(bad,replay::args+1));
    c.x[1]=0xdeadbeef;c.v[0].f32[0]=0.375f;SetAlphaRef(c);assert(recorded.back().f[0]==0.375f);
    c.v[0].f32[0]=2.5f;SetLineWidth(c);assert(recorded.back().f[0]==2.5f);
    assert(supported_line_width(2.5f,true,1,4)==2.5f);
    assert(supported_line_width(20,true,1,4)==4 && supported_line_width(.5f,true,1,4)==1);
    assert(supported_line_width(4,false,1,1)==1);
    try {supported_line_width(0,false,1,1);assert(false);} catch(const std::runtime_error&) {}
    std::cout<<"PASS recording/replay: late GPU arguments, unaligned record, all index sizes, signed base vertex, base instance, zero draws, invalid addresses, float ABI and line limits\n";
}
'''

FENCES = COMMON + r'''
namespace nx::plat { void perf_hint_thread() {} }
namespace nx::nvn {
ObjectsLock& objects_lock() { static ObjectsLock lock;return lock; }
std::unordered_map<uint64_t,std::unique_ptr<Object>>& objects() {static std::unordered_map<uint64_t,std::unique_ptr<Object>> o;return o;}
Object* find_object(uint64_t k,uint64_t) {auto i=objects().find(k);return i==objects().end()?nullptr:i->second.get();}
bool resolve_cache_on() {return false;}
void defer_object(std::unique_ptr<Object>) {}
std::vector<Cmd> recorded;
void record(uint64_t,Cmd c,const void*,size_t) {recorded.push_back(c);}
std::map<uint64_t,std::shared_ptr<CmdList>> lists;
std::shared_ptr<CmdList> command_list(uint64_t h) {return lists[h];}
std::vector<std::function<void()>> jobs;
uint64_t worker_run(std::function<void()> f) {jobs.push_back(std::move(f));return jobs.size();}
void worker_wait(uint64_t) {}
bool gpu_wait(uint64_t) {return false;}
DeferredValues deferred_snapshot(const std::vector<std::shared_ptr<CmdList>>&) {return {};}
std::atomic<bool> gpu_entered{false}, gpu_release{false};
bool gpu_submit(const std::vector<std::shared_ptr<CmdList>>&,std::shared_ptr<const DeferredValues>,bool wait_done) {
    assert(wait_done);gpu_entered=true;while(!gpu_release)std::this_thread::yield();return true;
}
@COMPLETION@
namespace {
void tl(const char*,uint64_t=0) {}
void wait_submits(uint64_t,int) {}
std::mutex g_sub_lock;
uint64_t g_sub_called=0, g_presents=0;
void submit_done() {}
@SYNC@
@SUBMIT@
@ORIGIN@
}
}
int main() {
    using namespace nx;using namespace nx::nvn;
    CPU c{};c.x[0]=0x100;SyncInitialize(c);
    c={};c.x[0]=0x200;c.x[1]=0x100;CommandBufferFenceSync(c);
    assert(recorded.size()==1 && recorded[0].op==Cmd::FenceSync);
    auto first=get<Sync>(0x100)->command_completion;
    c={};c.x[0]=0x100;c.x[1]=0;SyncWait(c);assert(c.x[0]==2);  // record is not a signal
    auto list=std::make_shared<CmdList>();list->cmds=recorded;lists[7]=list;
    // Fence in a nested command list must arm too.
    auto outer=std::make_shared<CmdList>();Cmd call{Cmd::CallList};call.a[0]=7;outer->cmds.push_back(call);lists[9]=outer;
    uint64_t handle=9;CPU submit{};submit.x[1]=1;submit.x[2]=uint64_t(&handle);
    QueueSubmitCommands(submit);assert(jobs.size()==1);
    std::thread replay([&] {jobs[0]();});
    while(!gpu_entered)std::this_thread::yield();
    c={};c.x[0]=0x100;c.x[1]=1000000;SyncWait(c);assert(c.x[0]==2);  // GPU still in flight
    std::thread release([] {std::this_thread::sleep_for(std::chrono::milliseconds(15));gpu_release=true;});
    c={};c.x[0]=0x100;c.x[1]=UINT64_MAX;SyncWait(c);assert(c.x[0]==1);
    replay.join();release.join();
    c={};c.x[0]=0x100;SyncWait(c);assert(c.x[0]==0);
    // Reuse creates a fresh pending completion. Old signals cannot satisfy it.
    QueueSubmitCommands(submit);auto second=get<Sync>(0x100)->command_completion;
    assert(second!=first);first->signal();assert(second->wait(0)==2);jobs[1]();assert(second->wait(0)==0);
    // An older queued submission cannot release a wait on a newer queued execution.
    QueueSubmitCommands(submit);auto third=get<Sync>(0x100)->command_completion;
    QueueSubmitCommands(submit);auto fourth=get<Sync>(0x100)->command_completion;
    jobs[2]();assert(third->wait(0)==0 && fourth->wait(0)==2);jobs[3]();assert(fourth->wait(0)==0);
    // Retained pending state survives finalization; a recycled guest sync gets its own state.
    c={};c.x[0]=0x100;SyncFinalize(c);SyncInitialize(c);assert(!get<Sync>(0x100)->command_completion);
    c={};c.x[1]=1;DeviceSetWindowOriginMode(c);DeviceGetWindowOriginMode(c);assert(c.x[0]==1);
    c.x[1]=0;try {DeviceSetWindowOriginMode(c);assert(false);} catch(const std::runtime_error&) {}
    std::cout<<"PASS command fences: recording/pending/timeout/condition/already, nested lists, GPU completion, repeat and overlapping submissions, finalization and origin validation\n";
}
'''

SPIRV = COMMON + r'''
int main(int argc,char** argv) {
    using namespace nx::nvn;
    std::ifstream f(argv[1],std::ios::binary|std::ios::ate);auto bytes=f.tellg();f.seekg(0);
    std::vector<uint32_t> original(size_t(bytes)/4);f.read(reinterpret_cast<char*>(original.data()),bytes);
    auto code=original;uint32_t mode=uint32_t(std::stoul(argv[3]));
    assert(patch_alpha_test(code,mode));
    if(mode==0||mode==8)assert(code==original);
    std::ofstream out(argv[2],std::ios::binary);out.write(reinterpret_cast<const char*>(code.data()),code.size()*4);
    std::vector<uint32_t> bad{0x07230203,0x10000,0,2,0,0};assert(!patch_alpha_test(bad,2));
    std::cout<<"PASS alpha SPIR-V mode "<<mode<<"\n";
}
'''

ASSEMBLY = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %color
OpExecutionMode %main OriginUpperLeft
OpExecutionMode %main EarlyFragmentTests
OpDecorate %color Location 0
%void = OpTypeVoid
%float = OpTypeFloat 32
%bool = OpTypeBool
%v4 = OpTypeVector %float 4
%ptr = OpTypePointer Output %v4
%fn = OpTypeFunction %void
%half = OpConstant %float 0.5
%rgba = OpConstantComposite %v4 %half %half %half %half
%color = OpVariable %ptr Output
%main = OpFunction %void None %fn
%label = OpLabel
OpStore %color %rgba
OpReturn
OpFunctionEnd
'''


class NvnGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        repo = common.parent
        cls.reference = Path(os.environ.get('NVN_REFERENCE', repo / '.local/owner-build/work/upstream/SuperMarioWonderRecomp'))
        cls.vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', '/opt/homebrew/include'))
        cls.compiler = shutil.which('c++')
        if not cls.reference.is_dir() or not cls.compiler or not (cls.vulkan / 'vulkan/vulkan.h').is_file():
            raise AssertionError('Existing pinned NVN_REFERENCE, c++ and NVN_VULKAN_INCLUDE required; no downloads')
        private = repo / '.local/units/NVN-PERF-015'
        private.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='tests-', dir=private)
        cls.out = Path(cls.temp.name)
        cls.source = cls.out / 'source'
        cls.order = list(ORDER)
        cls.patch = ROOT / 'runtime/patches' / OVERLAY
        prepare_runtime.prepare_source(cls.reference, cls.source, [ROOT / 'runtime/patches' / x for x in cls.order])
        cls.nvn = cls.source / 'runtime/src/nvn'
        cls.includes = ['-I', str(cls.source / 'runtime/include'), '-I', str(cls.source / 'runtime/src'), '-I', str(cls.vulkan)]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def compile(self, name, source):
        src = self.out / (name + '.cpp'); src.write_text(source)
        exe = self.out / name
        p = subprocess.run([self.compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', *self.includes,
                            str(src), '-o', str(exe)], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return exe

    def run_exe(self, exe, *args):
        p = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        print(p.stdout, end='')

    def test_platform_overlay_application(self):
        for platform in ('linux', 'windows'):
            order = [x for x in (ROOT / ('runtime/patches/series.' + platform)).read_text().splitlines()
                     if x and not x.startswith('#')]
            # Exercise the candidate insertions without enabling a failed performance gate.
            for name in ('astral-shader-cache.patch', OVERLAY):
                if name not in order:
                    order.insert(order.index('astral-linux.patch'), name)
            target = self.out / platform
            prepare_runtime.prepare_source(self.reference, target, [ROOT / 'runtime/patches' / x for x in order])
            self.assertTrue((target / 'runtime/src/nvn/nvn_gap_helpers.h').is_file())
        print('PASS Linux/Windows overlay application with documented shader-cache prerequisite')

    def test_record_and_ordered_indirect_replay(self):
        state = (self.nvn / 'nvn_state.cpp').read_text()
        replay = (self.nvn / 'nvn_replay.cpp').read_text()
        code = DRAW.replace('@RECORD@', region(state, 'void DrawElementsIndirect', 'void ignore'))
        code = code.replace('@REPLAY@', region(replay, '            case Cmd::DrawElementsIndirect:', '            case Cmd::CopyTextureToTexture:'))
        self.run_exe(self.compile('draw', code))

    def test_written_allocation_guards(self):
        code = COMMON + r'''
int main() {
    using namespace nx::nvn;
    constexpr uint64_t cap = 256ull << 20;
    assert(written_range_fits(0x1000, 4096, 65536, cap));
    assert(!written_range_fits(0, 4096, 4096, cap));
    assert(!written_range_fits(UINTPTR_MAX-7, 8, 8, cap));
    assert(!written_range_fits(0x1000, cap+1, cap+1, cap));
    assert(!written_range_fits(0x1000, 4096, 4095, cap));
    assert(written_copy_fits(4096, 256, 65536, cap));
    assert(!written_copy_fits(cap, 0, cap, cap));
    assert(!written_copy_fits(4096, UINT64_MAX-15, 65536, cap));
    assert(!written_copy_fits(4096, 0, UINT64_MAX, cap));
    assert(!written_copy_fits(4096, 0, 4096, 255));
    std::cout << "PASS written_bind guards: valid range, null/overflow, oversized snapshot, merged padding and ring bounds\n";
}
'''
        self.run_exe(self.compile('written_guards', code))

    def test_command_fence_execution_and_timeout(self):
        queue = (self.nvn / 'nvn_queue.cpp').read_text()
        code = FENCES.replace('@COMPLETION@', region(queue, 'struct FenceCompletion', '// Submits the game made'))
        code = code.replace('@SYNC@', region(queue, 'struct Sync : Object', '// ---- queues'))
        code = code.replace('@SUBMIT@', region(queue, 'void QueueSubmitCommands', 'void QueueFlush'))
        code = code.replace('@ORIGIN@', region(queue, 'std::atomic<uint32_t> g_window_origin', 'void QueueInitialize'))
        self.run_exe(self.compile('fences', code))

    def test_alpha_modes_validate_real_spirv(self):
        for tool in ['spirv-as', 'spirv-val', 'spirv-dis']:
            self.assertIsNotNone(shutil.which(tool), tool + ' required; no downloads')
        assembly = self.out / 'alpha.spvasm'; assembly.write_text(ASSEMBLY)
        binary = self.out / 'alpha.spv'
        subprocess.run(['spirv-as', '--target-env', 'vulkan1.1', str(assembly), '-o', str(binary)], check=True, capture_output=True)
        exe = self.compile('alpha', SPIRV)
        for mode in range(9):
            patched = self.out / f'alpha-{mode}.spv'
            self.run_exe(exe, binary, patched, mode)
            p = subprocess.run(['spirv-val', '--target-env', 'vulkan1.1', str(patched)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            dis = subprocess.check_output(['spirv-dis', str(patched)], text=True)
            if 0 < mode < 8:
                self.assertNotIn('EarlyFragmentTests', dis)
                self.assertIn('OpKill', dis)
                self.assertIn('SpecId 44052', dis)
        print('PASS SPIR-V validator: all 8 NVN alpha functions and default; active tests remove early depth writes')

    def test_changed_translation_units_compile(self):
        changed = [line.split(' b/')[1] for line in self.patch.read_text().splitlines() if line.startswith('diff --git ') and line.endswith('.cpp')]
        for name in changed:
            p = subprocess.run([self.compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', *self.includes,
                                '-fsyntax-only', str(self.source / name)], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, name + '\n' + p.stdout+p.stderr)
        print(f'PASS full production translation units: {len(changed)} strict-profile syntax checks')

    def test_queue_fence_forces_completion_and_checkpoint_applies_writes(self):
        vk = (self.nvn / 'nvn_vk.cpp').read_text()
        checkpoint = region(vk, 'VkCommandBuffer replay_checkpoint(', '// Headless:')
        self.assertLess(checkpoint.index('draw_end_rendering'), checkpoint.index('frame_submit'))
        self.assertLess(checkpoint.index('frame_submit'), checkpoint.index('draw_end_submit'))
        self.assertLess(checkpoint.index('draw_end_submit'), checkpoint.index('if (!begin(true))'))
        submit = region(vk, 'bool gpu_submit(', '// Complete a prefix')
        self.assertIn('wait_done || gpu_profile_on()', submit)
        frames = (self.nvn / 'nvn_frames.cpp').read_text()
        self.assertIn('if (wait_done) {\n            retire_through(s.serial);', frames)
        pipeline = (self.nvn / 'nvn_pipeline.cpp').read_text()
        self.assertIn('c.alpha_ref = k.alpha_ref; c.line_width = k.line_width;', pipeline)
        self.assertIn('st.pSpecializationInfo = &alpha_spec', pipeline)
        print('PASS pipeline completion and recipe integration assertions')


if __name__ == '__main__':
    unittest.main()
