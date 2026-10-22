"""Staging protocol and ownership regressions compiled from the shipped overlay; no game or GPU required."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime
from test_astral_touch import added_file

PATCH = ROOT / 'runtime/patches/astral-windows-mem.patch'
HEADER = 'runtime/src/nvn/nvn_retire.h'
FRAMES = 'runtime/src/nvn/nvn_frames.cpp'

FIXTURE = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <mutex>
#include <utility>
#include "nvn_retire.h"
long fail_after = -1;
void* operator new(size_t size) {
    if (fail_after == 0) throw std::bad_alloc();
    if (fail_after > 0) --fail_after;
    if (void* p = std::malloc(size ? size : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
int freed = 0, orphaned = 0;
struct GpuImage {
    int image = 1;
    ~GpuImage() { if (image) ++orphaned; }
};
void destroy(GpuImage& image) { assert(image.image); ++freed; image.image = 0; }
using P = std::shared_ptr<GpuImage>;
using V = std::vector<P>;
std::mutex g_grave_lock;
uint64_t g_submitted = 7;
std::vector<std::pair<uint64_t, P>> g_grave;
@ENQUEUE@
void release(V& v) { nx::nvn::detail::release_retired_images(v, destroy); }
int main() {
    // Reproduce the previous loop: references in this same dead batch fooled use_count.
    { P p = std::make_shared<GpuImage>(); V dead{p, p}; p.reset();
      for (auto& image : dead) { if (image.use_count() > 1) continue; destroy(*image); }
    }
    assert(freed == 0 && orphaned == 1);
    orphaned = 0;
    // The exact shipped helper releases three aliases once, including a null entry.
    { P p = std::make_shared<GpuImage>(); V dead{p, {}, p, p}; p.reset(); release(dead);
      for (auto& x : dead) assert(!x);
    }
    assert(freed == 1 && orphaned == 0);
    // A genuinely live owner must retain its GPU handles across retirement batches.
    { P live = std::make_shared<GpuImage>(); V dead{live, live}; release(dead);
      assert(freed == 1 && live->image);
      dead.push_back(std::move(live)); release(dead);
    }
    assert(freed == 2 && orphaned == 0);
    // An unretired reference in another batch prevents premature destruction.
    { P p = std::make_shared<GpuImage>(); V first{p, p}, later{p}; p.reset();
      release(first); assert(freed == 2); release(later);
    }
    assert(freed == 3 && orphaned == 0);
    // Snapshot expiry queues its final reference through the current submit's successor.
    { P snapshot = std::make_shared<GpuImage>(); retire_image(std::move(snapshot));
      assert(!snapshot && g_grave.size() == 1 && g_grave[0].first == 8);
      assert(freed == 3 && g_grave[0].second->image);
      retire_image({}); assert(g_grave.size() == 1);
      V completed; completed.push_back(std::move(g_grave[0].second));
      g_grave.clear(); release(completed);
    }
    assert(freed == 4 && orphaned == 0);
    // Repeated aliases and interleaved images do not accumulate live GPU resources.
    for (int n = 0; n < 10000; ++n) {
      P a = std::make_shared<GpuImage>(), b = std::make_shared<GpuImage>();
      V dead{a, b, a, b}; a.reset(); b.reset(); release(dead);
    }
    assert(freed == 20004 && orphaned == 0);
    // Streaming upload eligibility excludes every image with possible recorded GPU history.
    using nx::nvn::detail::fresh_upload_candidate;
    assert(fresh_upload_candidate(false, false, false, false, true, 1ull<<20));
    assert(!fresh_upload_candidate(true, false, false, false, true, 2ull<<20));
    assert(!fresh_upload_candidate(false, true, false, false, true, 2ull<<20));
    assert(!fresh_upload_candidate(false, false, true, false, true, 2ull<<20));
    assert(!fresh_upload_candidate(false, false, false, true, true, 2ull<<20));
    assert(!fresh_upload_candidate(false, false, false, false, false, 2ull<<20));
    assert(!fresh_upload_candidate(false, false, false, false, true, (1ull<<20)-1));
    // Snapshot counters follow actual shared ownership, including in-flight aliases.
    uint8_t input[8] = {1,2,3,4,5,6,7,8};
    nx::nvn::detail::SnapshotStats stats;
    { auto a = nx::nvn::detail::snapshot_copy(input, 8, &stats); auto b = a;
      assert(*a == std::vector<uint8_t>(input, input+8));
      assert(stats.live == 8 && stats.peak == 8 && stats.allocations == 1);
      a.reset(); assert(stats.live == 8 && stats.frees == 0);
      b.reset(); assert(stats.live == 0 && stats.frees == 1 && stats.total == 8);
    }
    { auto a = nx::nvn::detail::snapshot_copy(input, 8, nullptr); assert(a->size() == 8); }
    // Allocation failure before the vector, its bytes, or the shared control block must not
    // leave phantom live bytes or underflow the accounting used to diagnose bad_alloc.
    for (int failure = 0; failure < 3; ++failure) {
      nx::nvn::detail::SnapshotStats fault;
      fail_after = failure; bool threw = false;
      try { auto a = nx::nvn::detail::snapshot_copy(input, 8, &fault); }
      catch (const std::bad_alloc&) { threw = true; }
      fail_after = -1; assert(threw && fault.live == 0 && fault.allocations == fault.frees);
    }
    std::puts("PASS: baseline leak reproduced; 20004 images freed exactly once; live owners and retirement serial preserved");
}
'''


UPLOAD_FIXTURE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>
using VkCommandPool=uint64_t; using VkCommandBuffer=uint64_t; using VkFence=uint64_t;
using VkDevice=uint64_t; using VkBuffer=uint64_t; using VkDeviceMemory=uint64_t;
using VkImageLayout=int; using VkResult=int;
constexpr int VK_NULL_HANDLE=0, VK_SUCCESS=0, VK_ERROR_DEVICE_LOST=-4;
constexpr int VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO=1, VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT=1,
 VK_COMMAND_POOL_CREATE_TRANSIENT_BIT=2, VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO=2,
 VK_COMMAND_BUFFER_LEVEL_PRIMARY=1, VK_STRUCTURE_TYPE_FENCE_CREATE_INFO=3,
 VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO=4, VK_BUFFER_USAGE_TRANSFER_SRC_BIT=1,
 VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO=5, VK_WHOLE_SIZE=-1,
 VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO=6, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT=1,
 VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL=9, VK_STRUCTURE_TYPE_MEMORY_BARRIER=7,
 VK_ACCESS_TRANSFER_WRITE_BIT=1, VK_ACCESS_MEMORY_READ_BIT=2, VK_ACCESS_MEMORY_WRITE_BIT=4,
 VK_PIPELINE_STAGE_TRANSFER_BIT=1, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT=2,
 VK_STRUCTURE_TYPE_SUBMIT_INFO=8, VK_TRUE=1;
struct VkCommandPoolCreateInfo { int type; int flags{}; uint32_t queueFamilyIndex{}; };
struct VkCommandBufferAllocateInfo { int type; uint64_t commandPool{}; int level{}; uint32_t commandBufferCount{}; };
struct VkFenceCreateInfo { int type; };
struct VkBufferCreateInfo { int type; uint64_t size{}; int usage{}; };
struct VkMemoryRequirements { uint64_t size{}; uint32_t memoryTypeBits{}; };
struct VkMemoryAllocateInfo { int type; uint64_t allocationSize{}; uint32_t memoryTypeIndex{}; };
struct VkCommandBufferBeginInfo { int type; int flags{}; };
struct VkMemoryBarrier { int type; int srcAccessMask{}, dstAccessMask{}; };
struct VkSubmitInfo { int type; uint32_t commandBufferCount{}; const uint64_t* pCommandBuffers{}; };
struct VkBufferImageCopy {};
struct GpuImage { uint64_t image=71; int layout=0; };
std::vector<std::string> events;
std::vector<uint8_t> mapped_bytes;
bool submitted=false, waited=false, fail_allocation=false, fail_end=false, timeout=false, fail_submit=false;
uint64_t staging_live=0, staging_peak=0;
void reset() { events.clear(); submitted=waited=fail_allocation=fail_end=timeout=fail_submit=false; }
uint64_t vk_device(){return 1;} uint64_t vk_queue(){return 2;} uint32_t vk_queue_family(){return 3;}
uint32_t upload_memory_type(uint32_t bits){assert(bits==1);return 0;}
void log(const char*,...){}
[[noreturn]] void gpu_hung(const char*){throw std::runtime_error("gpu_hung");}
int p_vkCreateCommandPool(uint64_t,const VkCommandPoolCreateInfo* i,const void*,uint64_t* p){assert(i->queueFamilyIndex==3);*p=11;return 0;}
int p_vkAllocateCommandBuffers(uint64_t,const VkCommandBufferAllocateInfo* i,uint64_t* p){assert(i->commandPool==11);*p=17;return 0;}
int p_vkCreateFence(uint64_t,const VkFenceCreateInfo*,const void*,uint64_t* p){*p=21;return 0;}
void p_vkDestroyCommandPool(uint64_t,uint64_t,const void*){}
int p_vkCreateBuffer(uint64_t,const VkBufferCreateInfo* i,const void*,uint64_t* p){assert(i->size==8);*p=31;events.push_back("create");return 0;}
void p_vkGetBufferMemoryRequirements(uint64_t,uint64_t,VkMemoryRequirements* r){r->size=8;r->memoryTypeBits=1;}
int p_vkAllocateMemory(uint64_t,const VkMemoryAllocateInfo*,const void*,uint64_t* p){if(fail_allocation){*p=99;return -1;}*p=41;staging_live+=8;staging_peak=std::max(staging_peak,staging_live);return 0;}
int p_vkBindBufferMemory(uint64_t,uint64_t,uint64_t,uint64_t){return 0;}
int p_vkMapMemory(uint64_t,uint64_t,uint64_t,int,int,void** p){mapped_bytes.assign(8,0);*p=mapped_bytes.data();return 0;}
void p_vkUnmapMemory(uint64_t,uint64_t){events.push_back("unmap");}
int p_vkResetCommandBuffer(uint64_t cb,int){assert(cb==17);return 0;}
int p_vkBeginCommandBuffer(uint64_t cb,const VkCommandBufferBeginInfo*){assert(cb==17);events.push_back("begin_private");return 0;}
void transition(uint64_t cb,GpuImage& image,int layout){assert(cb==17);image.layout=layout;}
void p_vkCmdCopyBufferToImage(uint64_t cb,uint64_t buffer,uint64_t image,int,uint32_t count,const VkBufferImageCopy*){
 assert(cb==17 && buffer==31 && image==71 && count==1);events.push_back("copy");
 assert(mapped_bytes==std::vector<uint8_t>({1,2,3,4,5,6,7,8}));
}
void p_vkCmdPipelineBarrier(uint64_t cb,int src,int dst,int,int count,const VkMemoryBarrier* b,int,const void*,int,const void*){
 assert(cb==17 && src==VK_PIPELINE_STAGE_TRANSFER_BIT && dst==VK_PIPELINE_STAGE_ALL_COMMANDS_BIT && count==1);
 assert(b->srcAccessMask==VK_ACCESS_TRANSFER_WRITE_BIT && b->dstAccessMask==(VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT));events.push_back("barrier");
}
int p_vkEndCommandBuffer(uint64_t cb){assert(cb==17);return fail_end?-1:0;}
int p_vkResetFences(uint64_t,uint32_t,const uint64_t*){return 0;}
int p_vkQueueSubmit(uint64_t queue,uint32_t count,const VkSubmitInfo* s,uint64_t fence){
 assert(queue==2 && count==1 && s->commandBufferCount==1 && *s->pCommandBuffers==17 && fence==21);
 submitted=true;events.push_back("submit");return fail_submit?-1:0;
}
int p_vkWaitForFences(uint64_t,uint32_t,const uint64_t*,int,uint64_t ns){assert(ns==2'000'000'000ull);events.push_back("wait");if(timeout)return 1;waited=true;return 0;}
void p_vkDestroyBuffer(uint64_t,uint64_t,const void*){assert(!submitted||waited);events.push_back("destroy");}
void p_vkFreeMemory(uint64_t,uint64_t,const void*){assert(!submitted||waited);assert(staging_live==8);staging_live-=8;events.push_back("free");}
@UPLOAD@
int main(int argc, char**){
 const std::vector<uint8_t> bytes{1,2,3,4,5,6,7,8};const std::vector<VkBufferImageCopy> copies(1);
 GpuImage image;
 if(argc>1){assert(!upload_fresh_astc(image,bytes,copies));assert(events.empty());std::puts("PASS disabled fallback");return 0;}
 assert(upload_fresh_astc(image,bytes,copies));
 assert(image.layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
 assert((events==std::vector<std::string>{"create","unmap","begin_private","copy","barrier","submit","wait","destroy","free"}));
 for(int n=0;n<100;++n){reset();image.layout=0;assert(upload_fresh_astc(image,bytes,copies));assert(staging_live==0);}
 assert(staging_peak==8); // a scene's uploads cannot accumulate staging copies across calls
 reset();image.layout=0;fail_allocation=true;assert(!upload_fresh_astc(image,bytes,copies));
 assert(image.layout==0 && !submitted && events.back()=="destroy");
 reset();image.layout=0;fail_end=true;assert(!upload_fresh_astc(image,bytes,copies));
 assert(image.layout==0 && !submitted && events.back()=="free");
 reset();image.layout=0;fail_submit=true;bool rejected=false;
 try{upload_fresh_astc(image,bytes,copies);}catch(const std::runtime_error&){rejected=true;}
 assert(rejected && !waited && events.back()=="submit"); // failed submit cannot silently reuse staging
 reset();image.layout=0;timeout=true;bool hung=false;
 try{upload_fresh_astc(image,bytes,copies);}catch(const std::runtime_error&){hung=true;}
 assert(hung && submitted && !waited && events.back()=="wait"); // no premature staging free on timeout
 std::puts("PASS: fresh upload uses private commands, copies bytes, waits before freeing, preserves safe fallbacks");
}
'''


def enqueue():
    body = added_file(PATCH, FRAMES)
    start = body.index('void retire_image(')
    return body[start:body.index('\n}', start) + 2]


class WindowsMemoryTests(unittest.TestCase):
    def test_retirement_lifetimes(self):
        cxx = shutil.which('c++') or shutil.which('clang++')
        self.assertIsNotNone(cxx, 'C++20 compiler is required')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'nvn_retire.h').write_text(added_file(PATCH, HEADER))
            (d / 'fixture.cpp').write_text(FIXTURE.replace('@ENQUEUE@', enqueue()))
            args = [cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror',
                    str(d / 'fixture.cpp'), '-o', str(d / 'fixture')]
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(d / 'fixture')], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('20004 images freed exactly once', result.stdout)
            print(result.stdout.strip())

    def test_fresh_upload_protocol(self):
        body = added_file(PATCH, 'runtime/src/nvn/nvn_upload.cpp')
        start = body.index('bool upload_fresh_astc(')
        function = body[start:body.index('\n}\n#endif', start) + 2]
        cxx = shutil.which('c++') or shutil.which('clang++')
        self.assertIsNotNone(cxx, 'C++20 compiler is required')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'upload.cpp').write_text(UPLOAD_FIXTURE.replace('@UPLOAD@', function))
            result = subprocess.run([cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror',
                                     str(d / 'upload.cpp'), '-o', str(d / 'upload')],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            env = dict(os.environ)
            env['NX_WINDOWS_STREAM_UPLOADS'] = '1'
            result = subprocess.run([str(d / 'upload')], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('waits before freeing', result.stdout)
            print(result.stdout.strip())
            for value in [None, '0', 'yes', '10']:
                env.pop('NX_WINDOWS_STREAM_UPLOADS', None)
                if value is not None: env['NX_WINDOWS_STREAM_UPLOADS'] = value
                result = subprocess.run([str(d / 'upload'), 'disabled'], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS disabled fallback', result.stdout)

    def test_patch_scope_and_snapshot_route(self):
        text = PATCH.read_text()
        self.assertEqual(set(re.findall(r'^diff --git a/(\S+) ', text, re.M)), {
            HEADER, FRAMES, 'runtime/src/nvn/nvn.h', 'runtime/src/nvn/nvn_objects.cpp',
            'runtime/src/nvn/nvn_written.cpp', 'runtime/src/nvn/nvn_upload.cpp',
            'runtime/src/hle_fiber.cpp', 'runtime/src/memguard_win.cpp',
            'runtime/src/nvn/nvn_image.cpp', 'runtime/src/nvn/nvn_vk.cpp',
            'runtime/src/nvn/nvn_vk.h', 'runtime/src/win_mem_account.h',
            'runtime/src/win_mem_vk.h', 'runtime/src/win_mem_va.h'})
        self.assertIn('if (snap && detail::image_retirement_on()) retire_image(std::move(snap->image));', text)
        self.assertIn('detail::release_retired_images(dead,', text)
        self.assertIn('std::getenv("NX_MEM_TRACE")', text)
        self.assertNotRegex(text, r'/(?:Users|home)/|C:\\acr')

    def test_texture_queue_accounting_never_waits_on_game_thread(self):
        body = added_file(PATCH,'runtime/src/nvn/nvn_objects.cpp')
        start = body.index('void memory_trace_objects(')
        function = body[start:body.index('\n}',start)+2]
        code = r'''#include <cassert>
#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
struct Object { virtual ~Object() = default; };
struct Texture : Object { struct Write { std::vector<uint8_t> data; }; std::vector<Write> writes; };
std::mutex object_mutex;
std::map<uint64_t,std::unique_ptr<Object>> all_objects;
std::mutex& objects_lock() { return object_mutex; }
auto& objects() { return all_objects; }
std::string line;
void log(const char* fmt,...) { char text[1024]; va_list ap;va_start(ap,fmt);std::vsnprintf(text,sizeof text,fmt,ap);va_end(ap);line=text; }
@FUNCTION@
int main() {
 auto a=std::make_unique<Texture>(), b=std::make_unique<Texture>();
 a->writes.resize(2); a->writes[0].data.resize(3); a->writes[1].data.resize(5);
 b->writes.resize(1); b->writes[0].data.resize(3);
 all_objects[1]=std::move(a);all_objects[2]=std::move(b);all_objects[3]=std::make_unique<Object>();all_objects[4]=nullptr;
 memory_trace_objects(17);
 assert(line.find("ts_ns=17 live_bytes=11")!=std::string::npos);
 assert(line.find("writes=3 textures=2 busy=0")!=std::string::npos);
 std::atomic<bool> locked{false},done{false};
 std::thread game([&] { std::lock_guard lock(object_mutex);locked=true;while(!done)std::this_thread::yield(); });
 while(!locked)std::this_thread::yield();memory_trace_objects(19);
 assert(line.find("ts_ns=19 busy=1")!=std::string::npos);done=true;game.join();
 std::puts("PASS production texture-queue inventory: payload/capacity ownership and nonblocking busy samples");
}
'''
        with tempfile.TemporaryDirectory() as d:
            MemoryAccountingTests.compile_and_run(self,d,code.replace('@FUNCTION@',function))

    def test_repairs_are_opt_in_and_guard_unchanged(self):
        source = added_file(PATCH, HEADER)
        cxx = shutil.which('c++') or shutil.which('clang++')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d/'nvn_retire.h').write_text(source)
            (d/'test.cpp').write_text('#include "nvn_retire.h"\n#include <cstdio>\nint main(){std::printf("%d",nx::nvn::detail::image_retirement_on());}')
            p = subprocess.run([cxx, '-std=c++20', str(d/'test.cpp'), '-o', str(d/'test')], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            for setting, expected in [(None,'0'),('0','0'),('1','1'),('yes','0'),('10','0')]:
                env = dict(os.environ)
                env.pop('NX_WINDOWS_IMAGE_RETIRE_FIX', None)
                if setting is not None: env['NX_WINDOWS_IMAGE_RETIRE_FIX'] = setting
                p = subprocess.run([str(d/'test')], env=env, capture_output=True, text=True)
                self.assertEqual((p.returncode,p.stdout), (0,expected), p.stderr)
        text = PATCH.read_text()
        self.assertNotIn('memory_limit_gb', text)
        self.assertNotIn('-    const double gb =', text)
        self.assertIn('ticks % 20 == 0', text)



ACCOUNT_FIXTURE = r"""
#include <cassert>
#include <thread>
#include <vector>
#include "win_mem_account.h"
using namespace nx::memtrace;
int main() {
    Ledger ledger;
    ledger.allocated(Domain::Memory, 7, Pool::Images, 128);
    ledger.allocated(Domain::Memory, 7, Pool::Images, 999); // duplicate cannot inflate live bytes
    ledger.allocated(Domain::Shader, 7, Pool::ShaderCode, 16); // distinct Vulkan handle domains
    ledger.orphaned_image(7);
    auto s = ledger.snapshot();
    assert(s.pools[size_t(Pool::Images)].live == 128 && s.dropped == 1);
    assert(s.orphaned_images == 1 && s.orphaned_bytes == 128);
    ledger.freed(Domain::Memory, 7); ledger.freed(Domain::Memory, 7);
    ledger.freed(Domain::Shader, 7);
    ledger.allocated(Domain::Memory, 7, Pool::OtherVulkan, 32); // recycled handle, new category
    ledger.orphaned_image(7); // borrowed/unclassified images are not reported as texture leaks
    ledger.freed(Domain::Memory, 7);
    s = ledger.snapshot(); assert(s.unknown_frees == 1 && s.orphaned_images == 1);
    assert(s.pools[size_t(Pool::Images)].peak == 128 && s.pools[size_t(Pool::Images)].frees == 1);
    std::vector<std::thread> threads;
    for (uint64_t n = 0; n < 4; ++n) threads.emplace_back([&,n] {
        assert(allocation_pool == Pool::OtherVulkan);
        Tag outer(Pool::Staging);
        { Tag inner(Pool::Images); assert(allocation_pool == Pool::Images); }
        assert(allocation_pool == Pool::Staging);
        for (uint64_t k = 1; k <= 2000; ++k) {
            uint64_t id = 100 + n*2000 + k;
            ledger.allocated(Domain::Memory, id, allocation_pool, 64);
            ledger.payload_add(Pool::DecodedStore, 32);
            ledger.payload_free(Pool::DecodedStore, 32);
            ledger.freed(Domain::Memory, id);
        }
    });
    for (auto& thread : threads) thread.join();
    assert(allocation_pool == Pool::OtherVulkan);
    s = ledger.snapshot();
    for (const auto& c : s.pools) assert(c.live == 0 && c.allocations == c.frees);
    assert(s.pools[size_t(Pool::Staging)].allocations == 8000);
    assert(s.pools[size_t(Pool::DecodedStore)].total == 256000);
    assert(s.dropped == 1 && s.unknown_frees == 1);
    std::puts("PASS concurrent accounting: duplicate/recycled handles, ownership leaks and bounded payload lifetimes");
}
"""


VULKAN_ACCOUNT_FIXTURE = r"""
#include <cassert>
#include <cstdio>
#include "win_mem_vk.h"
using namespace nx::memtrace;
template<class T> T object(uint64_t n) {
    if constexpr (std::is_pointer_v<T>) return reinterpret_cast<T>(uintptr_t(n));
    else return T(n);
}
bool fail = false;
unsigned underlying_frees = 0, calls = 0;
VKAPI_ATTR VkResult VKAPI_CALL fake_allocate(VkDevice, const VkMemoryAllocateInfo*, const VkAllocationCallbacks*, VkDeviceMemory* out) {
    ++calls; *out = object<VkDeviceMemory>(fail ? 99 : 7); return fail ? VK_ERROR_OUT_OF_DEVICE_MEMORY : VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL fake_free(VkDevice, VkDeviceMemory, const VkAllocationCallbacks*) { ++underlying_frees; }
VKAPI_ATTR VkResult VKAPI_CALL fake_shader(VkDevice, const VkShaderModuleCreateInfo*, const VkAllocationCallbacks*, VkShaderModule* out) {
    *out = object<VkShaderModule>(7); return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL fake_destroy_shader(VkDevice, VkShaderModule, const VkAllocationCallbacks*) {}
VKAPI_ATTR VkResult VKAPI_CALL fake_graphics(VkDevice, VkPipelineCache, uint32_t n, const VkGraphicsPipelineCreateInfo*, const VkAllocationCallbacks*, VkPipeline* out) {
    assert(n == 2); out[0] = object<VkPipeline>(7); out[1] = VK_NULL_HANDLE; return VK_ERROR_OUT_OF_HOST_MEMORY;
}
VKAPI_ATTR VkResult VKAPI_CALL fake_compute(VkDevice, VkPipelineCache, uint32_t n, const VkComputePipelineCreateInfo*, const VkAllocationCallbacks*, VkPipeline* out) {
    assert(n == 1); out[0] = object<VkPipeline>(8); return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL fake_destroy_pipeline(VkDevice, VkPipeline, const VkAllocationCallbacks*) {}
namespace nx::vk {
PFN_vkAllocateMemory p_vkAllocateMemory = fake_allocate;
PFN_vkFreeMemory p_vkFreeMemory = fake_free;
PFN_vkCreateShaderModule p_vkCreateShaderModule = fake_shader;
PFN_vkDestroyShaderModule p_vkDestroyShaderModule = fake_destroy_shader;
PFN_vkCreateGraphicsPipelines p_vkCreateGraphicsPipelines = fake_graphics;
PFN_vkCreateComputePipelines p_vkCreateComputePipelines = fake_compute;
PFN_vkDestroyPipeline p_vkDestroyPipeline = fake_destroy_pipeline;
}
int main() {
    using namespace nx::vk;
    install_vulkan(); install_vulkan(); // installing twice must not wrap a wrapper recursively
    assert((p_vkAllocateMemory == allocate) == enabled());
    VkMemoryAllocateInfo info{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; info.allocationSize = 4096;
    VkDeviceMemory memory{};
    {
        Tag image(Pool::Images);
        assert(p_vkAllocateMemory({}, &info, nullptr, &memory) == VK_SUCCESS && handle(memory) == 7);
    }
    assert(ledger().snapshot().pools[size_t(Pool::Images)].live == (enabled() ? 4096 : 0));
    p_vkFreeMemory({}, memory, nullptr);
    fail = true;
    assert(p_vkAllocateMemory({}, &info, nullptr, &memory) == VK_ERROR_OUT_OF_DEVICE_MEMORY && handle(memory) == 99);
    assert(calls == 2 && underlying_frees == 1);
    VkShaderModuleCreateInfo shader_info{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; shader_info.codeSize = 88;
    VkShaderModule module{}; assert(p_vkCreateShaderModule({}, &shader_info, nullptr, &module) == VK_SUCCESS);
    p_vkDestroyShaderModule({}, module, nullptr);
    VkPipeline pipes[2]{};
    assert(p_vkCreateGraphicsPipelines({}, {}, 2, nullptr, nullptr, pipes) == VK_ERROR_OUT_OF_HOST_MEMORY);
    p_vkDestroyPipeline({}, pipes[0], nullptr);
    assert(p_vkCreateComputePipelines({}, {}, 1, nullptr, nullptr, pipes) == VK_SUCCESS);
    p_vkDestroyPipeline({}, pipes[0], nullptr);
    const auto s = ledger().snapshot();
    for (const auto& c : s.pools) assert(!c.live && c.allocations == c.frees);
    assert(!s.dropped && !s.unknown_frees);
    assert(s.pools[size_t(Pool::GraphicsPipelines)].total == (enabled() ? 1 : 0));
    assert(s.pools[size_t(Pool::ComputePipelines)].total == (enabled() ? 1 : 0));
    assert(s.pools[size_t(Pool::ShaderCode)].total == (enabled() ? 88 : 0));
    std::puts("PASS real Vulkan ABI hooks: disabled identity, failed allocation outputs, partial pipeline batches and frees");
}
"""


VA_WINDOWS_STUB = r"""
#pragma once
#include <cstdint>
#include <cstddef>
using HANDLE = void*;
constexpr unsigned MEM_FREE=1,MEM_RESERVE=2,MEM_COMMIT=4,MEM_PRIVATE=8,MEM_MAPPED=16,MEM_IMAGE=32,PAGE_GUARD=64;
struct MEMORY_BASIC_INFORMATION { void* BaseAddress; void* AllocationBase; size_t RegionSize; unsigned State,Protect,Type; };
struct SYSTEM_INFO { void* lpMaximumApplicationAddress; };
inline HANDLE GetCurrentProcess() { return nullptr; }
void GetSystemInfo(SYSTEM_INFO*);
size_t VirtualQueryEx(HANDLE,void*,MEMORY_BASIC_INFORMATION*,size_t);
"""
VA_FIXTURE = r"""
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
namespace nx {
constexpr uint64_t kHeapBase=0x100000,kHeapMax=0x20000,kAliasBase=0x200000,kAliasSize=0x1000;
constexpr uint64_t kStackBase=0x300000,kStackSize=0x1000,kKernelBase=0x600000,kKernelSize=0x1000;
namespace plat { uint64_t monotonic_ns() { return 123; } }
std::vector<std::string> lines;
void log(const char* fmt, ...) { char out[2048]; va_list ap; va_start(ap,fmt); std::vsnprintf(out,sizeof out,fmt,ap); va_end(ap); lines.emplace_back(out); }
}
#include "win_mem_va.h"
struct Range { uintptr_t base,allocation; size_t size; unsigned state,protect,type; };
Range ranges[] = {
 {0,0,0x100000,MEM_FREE,0,0},
 {0x100000,0x100000,0x1000,MEM_COMMIT,0,MEM_PRIVATE},
 {0x101000,0x100000,0x1f000,MEM_RESERVE,0,MEM_PRIVATE},
 {0x120000,0,0xe0000,MEM_FREE,0,0},
 {0x200000,0x200000,0x1000,MEM_COMMIT,0,MEM_MAPPED},
 {0x201000,0,0xff000,MEM_FREE,0,0},
 {0x300000,0x300000,0x1000,MEM_COMMIT,0,MEM_PRIVATE},
 {0x301000,0,0xff000,MEM_FREE,0,0},
 {0x400000,0x400000,0x6000,MEM_RESERVE,0,MEM_PRIVATE},
 {0x406000,0x400000,0x1000,MEM_COMMIT,PAGE_GUARD,MEM_PRIVATE},
 {0x407000,0x400000,0x3000,MEM_COMMIT,0,MEM_PRIVATE},
 {0x40a000,0,0xf6000,MEM_FREE,0,0},
 {0x500000,0x500000,0x1000,MEM_COMMIT,0,MEM_IMAGE}
};
bool fail_query=false;
void GetSystemInfo(SYSTEM_INFO* s) { s->lpMaximumApplicationAddress=reinterpret_cast<void*>(0x500fff); }
size_t VirtualQueryEx(HANDLE,void* ptr,MEMORY_BASIC_INFORMATION* out,size_t bytes) {
 assert(bytes==sizeof(*out));if(fail_query)return 0;
 for(auto& r:ranges) if(reinterpret_cast<uintptr_t>(ptr)==r.base) {
  *out={reinterpret_cast<void*>(r.base),reinterpret_cast<void*>(r.allocation),r.size,r.state,r.protect,r.type};return sizeof(*out);
 }
 assert(false);return 0;
}
bool has(const char* fragment) { for(auto& s:nx::lines)if(s.find(fragment)!=std::string::npos)return true;return false; }
int main() {
 nx::memtrace::sample(1ull<<30);
 assert(has("private=24576 mapped=4096 image=4096 guest_heap=4096 guest_alias=4096 guest_stack_kernel=4096"));
 assert(has("guarded_stack_groups=1 guarded_stack_commit=16384 guarded_stack_reserve=40960 query_failed=0"));
 assert(has("va_peak ts_ns=123 base=400000 reserved=40960 committed=16384 guard=1"));
 auto count=nx::lines.size();nx::memtrace::sample((1ull<<30)+(1<<20));
 for(size_t i=count;i<nx::lines.size();++i)assert(nx::lines[i].find("va_peak")==std::string::npos);
 fail_query=true;nx::memtrace::sample(1ull<<30);assert(has("query_failed=1"));
 std::puts("PASS production VirtualQueryEx inventory: committed vs reserved, guest aliases, guarded stacks, peak threshold and failed queries");
}
"""


IMAGE_CACHE_FIXTURE = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>
#include "nvn_retire.h"
using VkQueue=uint64_t;
constexpr uint64_t VK_NULL_HANDLE=0;
constexpr int VK_SUCCESS=0;
namespace nx {
namespace memtrace { bool enabled() { return true; } }
namespace plat { uint64_t now=10'000'000'000ull; uint64_t monotonic_ns() { return now; } }
void log(const char*,...) {}
namespace nvn {
struct Object { virtual ~Object()=default; };
struct GpuImage {
 uint64_t image=1,memory=1,view=1,memory_bytes=0,cache_last_use_ns=0;
 bool uploaded=true,rendered=false,texels=false;
};
struct Texture:Object {
 std::shared_ptr<GpuImage> image;
 uint64_t pool=1,offset=256,storage_size=128,memory=0x100100;
 std::atomic<bool> has_writes{false}; uint32_t format=42;
};
struct MemoryPool:Object {
 uint64_t memory=0x100000,size=1ull<<40;
 struct Mapping { uint64_t physical=0,physical_offset=0,size=0; };
 std::map<uint64_t,Mapping> mappings;
};
std::mutex mutex;
std::map<uint64_t,std::unique_ptr<Object>> map;
auto& objects() { return map; }
auto& objects_lock() { return mutex; }
uint64_t submit_start_ns() { return 9'000'000'000ull; }
bool astc_decoded(uint32_t format) { return format==42; }
std::map<uint64_t,std::weak_ptr<GpuImage>> g_live_images;
bool waited=false,fail_wait=false;
unsigned freed=0;
VkQueue vk_queue() { return 1; }
uint64_t vk_device() { return 2; }
int p_vkQueueWaitIdle(VkQueue q) { assert(q==1); waited=true; return fail_wait?-1:0; }
[[noreturn]] void gpu_hung(const char*) { throw std::runtime_error("wait failed"); }
void forget_image_views(GpuImage&) { assert(waited); }
void p_vkDestroyImageView(uint64_t,uint64_t,const void*) { assert(waited); }
void p_vkDestroyImage(uint64_t,uint64_t,const void*) { assert(waited); }
void p_vkFreeMemory(uint64_t,uint64_t,const void*) { assert(waited); ++freed; }
@FUNCTION@
Texture* add(uint64_t key,uint64_t bytes=32ull<<20,uint64_t used=1'000'000'000ull) {
 auto texture=std::make_unique<Texture>(); texture->image=std::make_shared<GpuImage>();
 texture->image->memory_bytes=bytes; texture->image->cache_last_use_ns=used;
 auto* result=texture.get(); g_live_images[key]=texture->image; map[key]=std::move(texture); return result;
}
}}
int main(int argc,char**) {
 using namespace nx::nvn;
 // Even an image idle for three seconds stays alive if this recording touched it.
 assert(!detail::cold_image_candidate(9'000'000'000ull,12'000'000'000ull,9'000'000'000ull,true,true,false,false));
 assert(detail::cold_image_candidate(8'000'000'000ull,12'000'000'000ull,9'000'000'000ull,true,true,false,false));
 assert(!detail::cold_image_candidate(0,12'000'000'000ull,9'000'000'000ull,true,true,false,false));
 assert(!detail::cold_image_candidate(8'900'000'000ull,9'100'000'000ull,9'000'000'000ull,true,true,false,false));
 assert(detail::cold_image_candidate(8'800'000'000ull,9'100'000'000ull,9'000'000'000ull,true,true,false,false));
 map[1]=std::make_unique<MemoryPool>();
 auto virtual_pool=std::make_unique<MemoryPool>(); virtual_pool->memory=0;
 virtual_pool->size=1<<20;virtual_pool->mappings[0]={1,0,1<<20};map[2]=std::move(virtual_pool);
 auto* a=add(10,1ull<<30,1'000'000'000ull);
 auto* b=add(11,1ull<<30,2'000'000'000ull);
 auto alias=std::make_unique<Texture>();alias->image=b->image;alias->pool=2;
 auto* alias_pointer=alias.get();map[12]=std::move(alias);
 auto* rendered=add(13);rendered->image->rendered=true;
 auto* texels=add(14);texels->image->texels=true;
 auto* current=add(15,32ull<<20,9'000'000'001ull);
 auto* external_texture=add(16);auto external=external_texture->image;
 auto* snapshot=add((1ull<<63)+1);
 auto* missing_pool=add(17);missing_pool->pool=99;
 auto* bad_backing=add(18);bad_backing->memory++;
 auto* pending_write=add(19);pending_write->has_writes=true;
 auto* unuploaded=add(20);unuploaded->image->uploaded=false;
 auto* hot=add(21,32ull<<20,9'900'000'000ull);
 auto* native=add(22);native->format=0;
 auto bad_virtual=std::make_unique<MemoryPool>();bad_virtual->memory=0;
 bad_virtual->size=1<<20;bad_virtual->mappings[0]={99,0,1<<20};map[3]=std::move(bad_virtual);
 auto* bad_mapping=add(23);bad_mapping->pool=3;
 if(argc>1)fail_wait=true;
 bool rejected=false;try { trim_windows_image_cache(); }catch(const std::runtime_error&) { rejected=true; }
 if(argc>1) { assert(rejected && freed==0 && a->image && b->image); return 0; }
 if(nx::nvn::detail::image_cache_on()) {
  assert(waited && freed==2 && !a->image && !b->image && !alias_pointer->image);
  assert(!g_live_images.count(10) && !g_live_images.count(11));
 } else { assert(!waited && freed==0 && a->image && b->image && alias_pointer->image); }
 for(auto* t:{rendered,texels,current,external_texture,snapshot,missing_pool,bad_backing,pending_write,unuploaded,hot,native,bad_mapping}) assert(t->image && t->image->image);
 std::puts("PASS production image cache: cold aliases evicted after idle; recording/hot/GPU-written/texel/deferred/invalid-backing owners protected");
}
"""


class MemoryAccountingTests(unittest.TestCase):
    def compile_and_run(self, directory, code, env=None, includes=()):
        d = Path(directory)
        cxx = shutil.which('c++') or shutil.which('clang++')
        self.assertIsNotNone(cxx)
        (d/'test.cpp').write_text(code)
        p = subprocess.run([cxx, '-std=c++20', '-pthread', '-Wall', '-Wextra', '-Werror',
            '-Wno-missing-field-initializers', *includes, str(d/'test.cpp'), '-o', str(d/'test')],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        p = subprocess.run([str(d/'test')], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        print(p.stdout.strip())

    def test_concurrent_allocation_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'win_mem_account.h').write_text(added_file(PATCH,'runtime/src/win_mem_account.h'))
            self.compile_and_run(d, ACCOUNT_FIXTURE)


class MemoryIntegrationTests(MemoryAccountingTests):
    @classmethod
    def setUpClass(cls):
        common = Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute(): common = (ROOT/common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE',str(common.parent/'.local/units/RENDER-FID-021/reference')))
        if not (reference/'.git').exists(): raise unittest.SkipTest('private pinned runtime unavailable; no downloads')
        cls.temp = tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name)
        names = [s.split('#')[0].strip() for s in (ROOT/'runtime/patches/series.windows').read_text().splitlines()]
        names = [n for n in names if n]
        assert names.count(PATCH.name) == 1
        cls.before = cls.out/'before';cls.after = cls.out/'after'
        runtime.prepare_source(reference, cls.before, [ROOT/'runtime/patches'/n for n in names[:names.index(PATCH.name)]])
        shutil.copytree(cls.before,cls.after,ignore=shutil.ignore_patterns('fsmonitor--daemon.ipc'))
        subprocess.run(['git','-C',str(cls.after),'apply','--check',str(PATCH)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(cls.after),'apply',str(PATCH)],check=True,capture_output=True)
        cls.full = cls.out/'full'
        runtime.prepare_source(reference, cls.full, [ROOT/'runtime/patches'/n for n in names])

    def test_texture_sampler_has_external_linkage(self):
        # The extracted sampler fixture cannot detect an anonymous-namespace definition.
        # Check its placement in the complete production TU: frames calls this symbol.
        source = (self.full/'runtime/src/nvn/nvn_objects.cpp').read_text()
        start = source.index('void memory_trace_objects(')
        self.assertGreater(start, source.rindex('\n}  // namespace\n'))
        self.assertLess(start, source.index('NX_HLE("nvnMemoryPoolInitialize"'))
        header = (self.full/'runtime/src/nvn/nvn.h').read_text()
        self.assertIn('void memory_trace_objects(uint64_t stamp);', header)

    def test_guard_peak_inventory_keeps_normal_stop_policy(self):
        source = (self.full/'runtime/src/memguard_win.cpp').read_text()
        start = source.index('double memory_limit_gb(')
        policy = source[start:source.index('\n}', start)+2]
        start = source.index('void start_memory_guard(')
        guard = source[start:source.index('\n}\n\n#endif', start)+2]
        # Execute the production loop synchronously against a deterministic footprint.
        # Only scheduling and process termination are replaced; no real VM is used.
        guard = guard.replace('std::thread(', 'FakeThread(').replace(
            'std::this_thread::sleep_for(', 'fake_sleep(')
        code = r'''#include <cassert>
#include <chrono>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#define _WIN32 1
#define NX_ASTRAL_STRICT 1
struct Stopped {};
unsigned tick=0, polls=0, terminations=0;
std::vector<std::string> lines;
std::vector<unsigned> inventories;
void* GetCurrentProcess() { return reinterpret_cast<void*>(42); }
[[noreturn]] void TerminateProcess(void* process, unsigned code) {
    assert(process==GetCurrentProcess() && code==3); ++terminations; throw Stopped{};
}
namespace nx {
void log(const char* fmt,...) {
    char text[512]; va_list ap; va_start(ap,fmt);
    std::vsnprintf(text,sizeof text,fmt,ap); va_end(ap); lines.emplace_back(text);
}
namespace memtrace {
bool enabled() { const char* e=std::getenv("NX_MEM_TRACE"); return e && e[0]=='1'; }
void sample(uint64_t) { inventories.push_back(tick); }
}
namespace plat {
struct FakeThread {
    template<class F> FakeThread(F run) { try { run(); } catch(const Stopped&) {} }
    void detach() {}
};
void fake_sleep(std::chrono::milliseconds duration) {
    assert(duration.count()==250); ++tick; assert(tick<=23);
}
uint64_t monotonic_ns() { return uint64_t(tick)*250000000; }
uint64_t memory_footprint() {
    ++polls;
    if(tick==20) return (1ull<<30)+(1ull<<20);
    if(tick==21) return (1ull<<30)+(65ull<<20);
    if(tick==22) return 512ull<<20;
    if(tick==23) return (8ull<<30)+1;
    return 1ull<<30;
}
@POLICY@
@GUARD@
}}
int main() {
    assert(nx::plat::memory_limit_gb(nullptr)==8.0);
    assert(nx::plat::memory_limit_gb("0")==8.0);
    nx::plat::start_memory_guard();
    assert(tick==23 && polls==23 && terminations==1);
    bool stopped=false, raw_stop=false, exact_peak=false;
    for(const auto& line:lines) {
        stopped|=line.find("over the 8.0 GB limit")!=std::string::npos;
        raw_stop|=line.find("private_bytes=8589934593 peak_private_bytes=8589934593 guard_stop=1")!=std::string::npos;
        exact_peak|=line.find("private_bytes=1141899264 peak_private_bytes=1141899264 guard_stop=0")!=std::string::npos;
    }
    assert(stopped);
    if(nx::memtrace::enabled()) {
        assert((inventories==std::vector<unsigned>{1,20,21}));
        assert(raw_stop && exact_peak);
    } else { assert(inventories.empty() && !raw_stop && !exact_peak); }
    std::puts("PASS production guard: 250ms checks, exact peaks, 64MiB inventories, unchanged 8GiB stop with trace on/off");
}
'''.replace('@POLICY@', policy).replace('@GUARD@', guard)
        with tempfile.TemporaryDirectory() as d:
            for value in ['0','1']:
                env = dict(os.environ, NX_MEM_TRACE=value)
                env.pop('NX_MEM_LIMIT_GB', None)
                self.compile_and_run(d, code, env)

    def test_image_cache_reconstruction_and_gpu_lifetimes(self):
        source = (self.full/'runtime/src/nvn/nvn_image.cpp').read_text()
        start = source.index('void trim_windows_image_cache(')
        function = source[start:source.index('\n}\n#endif',start)+2]
        code = IMAGE_CACHE_FIXTURE
        code = code.replace('@FUNCTION@', function)
        with tempfile.TemporaryDirectory() as d:
            flags = ['-I',str(self.full/'runtime/src/nvn')]
            for value in ['0','1']:
                self.compile_and_run(d,code,dict(os.environ,NX_WINDOWS_IMAGE_CACHE=value),flags)
            # A failed queue wait cannot discard any image still possibly in flight.
            self.compile_and_run(d,code,dict(os.environ,NX_WINDOWS_IMAGE_CACHE='1'),flags)
            p = subprocess.run([str(Path(d)/'test'),'fail-wait'],
                env=dict(os.environ,NX_WINDOWS_IMAGE_CACHE='1'),capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_hooks_with_actual_vulkan_dispatch_types(self):
        include = Path(os.environ.get('NVN_VULKAN_INCLUDE','/opt/homebrew/include'))
        if not (include/'vulkan/vulkan.h').is_file(): self.skipTest('existing Vulkan headers required')
        with tempfile.TemporaryDirectory() as d:
            flags = ['-I',str(self.full/'runtime/src'),'-I',str(self.full/'runtime/include'),'-I',str(include)]
            for value in ['0','1']:
                self.compile_and_run(d,VULKAN_ACCOUNT_FIXTURE,dict(os.environ,NX_MEM_TRACE=value),flags)

    def test_production_resident_observers_preserve_snapshot_aliases_and_scopes(self):
        resident = (self.full/'runtime/src/nvn/nvn_resident.h').read_text()
        start = resident.index('struct ResidentMemoryTrace {')
        observer = resident[start:resident.index('\n};',start)+3]
        vk = (self.full/'runtime/src/nvn/nvn_vk.cpp').read_text()
        self.assertIn('#include "nvn_retire.h"',vk)
        registration = vk.split('    memtrace::install_vulkan();\n',1)[1].split('#endif',1)[0]
        code = '''#include <cassert>
#include <cstdio>
#include "win_mem_account.h"
#include "nvn/nvn_retire.h"
namespace nx::nvn::replay { @OBSERVER@ }
namespace nx::nvn { void register_observers() { @REGISTER@ } }
int main() {
    using namespace nx::memtrace;
    using nx::nvn::replay::ResidentMemoryTrace;
    nx::nvn::register_observers();
    allocation_pool = Pool::Staging;
    {
        ResidentMemoryTrace first; assert(allocation_pool == Pool::Resident);
        { ResidentMemoryTrace nested; assert(allocation_pool == Pool::Resident); }
        assert(allocation_pool == Pool::Resident);
    }
    assert(allocation_pool == Pool::Staging);
    auto snapshot = ResidentMemoryTrace::snapshot(64); auto in_flight = snapshot;
    auto& stats = nx::nvn::detail::resident_snapshots;
    assert(stats.live == 64 && stats.allocations == 1);
    for (auto byte : *snapshot) assert(byte == 0);
    snapshot.reset(); assert(stats.live == 64 && stats.frees == 0);
    in_flight.reset(); assert(stats.live == 0 && stats.frees == 1);
    std::puts("PASS production resident observers: nested allocation tags and final in-flight snapshot ownership");
}
'''
        code = code.replace('@OBSERVER@',observer).replace('@REGISTER@',registration)
        with tempfile.TemporaryDirectory() as d:
            self.compile_and_run(d,code,dict(os.environ,NX_MEM_TRACE='1'),['-I',str(self.full/'runtime/src')])

    def test_virtual_query_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'windows.h').write_text(VA_WINDOWS_STUB)
            flags = ['-I',str(d),'-I',str(self.full/'runtime/src')]
            self.compile_and_run(d,VA_FIXTURE,dict(os.environ,NX_MEM_TRACE='1'),flags)

    @unittest.skipUnless(sys.platform == 'darwin', 'host SDK preprocessing proof uses the Mac compiler')
    def test_shared_translation_units_preprocess_identically(self):
        cxx = shutil.which('c++') or shutil.which('clang++')
        source_names = ['hle_fiber.cpp','nvn/nvn_frames.cpp','nvn/nvn_image.cpp',
                        'nvn/nvn_objects.cpp','nvn/nvn_upload.cpp','nvn/nvn_vk.cpp','nvn/nvn_written.cpp']
        include = os.environ.get('NVN_VULKAN_INCLUDE','/opt/homebrew/include')
        prelude = self.out/'linux-guards.h'
        headers = ('algorithm array atomic chrono cmath cstdio cstdlib cstring deque filesystem '
                   'fstream functional iterator map memory mutex new set sstream string thread tuple type_traits unordered_map utility vector')
        prelude.write_text(''.join(f'#include <{h}>\n' for h in headers.split()) + '#undef __APPLE__\n#define __linux__ 1\n')
        for platform, flags in [('macos',[]),('linux-guards',['-include',str(prelude)])]:
            for rel in source_names:
                with self.subTest(platform=platform,source=rel):
                    outputs=[]
                    for tree in [self.before,self.after]:
                        command=[cxx,'-std=c++20','-E','-P','-DNX_ASTRAL_STRICT=1',*flags,
                            '-I',str(tree/'runtime/include'),'-I',str(tree/'runtime/src'),'-I',include,
                            str(tree/'runtime/src'/rel)]
                        p=subprocess.run(command,capture_output=True,text=True,timeout=60)
                        self.assertEqual(p.returncode,0,p.stderr)
                        # Only registrar identifiers encode __LINE__; their constructor arguments and order stay exact.
                        normalized = re.sub(r'\b((?:hle_|nvn_)?reg_)\d+\b',r'\1LINE',p.stdout)
                        outputs.append(''.join(normalized.split()))
                    self.assertEqual(outputs[0],outputs[1])
        for platform in ['macos','linux']:
            self.assertNotIn(PATCH.name,(ROOT/f'runtime/patches/series.{platform}').read_text())


if __name__ == '__main__':
    unittest.main()
