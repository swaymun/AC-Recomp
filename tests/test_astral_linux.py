"""Linux overlay (astral-linux.patch, docs/ASTRAL_LINUX.md): the series, the overlay applying after series.macos on
the pinned runtime, and the Linux fiber context switch (fiber_context_linux.S with hle_fiber.cpp's prepare_entry),
assembled for x86-64 and arm64 ELF and, on a Linux host, run through first entry, resumption and the preserved
callee-saved/floating-point control state. No game, GPU or window is used."""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import acr_build as acr  # noqa: E402
import prepare_runtime as runtime  # noqa: E402
from test_astral_touch import added_file  # noqa: E402

PATCHES = ROOT / 'runtime/patches'
OVERLAY = PATCHES / 'astral-linux.patch'
ASM = 'runtime/src/fiber_context_linux.S'
FIBER = 'runtime/src/hle_fiber.cpp'


def prepare_entry_block() -> str:
    """HostContext, the assembly entry points and prepare_entry, as hle_fiber.cpp has them after the overlay."""
    body = added_file(OVERLAY, FIBER)
    start = body.index('#if defined(__aarch64__)\nstruct alignas(16) HostContext')
    end = body.index('\n}\n', body.index('void prepare_entry(')) + 3
    return body[start:end]


HARNESS = r'''
#include <cassert>
#include <cfenv>
#include <cstdint>
#include <cstdio>
#include <cstddef>
#include <sys/mman.h>
struct alignas(16) V128 { uint64_t lo, hi; };
namespace {
@BLOCK@
HostContext root, fiber;
int entries = 0, resumes = 0;
volatile uintptr_t entry_sp = 0;
[[noreturn]] void enter(void* arg) {
    assert(arg == nullptr);
    alignas(16) volatile char probe[16];
    entry_sp = reinterpret_cast<uintptr_t>(probe);
    assert(entry_sp % 16 == 0);
    entries++;
    for (;;) {
        std::fesetround(FE_UPWARD);  // the fiber's own rounding mode
        nx_fiber_swap(&fiber, &root);
        assert(std::fegetround() == FE_UPWARD);
        resumes++;
    }
}
}  // namespace
int main() {
    const size_t bytes = 1 << 20;
    void* stack = mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(stack != MAP_FAILED);
    const uintptr_t top = reinterpret_cast<uintptr_t>(stack) + bytes;
    prepare_entry(fiber, top);
    std::fesetround(FE_TOWARDZERO);
    volatile uint64_t keep[6] = {1, 2, 3, 4, 5, 6};
    uint64_t sum = 0;
    for (int k = 0; k < 5; k++) {
        uint64_t a = keep[k % 6] * 7 + k, b = a ^ 0x5a5a;  // live across the swap in callee-saved registers
        nx_fiber_swap(&root, &fiber);
        assert(std::fegetround() == FE_TOWARDZERO);
        sum += a + b;
        assert(b == (a ^ 0x5a5a));
    }
    assert(entries == 1 && resumes == 4);
    assert(entry_sp > top - 4096 && entry_sp < top);
    std::printf("PASS fiber: 1 entry, 4 resumes, sum %llu\n", (unsigned long long)sum);
    return 0;
}
'''


