"""Execute production changed-block merge, resident snapshots and flight policy without a game/GPU.

Real Vulkan dispatch/barrier validation and the optional full-scan oracle belong to VM evidence.
"""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import sys
import unittest
from unittest import mock

import test_astral_windows_perf as perf
import test_astral_windows_resident as resident

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'runtime/patches/astral-windows-writeback.patch'


def section(path):
    body = PATCH.read_text().split('+++ b/runtime/src/nvn/' + path + '\n', 1)[1].split('\ndiff --git ', 1)[0]
    return ''.join((line[1:] if line else '') + '\n' for line in body.splitlines()
                   if not line or line.startswith((' ', '+')))


def function(signature):
    with mock.patch.object(perf, 'PATCH', PATCH):
        return perf.function('runtime/src/nvn/nvn_written.cpp', signature)


POLICY = r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <stdexcept>
#include "nvn_writeback.h"
using namespace nx::nvn;
int main() {
    assert(writeback_flags_fit(48,0,64,16,16,false));
    assert(!writeback_flags_fit(48,0,64,17,16,false));
    assert(writeback_flags_fit(96,48,64,16,16,true));
    assert(!writeback_flags_fit(112,48,64,17,16,true));
    assert(!writeback_flags_fit(0,0,64,65,16,true));
    assert(!writeback_flags_fit(UINT64_MAX,0,64,1,256,true));
    assert(!writeback_flags_fit(0,0,0,1,256,true));
    assert(!writeback_flags_fit(0,0,64,1,3,true));
    std::vector<uint64_t> scanned;
    uint32_t flags[]={0,1,0,1};
    changed_blocks(12291,flags,[&](uint64_t at,uint64_t n){scanned.push_back(at);scanned.push_back(n);});
    assert((scanned==std::vector<uint64_t>{4096,4096,12288,3}));
    scanned.clear();
    changed_blocks(4097,flags,[&](uint64_t at,uint64_t n){scanned.push_back(at);scanned.push_back(n);});
    assert((scanned==std::vector<uint64_t>{4096,1}));
    scanned.clear();changed_blocks(9000,nullptr,[&](uint64_t at,uint64_t n){assert(at==0);scanned.push_back(n);});
    assert(scanned[0]==9000);
    // Simulate the production retirement callbacks. Neither fence readiness nor resource reset publishes
    // NVN completion; materialization must happen first, in submitted serial order.
    uint64_t completed=0; std::vector<unsigned> order;
    unsigned live=0,peak=0;
    for (uint64_t serial=1;serial<=17;++serial) {
        ++live; peak=(std::max)(peak,live);
        if (FlightPolicy::throttle(live)) {
            auto next=completed+1;
            FlightPolicy::retire(next,[&]{order.push_back(unsigned(next*2));},[&](uint64_t value){
                assert(value==completed+1 && order.back()==value*2); completed=value; --live;
            });
        }
        assert(live<=FlightPolicy::limit);
    }
    assert(peak==3 && completed==15 && live==2);
    assert(FlightPolicy::early(true,true,false,true,7,7));
    assert(!FlightPolicy::early(false,true,false,true,7,7));
    assert(!FlightPolicy::early(true,false,false,true,7,7));
    assert(!FlightPolicy::early(true,true,true,true,7,7));
    assert(!FlightPolicy::early(true,true,false,false,7,7));
    assert(!FlightPolicy::early(true,true,false,true,7,8));
    assert(!FlightPolicy::later_storage_may_write(0,63));
    assert(FlightPolicy::later_storage_may_write(1ull<<63,0));
    assert(FlightPolicy::later_storage_may_write(~0ull,2));
    assert(FlightPolicy::later_storage_may_write(0,64));
    struct Range {const void* from;const void* to;uint64_t size;const void* before;};
    int x=0,y=0;std::vector<Range> a{{&x,&y,4096,&x}},b=a;
    assert(FlightPolicy::same_ranges(a,b));
    b[0].before=&y;assert(!FlightPolicy::same_ranges(a,b));b=a;
    b[0].from=&y;assert(!FlightPolicy::same_ranges(a,b));b=a;
    b[0].size=4095;assert(!FlightPolicy::same_ranges(a,b));b.clear();assert(!FlightPolicy::same_ranges(a,b));
    assert(!FlightPolicy::eager(false,false));
    assert(FlightPolicy::eager(true,false) && FlightPolicy::eager(false,true));
    try { FlightPolicy::retire(18,[]{throw std::runtime_error("failed materialization");},[&](uint64_t){completed=18;}); }
    catch (const std::runtime_error&) {}
    assert(completed==15);
    std::puts("PASS changed blocks: clipping, unknown write set fallback, partial words; bounded flight retirement order");
}
'''

CACHE = r'''
#include <cassert>
#include <cstdio>
#include "nvn_resident.h"
using namespace nx::nvn; using namespace nx::nvn::replay;
namespace nx::plat {
inline uint64_t tick=0;uint64_t monotonic_ns(){return ++tick;}
alignas(4096) uint8_t guest[8*4096];PageGenerations tracker(reinterpret_cast<uint64_t>(guest),sizeof guest);
bool write_watch_pages(const uint8_t* p,uint64_t n,std::vector<uint64_t>& pages,uint64_t& epoch,uint64_t&) {
 if(!tracker.contains(reinterpret_cast<uint64_t>(p),n))return false;
 pages=tracker.capture(reinterpret_cast<uint64_t>(p),n);epoch=tracker.epoch;return true;
}
}
namespace nx::nvn { inline unsigned drains=0; void frame_wait_all(){++drains;} }
void env(const char* key,const char* value) {
#ifdef _WIN32
 _putenv_s(key,value);
#else
 setenv(key,value,1);
#endif
}
int main() {
 env("NX_RESIDENT","1");env("NX_NARROW_WRITEBACK","1");
#ifdef FLIGHTS
 env("NX_FRAMES_IN_FLIGHT","1");asynchronous=true;
#endif
 g_resident_capacity=128*1024;auto* p=nx::plat::guest;
 for(unsigned i=0;i<sizeof(nx::plat::guest);++i)p[i]=uint8_t(i);
 Upload current,snapshot;std::shared_ptr<std::vector<uint8_t>> before;
 resident_begin();assert(resident_upload(p,8193,12288,256,true,current,&before,&snapshot));
 assert(current.ptr!=snapshot.ptr && !std::memcmp(snapshot.ptr,p,8193));
 const auto old=current.ptr; const auto prior=resident_stats().gpu_snapshot;
 current.ptr[4097]=88;p[4097]=88;nx::plat::tracker.invalidate(reinterpret_cast<uint64_t>(p+4097),1);
 resident_begin();assert(resident_upload(p,8193,12288,256,true,current,&before,&snapshot));
 assert(current.ptr==old && snapshot.ptr[4097]==88 && (*before)[4097]==88);
 assert(resident_stats().gpu_snapshot-prior==4096);
 // A second same-submit binding gets a new allocation: immutable snapshots already referenced by
 // recorded comparison dispatches cannot be refreshed or recycled underneath the GPU.
 const auto prior_snapshot=snapshot.ptr;
 assert(resident_upload(p,8193,12288,256,true,current,&before,&snapshot));
 assert(snapshot.ptr!=prior_snapshot);
 assert(!resident_upload(p,8193,g_resident_capacity,256,true,current,&before,&snapshot));
 assert(g_resident_full);resident_begin();assert(g_resident.empty() && g_resident_head==0);
#ifdef FLIGHTS
 assert(drains==3); // each arena mutation boundary follows completion, even when no writebacks exist
#else
 assert(drains==0);
#endif
 std::puts("PASS resident snapshots: independent allocation, page refresh, copy-on-write, bounded recycle, flight drain");
}
'''


class WindowsWritebackTest(unittest.TestCase):
    def test_embedded_shader_matches_reviewable_source(self):
        compiler = os.environ.get('GLSLANG_VALIDATOR') or shutil.which('glslangValidator')
        if not compiler:
            self.skipTest('optional GLSLANG_VALIDATOR required for embedded shader reproducibility')
        header = section('nvn_writeback.h')
        glsl = header.split('R"GLSL(', 1)[1].split(')GLSL"', 1)[0]
        binary = header.split('kWritebackCompareSPV[] = {', 1)[1].split('};', 1)[0]
        expected = [int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]+)u', binary)]
        with tempfile.TemporaryDirectory() as td:
            source, output = Path(td)/'compare.comp', Path(td)/'compare.spv'
            source.write_text(glsl)
            built = subprocess.run([compiler, '-V', '-Os', str(source), '-o', str(output)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
            actual = output.read_bytes()
            self.assertEqual(list(struct.unpack('<%dI' % (len(actual)//4), actual)), expected)

    def test_switches_default_off_and_require_residency(self):
        for values, narrow, flights in [({}, False, False),
                ({'NX_NARROW_WRITEBACK': '0', 'NX_FRAMES_IN_FLIGHT': '0', 'NX_RESIDENT': '1'}, False, False),
                ({'NX_NARROW_WRITEBACK': '1', 'NX_FRAMES_IN_FLIGHT': '1'}, True, False),
                ({'NX_NARROW_WRITEBACK': '1', 'NX_FRAMES_IN_FLIGHT': '1', 'NX_RESIDENT': '1'}, True, True)]:
            env = {k: v for k, v in os.environ.items() if k not in
                   ('NX_NARROW_WRITEBACK', 'NX_FRAMES_IN_FLIGHT', 'NX_RESIDENT')}
            env.update(values)
            code = ('#include <cassert>\n#include <cstdio>\n#include "nvn_writeback.h"\nint main(){'
                    'assert(nx::nvn::narrow_writeback_on()==%s);'
                    'assert(nx::nvn::resident_flights_on()==%s);puts("PASS default-off switches");}' %
                    (str(narrow).lower(), str(flights).lower()))
            with self.subTest(values=values), mock.patch.dict(os.environ, env, clear=True):
                resident.WindowsResidentTest().compile_run(code, {'nvn_writeback.h': section('nvn_writeback.h')})

    def test_fence_capture_serializes_with_active_replay(self):
        with mock.patch.object(perf, 'PATCH', PATCH):
            body = perf.function('runtime/src/nvn/nvn_frames.cpp', 'uint64_t gpu_serial()')
        code = r"""
#include <atomic>
#include <cassert>
#include <cstdio>
#include <future>
#include <mutex>
#include <thread>
#include "nvn_writeback.h"
using namespace nx::nvn;
std::recursive_mutex lock;
std::atomic<uint64_t> g_submitted{0};
std::recursive_mutex& gpu_lock(){return lock;}
bool async_gpu(){return true;}bool pipelined(){return false;}
@BODY@
int main(){
#ifdef _WIN32
 _putenv_s("NX_RESIDENT","1");_putenv_s("NX_FRAMES_IN_FLIGHT","1");
#else
 setenv("NX_RESIDENT","1",1);setenv("NX_FRAMES_IN_FLIGHT","1",1);
#endif
 std::promise<void> queued,release;auto wait=release.get_future();
 std::thread replay([&]{std::lock_guard guard(lock);queued.set_value();wait.wait();g_submitted=7;});
 queued.get_future().wait();
 auto fence=std::async(std::launch::async,[]{return gpu_serial();});
 assert(fence.wait_for(std::chrono::milliseconds(10))==std::future_status::timeout);
 release.set_value();assert(fence.get()==7);replay.join();assert(gpu_serial()==7);
 puts("PASS NVN fence capture waits for replay/writeback publication, then captures current serial");
}
""".replace('@BODY@', body)
        resident.WindowsResidentTest().compile_run(code, {'nvn_writeback.h': section('nvn_writeback.h')})

    def test_changed_blocks_and_completion_bookkeeping(self):
        resident.WindowsResidentTest().compile_run(POLICY, {'nvn_writeback.h': section('nvn_writeback.h')})

    def cache(self, flights):
        stub = resident.VULKAN_STUB.replace('inline bool asynchronous=false;',
                    'void frame_wait_all();\ninline bool asynchronous=false;')
        resident.WindowsResidentTest().compile_run(('#define FLIGHTS 1\n' if flights else '') + CACHE,
            {'nvn_resident.h': section('nvn_resident.h'), 'nvn_writeback.h': section('nvn_writeback.h'),
             'win_page_generations.h': resident.added('win_page_generations.h'),
             'win_write_watch.h': resident.added('win_write_watch.h'), 'nvn_vk.h': stub,
             'platform.h': '#pragma once\nnamespace nx::plat { uint64_t monotonic_ns(); }\n'})

    def test_persistent_gpu_snapshot(self):
        self.cache(False)

    def test_resident_arena_waits_before_refresh_with_flights(self):
        self.cache(True)

    def merge(self, simd):
        # Same guard-page/scalar/AVX2 oracle as residency, with changed-block flags supplied to every
        # ordinary randomized merge. Extra large boundary cases run inside each of its 5,248 cases.
        harness = ('#define NOMINMAX 1\n' + perf.HARNESS).replace('    std::shared_ptr<std::vector<uint8_t>> before;',
            '    std::shared_ptr<std::vector<uint8_t>> before;\n    uint64_t before_offset=0; const uint32_t* changed=nullptr;')
        support = ('#include "nvn_writeback.h"\nusing namespace nx::nvn;\n'
            'void log(const char*,...) {}\nnamespace replay { struct Metrics { uint64_t wb_scanned=0,wb_changed=0,wb_considered=0; }; '
            'Metrics& resident_stats(){ static Metrics m; return m; } }\n' +
            function('void apply_write_back_full(') + '\n@FUNCTION@')
        # Header is inlined so the existing compile helper can run on both operating systems.
        support = support.replace('#include "nvn_writeback.h"', section('nvn_writeback.h'))
        harness = harness.replace('@FUNCTION@', support)
        harness = harness.replace('        apply_write_back(w);', r'''
        std::vector<uint32_t> flags((n+4095)/4096,0);
        for (size_t at=0;at<n;at+=4096)
            flags[at/4096]=std::memcmp(w.from+at,w.before->data()+at,std::min(size_t(4096),n-at))!=0;
        w.changed=flags.data();apply_write_back(w);
        ''', 1)
        # Exercise larger, sparse blocks and partial words with a bit-exact, independent full-range oracle.
        harness = harness.replace('    unsigned cases = 0;', r'''
    for (size_t n : {4095,4096,4097,8191,8192,8193,16387,65535}) for (unsigned trial=0;trial<64;++trial) {
        std::vector<uint8_t> src(n,0),dst(n,0x6b),expected=dst;
        auto before=std::make_shared<std::vector<uint8_t>>(n,0);
        for(unsigned k=0;k<13;++k) src[random()%n]=uint8_t(1+random()%255);
        for(size_t at=0;at<(n/8)*8;at+=4)
            if(whole || std::memcmp(src.data()+at,before->data()+at,4))std::copy_n(src.data()+at,4,expected.data()+at);
        for(size_t at=(n/8)*8;at<n;++at)if(whole || src[at])expected[at]=src[at];
        std::vector<uint32_t> flags((n+4095)/4096,0);
        for(size_t at=0;at<n;at+=4096) flags[at/4096]=std::memcmp(src.data()+at,before->data()+at,std::min(size_t(4096),n-at))!=0;
        WriteBack w{src.data(),dst.data(),n,before};w.changed=flags.data();apply_write_back(w);assert(dst==expected);
        // A conservative extra flag is harmless: the CPU still stores only changed words.
        std::fill(flags.begin(),flags.end(),1);dst.assign(n,0x6b);apply_write_back(w);assert(dst==expected);
    }
    unsigned cases = 0;''')
        with mock.patch.object(perf, 'PATCH', PATCH), mock.patch.object(perf, 'HARNESS', harness):
            perf.WindowsPerfTest().compile_writeback(simd)

    def test_bit_exact_changed_block_scalar_merge(self):
        self.merge(False)

    def test_bit_exact_changed_block_avx2_merge(self):
        self.merge(True)

    def test_integration_fallbacks_switches_and_scope(self):
        sys.path.insert(0, str(ROOT/'tools'))
        from acr_build import read_series
        series = read_series(ROOT/'runtime/patches/series.windows')
        self.assertEqual(series[series.index(PATCH.name)-1:series.index(PATCH.name)+2],
                         ['astral-windows-resident.patch', PATCH.name, 'astral-windows-replay.patch'])
        for n in ['series.linux', 'series.macos']:
            self.assertNotIn(PATCH.name, read_series(ROOT/'runtime/patches'/n))
        text = PATCH.read_text()
        self.assertNotRegex(text, r'/(?:Users|home|work)/|[A-Z]:[\\/]')
        frames = section('nvn_frames.cpp')
        self.assertLess(frames.index('prepare_write_backs(s.cbs[s.part],write_backs)'),
                        frames.index('g_current = nullptr;', frames.index('void frame_submit(')))
        self.assertIn('FlightPolicy::eager(!s.write_backs.empty(),wait_done)', frames)
        self.assertIn('FlightPolicy::retire(s->serial', frames)
        self.assertIn('FlightPolicy::early(', frames)
        self.assertIn('std::lock_guard lk(gpu_lock()); return g_submitted.load();', frames)
        self.assertIn('s->early_write_backs=replay::written_peek()', frames)
        self.assertIn('!replay::g_resident_graphics_writer', frames)
        self.assertIn('FlightPolicy::later_storage_may_write', section('nvn_sets.cpp'))
        resident_body = section('nvn_resident.h')
        self.assertLess(resident_body.index('frame_wait_all();'), resident_body.index('++g_resident_submit;'))
        self.assertIn('!w.snapshot.buffer || !w.result.buffer', section('nvn_written.cpp'))
        self.assertIn('VK_PIPELINE_STAGE_HOST_BIT', section('nvn_written.cpp'))
        self.assertIn('NX_NARROW_WRITEBACK_ORACLE', text)
        self.assertIn('validation active: VK_LAYER_KHRONOS_validation with persistent debug messenger', section('nvn_vk.cpp'))
        self.assertIn('ici.pNext=&debug;', section('nvn_vk.cpp'))
        # SPIR-V is original, embedded with its complete source and no game-specific identifiers.
        self.assertIn('0x07230203u', text)
        self.assertIn('layout(local_size_x=64)', text)


if __name__ == '__main__':
    unittest.main()
