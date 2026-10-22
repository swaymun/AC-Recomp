"""Game-free production tracker/resident regression tests; native Win32 watch tests on Windows.

No cloud, credentials, game or GPU. The Vulkan fixture supplies mapped coherent memory and
executes the actual cache functions; it does not establish real-driver/gameplay correctness.
"""
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

import test_astral_windows_perf as perf

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'runtime/patches/astral-windows-resident.patch'


def section(path):
    body = PATCH.read_text().split('+++ b/' + path + '\n', 1)[1].split('\ndiff --git ', 1)[0]
    return ''.join((line[1:] if line else '') + '\n' for line in body.splitlines()
                   if not line or line.startswith((' ', '+')))


def added(path):
    return section('runtime/src/' + path)


TRACKER_TEST = r'''
#include <cassert>
#include <cstdio>
#include <limits>
#include "win_page_generations.h"
using namespace nx::plat;
int main() {
    PageGenerations owner(0x10000, 8*4096);
    assert(!owner.contains(0xffff,1)); assert(!owner.contains(0x10000,0));
    assert(!owner.contains(0x17fff,2)); assert(!owner.contains(UINT64_MAX,8));
    assert(owner.contains(0x17fff,1));
    PageConsumer a,b;
    uint64_t copied=0;
    auto refresh=[&](PageConsumer& c,uint64_t p,uint64_t n) {
        auto snap=owner.capture(p,n); auto epoch=owner.epoch;
        return c.refresh(p,n,epoch,snap,[&](uint64_t off,uint64_t bytes) {
            assert(off+bytes<=n);copied+=bytes;
        });
    };
    assert(refresh(a,0x10003,9000)==9000); assert(refresh(b,0x10003,9000)==9000);
    assert(refresh(a,0x10003,9000)==0); assert(refresh(b,0x10003,9000)==0);
    assert(owner.invalidate(0x11000,4096));
    assert(refresh(a,0x10003,9000)==4096); // a cannot consume b's dirty state
    assert(refresh(b,0x10003,9000)==4096);
    assert(owner.invalidate(0x10003,1));
    auto snap=owner.capture(0x10003,9000);auto epoch=owner.epoch;
    a.refresh(0x10003,9000,epoch,snap,[&](uint64_t,uint64_t) {
        // A write after harvest / during copy must remain visible on the next query.
        assert(owner.invalidate(0x12000,4096));
    });
    assert(refresh(a,0x10003,9000)==811); assert(refresh(b,0x10003,9000)==4904);
    // decommit/recommit and pool reuse use invalidate even if OS clears dirty bits.
    assert(owner.invalidate(0x10000,3*4096)); assert(refresh(a,0x10003,9000)==9000);
    owner.clock=UINT64_MAX; const auto old_epoch=owner.epoch;
    assert(owner.invalidate(0x11000,4096)); assert(owner.epoch==old_epoch+1);
    assert(refresh(a,0x10003,9000)==9000); assert(refresh(b,0x10003,9000)==9000);
    owner.clock=owner.epoch=UINT64_MAX; assert(!owner.invalidate(0x10000,1));
    std::puts("PASS tracker: independent consumers, clipped pages, racing write, reuse, rollover, bounds");
}
'''