class LinuxSeriesTest(unittest.TestCase):
    def test_linux_series_is_the_macos_series_then_the_overlay(self):
        macos = acr.read_series(PATCHES / 'series.macos')
        linux = acr.read_series(PATCHES / 'series.linux')
        self.assertEqual(linux, [*macos, OVERLAY.name])

    def test_overlay_is_public_and_limited(self):
        text = OVERLAY.read_text()
        self.assertNotRegex(text, r'/(?:Users|home|work)/')
        files = re.findall(r'^diff --git a/(\S+) ', text, re.M)
        self.assertEqual(files, ['CMakeLists.txt', ASM, FIBER, 'runtime/src/kernel.cpp', 'runtime/src/nvn/nvn_caps.cpp',
                                 'runtime/src/nvn/nvn_vk.cpp', 'runtime/src/nvn/nvn_frames.cpp',
                                 'runtime/src/nvn/nvn_linux_staging.h'])
        # The host-cached upload ring default is Linux-only; other hosts keep NX_RING_CACHED opt-in.
        caps = text.split('+++ b/runtime/src/nvn/nvn_caps.cpp', 1)[1].split('\ndiff --git ', 1)[0]
        self.assertIn('+#if defined(__linux__) && !defined(__ANDROID__)\n', caps)
        self.assertIn('+    if (!e) e = "1";\n', caps)
        # The Linux branch of CMakeLists.txt gains the fiber sources; the Apple branch is untouched.
        cmake = text.split('diff --git a/CMakeLists.txt', 1)[1].split('\ndiff --git ', 1)[0]
        self.assertIn('@@ -248,7 +248,9 @@ elseif(UNIX)', cmake)
        self.assertIn('+        runtime/src/hle_fiber.cpp runtime/src/fiber_context_linux.S)', cmake)

    def test_overlay_applies_after_series_macos(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not (reference / '.git').exists():
            self.skipTest('private pinned upstream reference unavailable')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source'
            runtime.prepare_source(reference, source, [PATCHES / n for n in acr.read_series(PATCHES / 'series.linux')])
            fiber = (source / FIBER).read_text()
            self.assertIn('prepare_entry(d->host,start+host_stack_bytes);', fiber)
            self.assertIn('(defined(__linux__) && !defined(__ANDROID__))', (source / 'runtime/src/kernel.cpp').read_text())
            self.assertIn('!plat::headless()', (source / 'runtime/src/nvn/nvn_vk.cpp').read_text())
            self.assertEqual((source / ASM).read_text(), added_file(OVERLAY, ASM).rstrip('\n') + '\n')
            runtime.prepare_source(reference, Path(d) / 'windows',
                                   [PATCHES / n for n in acr.read_series(PATCHES / 'series.windows')])


ALLOCATOR_HARNESS = r'''#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <set>
#include <tuple>
#include <vector>
#include "nvn_linux_staging.h"
using namespace nx::nvn;
using VkBuffer = uint64_t; using VkDeviceMemory = uint64_t;
constexpr uint64_t VK_NULL_HANDLE = 0, VK_WHOLE_SIZE = ~0ull;
constexpr unsigned VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO = 1, VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO = 2;
constexpr unsigned VK_BUFFER_USAGE_TRANSFER_SRC_BIT = 1;
constexpr unsigned VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT = 1, VK_MEMORY_PROPERTY_HOST_COHERENT_BIT = 2,
                   VK_MEMORY_PROPERTY_HOST_CACHED_BIT = 4, VK_SUCCESS = 0;
struct VkBufferCreateInfo { unsigned tag; uint64_t size = 0; unsigned usage = 0; };
struct VkMemoryRequirements { uint64_t size = 0; unsigned memoryTypeBits = 3; };
struct VkMemoryAllocateInfo { unsigned tag; uint64_t allocationSize = 0; unsigned memoryTypeIndex = 0; };
struct VkPhysicalDeviceMemoryProperties { unsigned memoryTypeCount = 2; struct { unsigned propertyFlags; } memoryTypes[2]{{3},{7}}; };
struct Upload { uint64_t buffer, offset; uint8_t* ptr; };
std::mutex g_grave_lock;
uint64_t g_submitted = 4, sequence = 10, requested = 0;
std::vector<std::tuple<uint64_t,VkBuffer,VkDeviceMemory>> g_staging;
std::set<uint64_t> buffers, memories;
std::vector<unsigned> types;
unsigned fail = 0, allowed_types = 3; bool cached_exists = true, hard_fail = false;
uint8_t byte;
unsigned vk_device() { return 1; } unsigned vk_physical() { return 1; }
unsigned p_vkCreateBuffer(unsigned, const VkBufferCreateInfo* bi, void*, VkBuffer* b) {
    requested = bi->size; *b = ++sequence; buffers.insert(*b); return 0;
}
void p_vkGetBufferMemoryRequirements(unsigned, VkBuffer, VkMemoryRequirements* r) { r->size = requested + 4096; r->memoryTypeBits = allowed_types; }
void p_vkGetPhysicalDeviceMemoryProperties(unsigned, VkPhysicalDeviceMemoryProperties* p) {
    *p = {}; if (!cached_exists) p->memoryTypes[1].propertyFlags = 3;
}
unsigned memory_type(unsigned, unsigned) { return 0; }
unsigned p_vkAllocateMemory(unsigned, const VkMemoryAllocateInfo* ai, void*, VkDeviceMemory* m) {
    types.push_back(ai->memoryTypeIndex);
    if (hard_fail || (fail == 1 && ai->memoryTypeIndex == 1)) { *m = 999999; return 1; }
    *m = ++sequence; memories.insert(*m); return 0;
}
unsigned p_vkBindBufferMemory(unsigned, VkBuffer, VkDeviceMemory, uint64_t) {
    return fail == 2 && types.back() == 1;
}
unsigned p_vkMapMemory(unsigned, VkDeviceMemory, uint64_t, uint64_t, unsigned, void** ptr) {
    if (fail == 3 && types.back() == 1) return 1; *ptr = &byte; return 0;
}
void p_vkUnmapMemory(unsigned, VkDeviceMemory) {}
void p_vkDestroyBuffer(unsigned, VkBuffer b, void*) { assert(buffers.erase(b) == 1); }
void p_vkFreeMemory(unsigned, VkDeviceMemory m, void*) { assert(memories.erase(m) == 1); }
Upload upload_alloc(uint64_t, uint64_t) { return {999,0,nullptr}; }
@ALLOCATOR@
void release_legacy() {
    for (auto [serial,b,m] : g_staging) { assert(serial == 5); p_vkDestroyBuffer(1,b,nullptr); p_vkFreeMemory(1,m,nullptr); }
    g_staging.clear(); assert(buffers.empty() && memories.empty());
}
int main() {
    setenv("NX_LINUX_STAGING_CACHED","1",1); setenv("NX_LINUX_STAGING_POOL","0",1);
    auto a = linux_staging_alloc(64); assert(a.ptr && types.back() == 1); release_legacy();
    cached_exists = false; types.clear(); a = linux_staging_alloc(64);
    assert(a.ptr && types == std::vector<unsigned>{0}); release_legacy(); cached_exists = true;
    allowed_types = 1; types.clear(); a = linux_staging_alloc(64);
    assert(a.ptr && types == std::vector<unsigned>{0}); release_legacy(); allowed_types = 3;
    for (fail = 1; fail <= 3; ++fail) {
        types.clear(); a = linux_staging_alloc(64);
        assert(a.ptr && types == (std::vector<unsigned>{1,0})); release_legacy();
    }
    fail = 0; hard_fail = true; a = linux_staging_alloc(64);
    assert(a.buffer == 999 && buffers.empty() && memories.empty()); hard_fail = false;
    setenv("NX_LINUX_STAGING_POOL","1",1);
    a = linux_staging_alloc(64); auto b = linux_staging_alloc(128);
    assert(a.buffer != b.buffer && g_linux_staging.pending_count() == 2);
    g_linux_staging.retire(4,linux_staging_dispose);
    assert(g_linux_staging.retained_bytes() == 0);
    g_linux_staging.retire(5,linux_staging_dispose);
    assert(g_linux_staging.retained_bytes() == 64 + 128 + 8192);
    auto c = linux_staging_alloc(64); assert(c.buffer == a.buffer);
    auto e = linux_staging_alloc(65); assert(e.buffer == b.buffer);
    assert(g_linux_staging.retained_bytes() == 0);
    return 0;
}
'''


class LinuxStagingTest(unittest.TestCase):
    def test_staging_additions_preprocess_to_nothing_on_other_hosts(self):
        compiler = shutil.which('clang++') or shutil.which('c++')
        if not compiler:
            self.skipTest('C++ preprocessor unavailable')
        part = OVERLAY.read_text().split('+++ b/runtime/src/nvn/nvn_frames.cpp\n', 1)[1].split('\ndiff --git ', 1)[0]
        additions = '\n'.join(line[1:] for line in part.splitlines() if line.startswith('+'))
        for definitions in (['-D_WIN32=1', '-D_M_X64=1'], ['-D__APPLE__=1', '-D__aarch64__=1'],
                            ['-D__linux__=1', '-D__ANDROID__=1']):
            result = subprocess.run([compiler, '-E', '-P', '-x', 'c++', '-undef', *definitions, '-'],
                                    input=additions, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '', definitions)

    def test_allocator_cached_fallback_failure_cleanup_and_retirement(self):
        cxx = shutil.which('clang++') or shutil.which('c++')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        body = added_file(OVERLAY, 'runtime/src/nvn/nvn_frames.cpp')
        start = body.index('struct LinuxStaging {')
        body = body[start:body.index('\n#endif', start)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'nvn_linux_staging.h').write_text(added_file(OVERLAY, 'runtime/src/nvn/nvn_linux_staging.h'))
            source = root / 'allocator.cpp'
            source.write_text(ALLOCATOR_HARNESS.replace('@ALLOCATOR@', body))
            exe = root / 'allocator'
            result = subprocess.run([cxx, '-std=c++20', '-O2', '-Wall', '-Wextra', str(source), '-o', str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_retirement_ownership_best_fit_and_actual_allocation_bounds(self):
        cxx = shutil.which('clang++') or shutil.which('c++')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'nvn_linux_staging.h').write_text(added_file(OVERLAY, 'runtime/src/nvn/nvn_linux_staging.h'))
            source = root / 'pool.cpp'
            source.write_text(r'''#include <cassert>
#include <set>
#include "nvn_linux_staging.h"
using Pool = nx::nvn::RetiredStaging<unsigned>;
int main() {
    Pool p; unsigned a = 0; std::set<unsigned> disposed;
    auto dispose = [&](unsigned id) { assert(disposed.insert(id).second); };
    p.submit(4, 64, 4096, 1); p.submit(5, 96, 8192, 2);
    p.retire(3, dispose); assert(!p.acquire(64, a)); assert(p.pending_count() == 2);
    p.retire(4, dispose); assert(p.pending_count() == 1); assert(p.retained_bytes() == 4096);
    // Accounting uses allocation size, but fitting uses buffer size.
    assert(!p.acquire(65, a)); assert(!p.acquire(16, a));
    assert(p.acquire(64, a) && a == 1); assert(!p.acquire(64, a));
    p.submit(7, 64, 4096, 1); p.retire(5, dispose);
    assert(p.acquire(80, a) && a == 2); p.submit(8, 96, 8192, 2);
    p.retire(6, dispose); assert(!p.acquire(64, a));
    p.retire(8, dispose); assert(p.acquire(64, a) && a == 1);
    assert(p.acquire(64, a) && a == 2); assert(p.retained_bytes() == 0);
    p.submit(9, Pool::max_bytes + 1, Pool::max_bytes + 1, 3);
    p.retire(9, dispose); assert(disposed.count(3));
    for (unsigned i = 0; i < 40; ++i) p.submit(10, 1, 1, 100 + i);
    p.retire(9, dispose); assert(p.pending_count() == 40);
    p.retire(10, dispose); assert(p.retained_bytes() == Pool::max_buffers);
    assert(disposed.size() == 9);
    Pool large; large.submit(1, 1, Pool::max_bytes, 4); large.submit(1, 1, 1, 5);
    large.retire(1, dispose); assert(large.retained_bytes() == Pool::max_bytes); assert(disposed.count(5));
    assert(large.peak_bytes == Pool::max_bytes);
    return 0;
}
''')
            exe = root / 'pool'
            result = subprocess.run([cxx, '-std=c++20', '-O2', '-Wall', '-Wextra', str(source), '-o', str(exe)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LinuxFiberContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.asm = self.tmp / 'fiber_context_linux.S'
        self.asm.write_text(added_file(OVERLAY, ASM))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assembles_for_linux_x86_64_and_arm64(self):
        clang = shutil.which('clang')
        if not clang:
            self.skipTest('clang unavailable')
        for target, symbols in (('x86_64-linux-gnu', 2), ('aarch64-linux-gnu', 2)):
            obj = self.tmp / f'{target}.o'
            r = subprocess.run([clang, '--target=' + target, '-c', str(self.asm), '-o', str(obj)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(obj.read_bytes()[:4], b'\x7fELF')

    def test_first_entry_resume_and_preserved_state_on_linux(self):
        if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'aarch64'):
            self.skipTest('needs a Linux x86-64 or arm64 host')
        cxx = shutil.which('clang++') or shutil.which('c++')
        source = self.tmp / 'harness.cpp'
        source.write_text(HARNESS.replace('@BLOCK@', prepare_entry_block()))
        exe = self.tmp / 'harness'
        r = subprocess.run([cxx, '-std=c++20', '-O2', '-Wall', str(source), str(self.asm), '-o', str(exe)],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('PASS fiber: 1 entry, 4 resumes', r.stdout)


if __name__ == '__main__':
    unittest.main()