VULKAN_STUB = r'''
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
using VkBuffer=uint64_t; using VkDeviceMemory=uint64_t; using VkDevice=uint64_t;
constexpr uint64_t VK_NULL_HANDLE=0, VK_WHOLE_SIZE=~0ull;
constexpr int VK_SUCCESS=0,VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO=1,VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO=2;
struct VkBufferCreateInfo { int type; uint64_t size=0,usage=0; };
struct VkMemoryRequirements { uint64_t size=0;uint32_t memoryTypeBits=1; };
struct VkMemoryAllocateInfo { int type;uint64_t allocationSize=0;uint32_t memoryTypeIndex=0; };
inline std::vector<uint8_t> mapped; inline uint64_t created_size=0; inline bool fail_alloc=false;
namespace nx::vk {
inline int p_vkCreateBuffer(VkDevice,const VkBufferCreateInfo* b,void*,VkBuffer* out) {*out=1;created_size=b->size;return 0;}
inline void p_vkGetBufferMemoryRequirements(VkDevice,VkBuffer,VkMemoryRequirements* out) {out->size=created_size;}
inline int p_vkAllocateMemory(VkDevice,const VkMemoryAllocateInfo* a,void*,VkDeviceMemory* out) {
 if(fail_alloc)return -1;mapped.resize(a->allocationSize);*out=1;return 0;
}
inline int p_vkBindBufferMemory(VkDevice,VkBuffer,VkDeviceMemory,uint64_t) {return 0;}
inline int p_vkMapMemory(VkDevice,VkDeviceMemory,uint64_t,uint64_t,int,void** out) {*out=mapped.data();return 0;}
inline void p_vkDestroyBuffer(VkDevice,VkBuffer,void*) {}
inline void p_vkFreeMemory(VkDevice,VkDeviceMemory,void*) {}
}
namespace nx::nvn {
struct Upload { VkBuffer buffer=0;uint64_t offset=0;uint8_t* ptr=nullptr; };
constexpr uint64_t kUploadUsage=127;
inline bool asynchronous=false;
inline bool async_gpu(){return asynchronous;}
inline VkDevice vk_device(){return 1;}
inline uint32_t upload_memory_type(uint32_t){return 0;}
inline void log(const char*,...) {}
}
'''
CACHE_TEST = r'''
#include <cassert>
#include <cstdio>
#include "nvn_resident.h"
using namespace nx::nvn; using namespace nx::nvn::replay;
namespace nx::plat {
inline uint64_t tick=0; uint64_t monotonic_ns(){return ++tick;}
alignas(4096) uint8_t guest[8*4096]; PageGenerations tracker(reinterpret_cast<uint64_t>(guest),sizeof guest);
bool write_watch_pages(const uint8_t* p,uint64_t n,std::vector<uint64_t>& pages,uint64_t& epoch,uint64_t&) {
 if(!tracker.contains(reinterpret_cast<uint64_t>(p),n))return false;
 pages=tracker.capture(reinterpret_cast<uint64_t>(p),n);epoch=tracker.epoch;return true;
}
}
void env(const char* key,const char* v) {
#ifdef _WIN32
 _putenv_s(key,v?v:"");
#else
 if(v)setenv(key,v,1);else unsetenv(key);
#endif
}
int main() {
 env("NX_RESIDENT","1");g_resident_capacity=65536;
#ifdef THRESHOLD_TEST
 { auto* p=nx::plat::guest; Upload small;
 env("NX_RESIDENT_MIN_READ",nullptr);resident_begin();
 assert(!resident_upload(p,4095,4096,16,false,small));
 assert(resident_stats().query_ns==0 && g_resident_head==0);
 assert(resident_upload(p,4096,4096,16,false,small));
 std::shared_ptr<std::vector<uint8_t>> original;
 assert(resident_upload(p,8,16,4,true,small,&original));assert(original->size()==8);
 std::puts("PASS threshold: small reads bypass without querying, boundary and small storage cache");return 0; }
#endif
 env("NX_RESIDENT_MIN_READ","0");
 auto* p=nx::plat::guest; for(unsigned i=0;i<sizeof(nx::plat::guest);++i)p[i]=uint8_t(i);
 Upload a,b;std::shared_ptr<std::vector<uint8_t>> before;
 resident_begin();assert(resident_upload(p+3,9000,9216,16,false,a));
 assert(!std::memcmp(a.ptr,p+3,9000));for(int i=9000;i<9216;++i)assert(a.ptr[i]==0);
 const auto copied=resident_stats().copied;resident_begin();
 assert(resident_upload(p+3,9000,9216,16,false,b));assert(a.ptr==b.ptr);assert(copied==resident_stats().copied);
 p[4097]=77;nx::plat::tracker.invalidate(reinterpret_cast<uint64_t>(p+4097),1);
 // An already-referenced allocation must not be overwritten in the same command buffer.
 assert(resident_upload(p+3,9000,9216,16,false,b));assert(a.ptr!=b.ptr);assert(a.ptr[4094]!=77);assert(b.ptr[4094]==77);
 assert(resident_upload(p+3,9000,9216,16,true,a,&before));assert(before&&before->size()==9000);
 assert(!std::memcmp(before->data(),p+3,9000));
 // Simulated completed GPU changed-word merge marks only its CPU destination dirty.
 a.ptr[9001]=0x44; a.ptr[40]=88;p[43]=88;nx::plat::tracker.invalidate(reinterpret_cast<uint64_t>(p+43),1);
 p[5000]=99;nx::plat::tracker.invalidate(reinterpret_cast<uint64_t>(p+5000),1);
 resident_begin();auto* old=a.ptr;const auto prior_copy=resident_stats().copied;const auto prior_snapshot=resident_stats().snapshot;
 assert(resident_upload(p+3,9000,9216,16,true,a,&before));assert(old==a.ptr);
 assert(a.ptr[9001]==0);assert(resident_stats().copied-prior_copy==8189);assert(resident_stats().snapshot-prior_snapshot==8189);
 assert(a.ptr[40]==88&&a.ptr[4997]==99);assert((*before)[40]==88&&(*before)[4997]==99);
 // Unknown ranges, async operation and explicit switches always use the uncached fallback.
 uint8_t unknown[8];assert(!resident_upload(unknown,8,8,4,false,b));
 asynchronous=true;assert(!resident_upload(p,8,8,4,false,b));asynchronous=false;
 env("NX_RESIDENT_STORAGE","0");assert(!resident_upload(p,8,8,4,true,b));env("NX_RESIDENT_STORAGE",nullptr);
 env("NX_RESIDENT_READ","0");assert(!resident_upload(p,8,8,4,false,b));env("NX_RESIDENT_READ",nullptr);
 env("NX_RESIDENT","0");assert(!resident_upload(p,8,8,4,false,b));env("NX_RESIDENT","1");
 assert(!resident_upload(p,8,7,4,false,b));assert(!resident_upload(p,8,8,512,false,b));
 // Exhaustion falls back without recycling allocations still referenced by this submit.
 assert(!resident_upload(p,8,65536,4,false,b));assert(g_resident_full);
 resident_begin();assert(g_resident.empty()&&g_resident_head==0);
 assert(resident_upload(p,8,16,4,false,b));
 // A graphics SSBO may have changed a read allocation without CPU writes. Future reads
 // must fall back, while already-recorded memory and compute changed-word snapshots survive.
 auto* recorded=b.ptr; const auto arena_head=g_resident_head;
 resident_note_graphics_writes(); resident_begin();
 assert(g_resident_graphics_writer && g_resident_head==arena_head && recorded==b.ptr);
 assert(!resident_upload(p,8,16,4,false,b));
 assert(resident_upload(p,8,16,4,true,a,&before));
 std::puts("PASS resident: reuse, dirty refresh, snapshot, same-submit copy-on-write, fallback, bounded reset, graphics writer");
}
'''

NATIVE_TEST = r'''
#include <windows.h>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <cstdint>
#include <vector>
#include "win_page_generations.h"
constexpr uint64_t kHeapBase=0x4800000000ull,kHeapMax=8*4096;
void log(const char*,...) {}
namespace nx::plat {
@PLATFORM@
}
int main() {
 _putenv_s("NX_RESIDENT","1");_putenv_s("NX_WRITE_WATCH","1");
 using namespace nx::plat;
 assert(reserve(kHeapBase,kHeapMax));assert(commit(kHeapBase,kHeapMax));
 auto* p=reinterpret_cast<volatile uint8_t*>(kHeapBase);
 std::vector<uint64_t> first,second,third;uint64_t epoch=0,dirty=0;
 p[4100]=1;assert(write_watch_pages(const_cast<const uint8_t*>(p),kHeapMax,first,epoch,dirty));assert(dirty>=1);
 assert(write_watch_pages(const_cast<const uint8_t*>(p),kHeapMax,second,epoch,dirty));assert(first==second);
 p[8200]=2;assert(write_watch_pages(const_cast<const uint8_t*>(p),kHeapMax,third,epoch,dirty));
 assert(third[2]!=first[2]);assert(third[1]==first[1]);
 uint64_t old_dirty=dirty;for(unsigned i=0;i<8;++i)p[i*4096]=uint8_t(i+3);
 assert(write_watch_pages(const_cast<const uint8_t*>(p),kHeapMax,second,epoch,dirty));assert(dirty-old_dirty==8);
 third=second;
 decommit(kHeapBase+4096,4096);assert(commit(kHeapBase+4096,4096));
 assert(write_watch_pages(const_cast<const uint8_t*>(p),kHeapMax,second,epoch,dirty));assert(second[1]!=third[1]);
 assert(!write_watch_pages(reinterpret_cast<const uint8_t*>(kHeapBase-1),1,first,epoch,dirty));
 assert(VirtualFree(reinterpret_cast<void*>(kHeapBase),0,MEM_RELEASE));
 std::puts("PASS Win32: MEM_WRITE_WATCH, reset owner, page identities, decommit/recommit, unknown fallback");
}
'''


class WindowsResidentTest(unittest.TestCase):
    def compile_run(self, code, headers=None, avx=False):
        cxx = shutil.which('clang-cl' if os.name == 'nt' else 'clang++')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, content in (headers or {}).items():
                (d / name).write_text(content)
            (d / 'test.cpp').write_text(code)
            exe = d / ('test.exe' if os.name == 'nt' else 'test')
            if os.name == 'nt':
                cmd = [cxx, '/nologo', '/std:c++20', '/EHsc', '/O2', '/UNDEBUG', '/DNX_ASTRAL_STRICT=1',
                       str(d / 'test.cpp'), '/Fe' + str(exe), '/Fo' + str(d / 'test.obj')]
                if avx:
                    cmd += ['/arch:AVX2']
            else:
                cmd = [cxx, '-std=c++20', '-O2', '-UNDEBUG', str(d / 'test.cpp'), '-o', str(exe)]
            p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('PASS', p.stdout)

    def test_independent_generations_races_reuse_rollover(self):
        self.compile_run(TRACKER_TEST, {'win_page_generations.h': added('win_page_generations.h')})

    def test_production_resident_cache_lifetime_and_refresh(self):
        self.compile_run(CACHE_TEST, {'win_page_generations.h': added('win_page_generations.h'),
                                    'win_write_watch.h': added('win_write_watch.h'),
                                    'nvn_resident.h': added('nvn/nvn_resident.h'),
                                    'nvn_vk.h': VULKAN_STUB,
                                    'platform.h': '#pragma once\nnamespace nx::plat { uint64_t monotonic_ns(); }\n'})

    def test_minimum_read_range_uses_uncached_fallback(self):
        self.compile_run('#define THRESHOLD_TEST 1\n' + CACHE_TEST,
                         {'win_page_generations.h': added('win_page_generations.h'),
                          'win_write_watch.h': added('win_write_watch.h'),
                          'nvn_resident.h': added('nvn/nvn_resident.h'), 'nvn_vk.h': VULKAN_STUB,
                          'platform.h': '#pragma once\nnamespace nx::plat { uint64_t monotonic_ns(); }\n'})

    def test_combined_changed_word_contract(self):
        # Execute the instrumented production scalar and AVX2 merge against the same 5,248-case
        # randomized/guard-page oracle as WIN-PERF-020, including CPU changes in untouched words.
        original = perf.HARNESS
        metrics = ('namespace replay { struct Metrics { uint64_t wb_scanned=0, wb_changed=0; }; '
                   'Metrics& resident_stats() { static Metrics m; return m; } }\n@FUNCTION@')
        with mock.patch.object(perf, 'PATCH', PATCH), mock.patch.object(perf, 'HARNESS', original.replace('@FUNCTION@', metrics)):
            helper = perf.WindowsPerfTest()
            helper.compile_writeback(False)
            helper.compile_writeback(True)

    @unittest.skipUnless(os.name == 'nt', 'native GetWriteWatch test requires Windows')
    def test_native_write_watch_and_recommit(self):
        body = section('runtime/src/platform_win.cpp')
        body = body[body.index('namespace {'):body.index('// ---- threads')]
        self.compile_run(NATIVE_TEST.replace('@PLATFORM@', body),
                         {'win_page_generations.h': added('win_page_generations.h')})

    def test_series_and_public_scope(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        from acr_build import read_series
        series = read_series(ROOT / 'runtime/patches/series.windows')
        resident_index = series.index(PATCH.name)
        self.assertEqual(series[resident_index - 1:resident_index + 2],
                         ['astral-windows-perf.patch', PATCH.name,
                          'astral-windows-writeback.patch'])
        for name in ['series.linux', 'series.macos']:
            self.assertNotIn(PATCH.name, read_series(ROOT / 'runtime/patches' / name))
        text = PATCH.read_text()
        self.assertNotRegex(text, r'/(?:Users|home|work)/|[A-Z]:[\\/]')
        self.assertIn('WRITE_WATCH_FLAG_RESET', text)
        self.assertIn('write_watch_invalidate(p->memory,p->size)', text)
        self.assertIn('s->stage != ShaderStage::Compute && written_storage_bindings(s)', text)


if __name__ == '__main__':
    unittest.main()
