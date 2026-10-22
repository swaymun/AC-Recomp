"""Apply the shipped desktop series and execute production cache/key/record helpers.

No game inputs or GPU are used. The pinned upstream reference and Vulkan headers
must already exist locally; these tests never download anything.
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
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime
import test_astral_texel_coalesce as previous

OVERLAY = 'astral-shader-cache.patch'
ORDER = (*previous.ORDER, OVERLAY)
# Shared render fixes close the stack before the Linux and Windows overlays.
NATIVE_ORDER = (*ORDER, 'astral-render-fix.patch', 'astral-depth-fidelity.patch')
# Windows adds opt-in memory diagnostics before the performance dependencies.
WINDOWS_ORDER = (*NATIVE_ORDER, 'astral-linux.patch', 'windows-native.patch',
    'astral-windows.patch', 'astral-windows-desktop.patch', 'astral-windows-mem.patch',
    'astral-windows-perf.patch', 'astral-windows-resident.patch',
    'astral-windows-writeback.patch', 'astral-windows-replay.patch', 'astral-windows-stutter.patch')


CODEC = r'''
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include "nvn_shader_cache.h"
#if defined(_WIN32)
namespace nx::plat {
FILE* fopen_utf8(const std::string& path, const char* mode) {
    auto wide = std::filesystem::u8path(path).wstring();
    return _wfopen(wide.c_str(), std::wstring(mode, mode + std::strlen(mode)).c_str());
}
}
#endif
using namespace nx::nvn;
int main() {
    const std::string unicode = "cache-\xe9\x9b\xaa-\xc3\xa9.bin";
    const std::string key = "runtime-A:driver-A:uuid-A:options-A";
    const std::string payload("\0opaque cache\xff", 14);
    auto bytes = shader_cache::encode(key, payload);
    std::string out;
    assert(shader_cache::decode(bytes, key, out) && out == payload);
    for (const auto& wrong : {"runtime-B:driver-A:uuid-A:options-A", "runtime-A:driver-B:uuid-A:options-A",
                             "runtime-A:driver-A:uuid-B:options-A", "runtime-A:driver-A:uuid-A:options-B"})
        assert(!shader_cache::decode(bytes, wrong, out) && out.empty());
    for (size_t n = 0; n < bytes.size(); ++n) {
        assert(!shader_cache::decode(bytes.substr(0, n), key, out));
        auto bad = bytes; bad[n] ^= 1;
        assert(!shader_cache::decode(bad, key, out));
    }
    assert(!shader_cache::decode(bytes + "junk", key, out));
    auto huge = bytes; for (int i = 12; i < 16; ++i) huge[i] = '\xff';
    assert(!shader_cache::decode(huge, key, out));
    assert(shader_cache::save("cache.bin", key, payload));
    assert(shader_cache::load("cache.bin", key, out) && out == payload);
    std::filesystem::create_directory("cache.bin.tmp"); // failed replacement preserves old file
    assert(!shader_cache::save("cache.bin", key, "replacement"));
    assert(shader_cache::load("cache.bin", key, out) && out == payload);
    std::filesystem::remove("cache.bin.tmp");
    assert(shader_cache::save("cache.bin", key, "new payload!!"));
    assert(shader_cache::load("cache.bin", key, out) && out == "new payload!!");
    { std::ofstream f("big.bin", std::ios::binary); f.seekp(shader_cache::max_payload + 4152); f.put('x'); }
    assert(!shader_cache::load("big.bin", key, out));
    assert(!shader_cache::load("missing.bin", key, out));
    assert(shader_cache::save(unicode, key, "first"));
    assert(shader_cache::save(unicode, key, "other"));
    assert(shader_cache::load(unicode, key, out) && out == "other");
    // Atomic replacement fails when the destination is a directory; it survives.
    std::filesystem::create_directory("blocked.bin");
    assert(!shader_cache::save("blocked.bin", key, payload));
    assert(std::filesystem::is_directory("blocked.bin"));
    std::cout << "PASS version, build/driver/UUID/options separation, every-byte corruption/truncation, bounds, atomic failure, same-size replacement\n";
}
'''

KEY = r'''
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <vector>
#include <set>
#include "nvn_shader_cache.h"
#include "platform.h"
#if defined(__APPLE__)
extern char** environ;
#endif
namespace nx::plat {
FILE* fopen_utf8(const std::string& path, const char* mode) { return std::fopen(path.c_str(), mode); }
int fseek64(FILE* f, int64_t n, int origin) {
#if defined(_WIN32)
    return _fseeki64(f,n,origin);
#else
    return fseeko(f,n,origin);
#endif
}
int64_t ftell64(FILE* f) {
#if defined(_WIN32)
    return _ftelli64(f);
#else
    return ftello(f);
#endif
}
}
namespace nx::nvn {
#if defined(__APPLE__)
char*** _NSGetEnviron() { return &environ; }
#endif
struct VkPhysicalDeviceProperties { uint32_t vendorID=1, deviceID=2, driverVersion=3, apiVersion=4; uint8_t pipelineCacheUUID[16]{}; };
constexpr size_t VK_UUID_SIZE = 16;
int vk_physical() { return 1; }
void p_vkGetPhysicalDeviceProperties(int, VkPhysicalDeviceProperties* p) {
    if (auto e = std::getenv("TEST_DRIVER")) p->driverVersion = std::atoi(e);
    if (auto e = std::getenv("TEST_UUID")) p->pipelineCacheUUID[0] = std::atoi(e);
}
struct utsname { char release[8] = "test"; char version[8] = "test"; };
int uname(utsname*) { return 0; }
int _NSGetExecutablePath(char* dest, uint32_t* n) {
    if (!dest) { *n = 15; return -1; }
    std::strcpy(dest, "executable.bin"); return 0;
}
@KEY@
}
int main() {
    std::cout << nx::nvn::shader_cache_key() << " " << nx::nvn::shader_cache_enabled() << "\n";
}
'''

RECORDS = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <set>
#include <iostream>
#include "nvn_pipeline.h"
#include "nvn_shader_cache.h"
namespace nx::nvn {
int pipeline_depth_mode() { return 1; }
bool shader_cache_enabled() { return true; }
namespace {
std::map<std::string, VkPipeline> g_recorded_pipelines;
std::set<std::string> g_records;
bool g_records_dirty = false;
@HELPERS@
}
}
using namespace nx::nvn;
int main() {
    ShaderInfo vs, fs;
    vs.hash = "0123456789abcdef"; vs.stage = ShaderStage::Vertex; vs.spirv = {0x07230203, 1};
    fs.hash = "fedcba9876543210"; fs.stage = ShaderStage::Fragment; fs.spirv = {0x07230203, 2};
    PipelineKey k{}; k.vs=&vs; k.fs=&fs; k.color_count=1; k.color_formats[0]=VK_FORMAT_R8G8B8A8_UNORM;
    auto bytes=graphics_record(k); WarmRecord r;
    assert(parse_record(bytes,r) && r.depth==1 && !r.compute && !r.key.vs && !r.key.fs && r.key.color_count==1);
    ShaderInfo clone=vs; k.vs=&clone;
    assert(graphics_record(k)==bytes); // process pointers never form the persistent identity
    k.depth.depth_write=1; assert(graphics_record(k)!=bytes); k.depth.depth_write=0;
    ShaderInfo changed=vs; changed.spirv.push_back(3); k.vs=&changed;
    assert(graphics_record(k)!=bytes);
    ShaderInfo shared=vs; shared.control.shared_size=16; k.vs=&shared;
    assert(graphics_record(k)!=bytes);
    k.vs=&vs; k.color_count=9; assert(!parse_record(graphics_record(k),r));
    k.color_count=1; k.attrib_count=17; assert(!parse_record(graphics_record(k),r));
    k.attrib_count=0; k.uw_x=std::nanf(""); assert(!parse_record(graphics_record(k),r));
    for (size_t n=0; n<bytes.size(); ++n) assert(!parse_record(bytes.substr(0,n),r));
    assert(!parse_record(bytes+"trailing",r));
    ShaderInfo cs; cs.hash="0011223344556677"; cs.stage=ShaderStage::Compute; cs.spirv={0x07230203};
    assert(parse_record(compute_record(&cs),r) && r.compute);
    cs.stage=ShaderStage::Vertex; // a new identity (not a previously cached shader pointer)
    ShaderInfo wrong=cs;
    assert(!parse_record(compute_record(&wrong),r));
    std::cout << "PASS graphics/compute records, pointer independence, SPIR-V/shared-size invalidation, counts, NaN, truncation, wrong stage\n";
}
'''


MOCK_CACHE = r'''
#include <cassert>
#include <cstdarg>
#include <cstdlib>
#include <iostream>
#include "nvn_shader_cache.h"
#include "nvn_vk.h"
#include "platform.h"
#include <filesystem>
namespace {
std::vector<size_t> initial_sizes;
std::string mode, driver_blob;
int data_queries = 0;
void properties(VkPhysicalDevice, VkPhysicalDeviceProperties* p) {
    *p = {}; p->vendorID = 0x106b; p->deviceID = 12; p->driverVersion = 42;
    p->pipelineCacheUUID[0] = 9;
}
VkResult create_cache(VkDevice, const VkPipelineCacheCreateInfo* ci, const VkAllocationCallbacks*, VkPipelineCache* cache) {
    initial_sizes.push_back(ci->initialDataSize);
    if (mode == "driver-reject" && ci->initialDataSize) return VK_ERROR_INITIALIZATION_FAILED;
    *cache = reinterpret_cast<VkPipelineCache>(uintptr_t(1)); return VK_SUCCESS;
}
VkResult get_data(VkDevice, VkPipelineCache, size_t* n, void* data) {
    ++data_queries;
    if (data) std::memcpy(data, driver_blob.data(), driver_blob.size());
    *n = driver_blob.size(); return VK_SUCCESS;
}
}
namespace nx {
void log(const char*, ...) {}
namespace vk {
PFN_vkGetPhysicalDeviceProperties p_vkGetPhysicalDeviceProperties = properties;
PFN_vkCreatePipelineCache p_vkCreatePipelineCache = create_cache;
PFN_vkGetPipelineCacheData p_vkGetPipelineCacheData = get_data;
}
namespace plat {
std::string data_root() { return "."; }
FILE* fopen_utf8(const std::string& p, const char* m) {
#if defined(_WIN32)
    return _wfopen(std::filesystem::u8path(p).c_str(),std::wstring(m,m+std::strlen(m)).c_str());
#else
    return std::fopen(p.c_str(), m);
#endif
}
int fseek64(FILE* f, int64_t n, int origin) {
#if defined(_WIN32)
    return _fseeki64(f,n,origin);
#else
    return fseeko(f,n,origin);
#endif
}
int64_t ftell64(FILE* f) {
#if defined(_WIN32)
    return _ftelli64(f);
#else
    return ftello(f);
#endif
}
}
namespace nvn {
VkDevice vk_device() { return VK_NULL_HANDLE; }
VkPhysicalDevice vk_physical() { return VK_NULL_HANDLE; }
void shader_records_save() {}
}
}
#include <nvn_pipeline_cache.cpp>
int main(int argc, char** argv) {
    assert(argc == 2); mode = argv[1];
    using namespace nx::nvn;
    auto key = shader_cache_key();
    auto path = "./pipelines_v1_" + key + ".bin";
    driver_blob.clear(); shader_cache::u32(driver_blob, 32); shader_cache::u32(driver_blob, 1);
    shader_cache::u32(driver_blob, 0x106b); shader_cache::u32(driver_blob, 12);
    driver_blob += std::string(16, '\0'); driver_blob[16] = 9; driver_blob += "driver-private-data";
    auto bytes = shader_cache::encode(key + ":vulkan", driver_blob);
    if (mode == "corrupt") bytes.back() ^= 1;
    if (mode == "wrong-header") {
        auto bad = driver_blob; bad[8] = 0;
        bytes = shader_cache::encode(key + ":vulkan", bad);
    }
    if (mode != "cold") { FILE* f=std::fopen(path.c_str(),"wb"); assert(f); std::fwrite(bytes.data(),1,bytes.size(),f); std::fclose(f); }
    else std::remove(path.c_str());
    assert(pipeline_cache() != VK_NULL_HANDLE);
    if (mode == "warm" || mode == "driver-reject") assert(initial_sizes[0] == driver_blob.size());
    else assert(initial_sizes[0] == 0);
    if (mode == "driver-reject") assert(initial_sizes.size() == 2 && initial_sizes[1] == 0);
    note_pipeline_created(1); pipeline_cache_save();
    std::string loaded; assert(shader_cache::load(path,key+":vulkan",loaded) && loaded==driver_blob);
    int queried = data_queries;
    pipeline_cache_save(); assert(data_queries==queried); // unchanged: no expensive driver serialization
    driver_blob.back() ^= 1; // same size, different content: must be persisted
    note_pipeline_created(1); pipeline_cache_save();
    assert(shader_cache::load(path,key+":vulkan",loaded) && loaded==driver_blob);
    std::cout << "PASS Vulkan " << mode << ": load validation, driver fallback, dirty-only serialization, same-size update\n";
}
'''


class ShaderCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute(): common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent / '.local/owner-build/work/upstream/SuperMarioWonderRecomp')))
        cls.reference = reference
        if not (reference / '.git').exists():
            raise unittest.SkipTest('existing pinned runtime required (NVN_REFERENCE); no downloads')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name)
        cls.source = cls.out / 'source'
        series = [line.split('#')[0].strip() for line in (ROOT / 'runtime/patches/series.macos').read_text().splitlines()]
        cls.series = [p for p in series if p]
        assert cls.series == list(NATIVE_ORDER), 'shipped Mac series differs from composed overlay tests'
        prepare_runtime.prepare_source(reference, cls.source,
            [ROOT / 'runtime/patches' / p for p in ORDER[:-1]])
        cls.before = {n: (cls.source / n).read_text() for n in ('runtime/src/frame_stats.cpp',
            'runtime/src/nvn/nvn_pipeline.cpp', 'runtime/src/nvn/nvn_pipeline_cache.cpp', 'runtime/src/nvn/nvn_vk.cpp')}
        for patch in cls.series[len(ORDER) - 1:]:
            path = ROOT / 'runtime/patches' / patch
            subprocess.run(['git', '-C', str(cls.source), 'apply', '--check', str(path)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(cls.source), 'apply', str(path)], check=True, capture_output=True)
            if patch == OVERLAY:
                cls.cache_only = {n: (cls.source / n).read_text() for n in cls.before}
        cls.src = cls.source / 'runtime/src'
        cls.cxx = os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
        if not cls.cxx: raise RuntimeError('C++ compiler required')
        cls.includes = ['-I', str(cls.src / 'nvn'), '-I', str(cls.src), '-I', str(cls.source / 'runtime/include'),
                        '-I', os.environ.get('NVN_VULKAN_INCLUDE', '/opt/homebrew/include')]
        cls.shader_sources = [str(cls.src / 'nvn/nvn_shaders.cpp'), str(cls.src / 'nvn/nvn_spirv_reflect.cpp')]

    def build(self, name, code):
        src = self.out / (name + '.cpp'); src.write_text(code)
        exe = self.out / (name + ('.exe' if os.name == 'nt' else ''))
        run = subprocess.run([self.cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-function', '-Wno-unused-variable', '-Wno-missing-field-initializers', '-DNX_SHADERS_STANDALONE=1',
            '-D_CRT_SECURE_NO_WARNINGS', '-D_SILENCE_CXX20_U8PATH_DEPRECATION_WARNING',
            *(['-Wno-cast-function-type-mismatch'] if os.name == 'nt' else []),
            *self.includes, str(src), *self.shader_sources, '-o', str(exe)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return exe

    def run_fixture(self, exe, env=None):
        run = subprocess.run([str(exe)], cwd=self.out, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout.strip()

    def test_prewarm_runs_at_device_boot_before_first_present(self):
        text = (self.src / 'nvn/nvn_vk.cpp').read_text()
        init = text.split('bool init() {', 1)[1].split('// The window', 1)[0]
        self.assertLess(init.index('g_ready = true;'), init.index('shader_prewarm();'))
        self.assertLess(init.index('shader_prewarm();'), init.rindex('return true;'))

    def test_headless_telemetry_hook_precedes_early_return(self):
        text = (self.src / 'nvn/nvn_vk.cpp').read_text().split('void present_headless(uint64_t texture) {', 1)[1]
        self.assertLess(text.index('plat::frame_presented();'), text.index('if (!due && !every) return;'))
        self.assertIn('if (std::getenv("NX_FRAME_LOG")) plat::frame_presented();', text)
        present = text.split('void gpu_present(uint64_t texture, const int32_t* crop) {', 1)[1]
        self.assertLess(present.index('std::lock_guard lk(g_gpu);'), present.index('static uint64_t last = 0, index = 0;'))
        self.assertLess(present.index('if (!init()) return;'), present.index('static uint64_t last = 0, index = 0;'))
        self.assertLess(present.index('static uint64_t last = 0, index = 0;'),
                        present.index('if (plat::headless()) return present_headless(texture);'))


    def test_linux_stack_applies_in_order(self):
        series = [line.split('#')[0].strip() for line in
                  (ROOT / 'runtime/patches/series.linux').read_text().splitlines()]
        series = [p for p in series if p]
        self.assertEqual(series, [*NATIVE_ORDER, 'astral-linux.patch'])
        prepare_runtime.prepare_source(self.reference, self.out / 'linux-source',
                                       [ROOT / 'runtime/patches' / p for p in series])

    @unittest.skipUnless(sys.platform == 'darwin', 'host SDK preload is Apple-specific')
    def test_unsupported_platform_strict_translation_units_are_unchanged(self):
        # Exercise the non-Apple guards on the host compiler. This is a compile/
        # preprocessing regression, not a Linux or Windows SDK/build claim.
        # Load the host C++ SDK before changing runtime platform selection: Apple
        # libc++ itself cannot be compiled with its target macro undefined.
        prelude = self.out / 'non-apple.h'
        headers = ('algorithm array atomic chrono cmath cstdio cstdlib cstring deque filesystem '
                   'fstream functional map memory mutex set sstream string thread unordered_map vector')
        prelude.write_text(''.join(f'#include <{h}>\n' for h in headers.split()) + '#undef __APPLE__\n#undef __linux__\n#undef _WIN32\n')
        flags = ['-include', str(prelude), '-DNX_ASTRAL_STRICT=1']
        for name, before in self.before.items():
            with self.subTest(source=name):
                path = self.source / name
                original = self.out / ('non-apple-' + path.name)
                original.write_text(before)
                command = [self.cxx, '-std=c++20', *flags, '-I', str(path.parent), *self.includes]
                run = subprocess.run([*command, '-fsyntax-only', str(path)], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                outputs = []
                cache_only = self.out / ('cache-only-' + path.name)
                cache_only.write_text(self.cache_only[name])
                for source in (original, cache_only):
                    run = subprocess.run([*command, '-E', '-P', str(source)], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    outputs.append(run.stdout)
                self.assertEqual(*outputs, name)

    def test_pc_platform_paths_and_persistence_contract(self):
        header = (self.src / 'nvn/nvn_shader_cache.h').read_text()
        cache = (self.src / 'nvn/nvn_pipeline_cache.cpp').read_text()
        self.assertIn('plat::fopen_utf8(path, "rb")', header)
        self.assertIn('MoveFileExW(temporary.c_str(), destination.c_str()', header)
        self.assertIn('MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH', header)
        self.assertIn('std::rename(tmp.c_str(), path.c_str())', header)
        self.assertIn('GetModuleFileNameW', cache)
        self.assertIn('"/proc/self/exe"', cache)
        self.assertIn('p.pipelineCacheUUID', cache)
        # The GPU-owned timing window persists both products; _exit cannot lose
        # an entire session merely because a destructor never runs.
        window = cache.split('void creation_log(uint64_t frames)', 1)[1]
        self.assertLess(window.index('shader_records_save();'), window.index('pipeline_cache_save();'))

    def test_primary_log_retains_statistics_and_console_is_explicit(self):
        loader = (self.src / 'loader.cpp').read_text()
        function = loader.split('void log(const char* fmt, ...) {', 1)[1].split('\nvoid fatal(', 1)[0]
        code = r'''#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cstring>
#include <mutex>
#include <string>
#include <filesystem>
#include "platform.h"
namespace nx {
FILE* g_log_file = nullptr;
std::mutex g_log_lock;
unsigned console_lines = 0;
namespace plat {
std::string data_root() { return "."; }
void log_line(const char*) { ++console_lines; }
FILE* fopen_utf8(const std::string& path, const char* mode) {
#if defined(_WIN32)
    return _wfopen(std::filesystem::u8path(path).c_str(),std::wstring(mode,mode+std::strlen(mode)).c_str());
#else
    return std::fopen(path.c_str(),mode);
#endif
}
}
void log(const char* fmt, ...) {@FUNCTION@
}
int main() {
    nx::log("statistics frames=%d",300);
    nx::log("statistics pipelines=%d",7);
    std::printf("%u",nx::console_lines);
}
'''
        exe = self.build('primary-log', '#define NX_ASTRAL_STRICT 1\n' + code.replace('@FUNCTION@', function))
        env = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
        for switch, expected in [(None, '0'), ('0', '0'), ('1', '2'), ('yes', '0')]:
            settings = dict(env, NX_LOG=str(self.out / 'statistics.log'))
            if switch is not None: settings['NX_CONSOLE_LOG'] = switch
            self.assertEqual(self.run_fixture(exe, settings), expected)
            self.assertEqual((self.out / 'statistics.log').read_text(),
                             'statistics frames=300\nstatistics pipelines=7\n')
        self.assertEqual(self.run_fixture(exe, dict(env, NX_LOG=str(self.out / 'absent' / 'log'))), '2')
        if sys.platform == 'linux':
            self.assertEqual(self.run_fixture(exe, dict(env, NX_LOG='/dev/full', NX_REEXEC='1')), '2')
        self.assertEqual(self.run_fixture(exe, dict(env, NX_LOG=str(self.out / 'statistics.log'),
                         NX_WIN_ASYNC_CONSOLE='1')), '2' if os.name == 'nt' else '0')

    def test_native_prewarm_policy_preserves_apple_windows_and_linux_opt_in(self):
        text = (self.src / 'nvn/nvn_pipeline.cpp').read_text()
        prefix = text.split('void shader_prewarm() {', 1)[1].split('// Called under GPU ownership', 1)[0]
        code = r'''#include <cstdio>
#include <cstdlib>
bool g_prewarming = false;
bool shader_cache_enabled() { return true; }
int warmed = 0;
void shader_prewarm() {@PREFIX@
    ++warmed;
}
int main() { shader_prewarm(); std::printf("%d", warmed); }
'''.replace('@PREFIX@', prefix)
        exe = self.build('prewarm-policy', code)
        env = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
        self.assertEqual(self.run_fixture(exe, env), '0' if sys.platform == 'linux' else '1')
        self.assertEqual(self.run_fixture(exe, dict(env, NX_SHADER_PREWARM='0')), '0')
        self.assertEqual(self.run_fixture(exe, dict(env, NX_SHADER_PREWARM='1')), '1')

    def test_desktop_cache_guard_excludes_android(self):
        text = (self.src / 'nvn/nvn_pipeline_cache.cpp').read_text()
        guard = next(line for line in text.splitlines() if line.startswith('#if ') and
                     'defined(__APPLE__)' in line and 'defined(__linux__)' in line)
        for defines, expected in [(('__APPLE__',), '1'), (('_WIN32',), '1'),
                                  (('__linux__',), '1'), (('__linux__', '__ANDROID__'), '0'), ((), '0')]:
            code = '#undef __APPLE__\n#undef _WIN32\n#undef __linux__\n#undef __ANDROID__\n#define NX_ASTRAL_STRICT 1\n'
            code += ''.join('#define '+name+' 1\n' for name in defines)
            code += guard+'\nint cache_enabled = 1;\n#else\nint cache_enabled = 0;\n#endif\n'
            path = self.out / 'target-guard.cpp'; path.write_text(code)
            run = subprocess.run([self.cxx, '-E', '-P', str(path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('int cache_enabled = '+expected+';', run.stdout)

    def test_codec_and_disk_failures(self):
        output = self.run_fixture(self.build('codec', CODEC))
        self.assertIn('PASS version', output)

    def test_real_key_function_changes_for_build_driver_uuid_and_settings(self):
        text = (self.src / 'nvn/nvn_pipeline_cache.cpp').read_text()
        key = text[text.index('const std::string& shader_cache_key()'):text.index('\n#endif\n\nVkPipelineCache')]
        exe = self.build('key', KEY.replace('@KEY@', key))
        env = {k: v for k, v in os.environ.items() if not k.startswith(('NX_', 'MVK_', 'TEST_'))}
        binary = self.out / 'executable.bin'; binary.write_bytes(b'build-A')
        baseline = self.run_fixture(exe, env)
        self.assertTrue(baseline.endswith(' 1'))
        for setting, value in [('TEST_DRIVER', '42'), ('TEST_UUID', '9'), ('NX_INT_ATTRIBS', '0'),
                               ('NX_DYNAMIC_UBO', '1')]:
            with self.subTest(setting=setting): self.assertNotEqual(self.run_fixture(exe, dict(env, **{setting: value})), baseline)
        for setting in ('MVK_CONFIG_FAST_MATH_ENABLED', 'MVK_CONFIG_NEW_COMPILER_OPTION'):
            result = self.run_fixture(exe, dict(env, **{setting: '1'}))
            if sys.platform == 'darwin': self.assertNotEqual(result, baseline)
            else: self.assertEqual(result, baseline, 'MoltenVK options are Apple-only')
        for setting in ('NX_EXACT_EQUAL', 'NX_FRAG_OUTPUT_MASK', 'NX_HALF_BITS', 'NX_VERTEX_PRECISE',
                        'NX_REPLAY_DYNAMIC', 'NX_REPLAY_KEYS'):
            result = self.run_fixture(exe, dict(env, **{setting: '1'}))
            if os.name == 'nt': self.assertNotEqual(result, baseline)
            else: self.assertEqual(result, baseline, 'Windows fidelity/replay settings are Windows-only')
        if sys.platform == 'darwin':
            binary.write_bytes(b'build-B')
            self.assertNotEqual(self.run_fixture(exe, env), baseline)
        else:
            changed = self.out / ('changed' + exe.suffix)
            shutil.copy2(exe, changed)
            with changed.open('ab') as f: f.write(b'build-B')
            self.assertNotEqual(self.run_fixture(changed, env), baseline)
        for setting in ('NX_SHADER_CACHE', 'NX_SPIRV_TOOL', 'NX_SPIRV_OPT'):
            self.assertTrue(self.run_fixture(exe, dict(env, **{setting: '0'})).endswith(' 0'))

    def test_production_record_keys_and_validation(self):
        text = (self.src / 'nvn/nvn_pipeline.cpp').read_text()
        helpers = text[text.index('std::string shader_identity('):text.index('const ShaderInfo* warm_shader(')]
        self.assertIn('PASS graphics', self.run_fixture(self.build('records', RECORDS.replace('@HELPERS@', helpers))))

    def test_production_vulkan_cache_with_fake_driver(self):
        # Compile the complete production cache TU against a deterministic fake Vulkan driver.
        exe = self.build('mock-cache', '#define NX_ASTRAL_STRICT 1\n' + MOCK_CACHE)
        for mode in ('cold', 'warm', 'corrupt', 'wrong-header', 'driver-reject'):
            run = subprocess.run([str(exe), mode], cwd=self.out, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS Vulkan ' + mode, run.stdout)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac-profile compilation needs the Apple SDK')
    def test_changed_translation_units_compile_and_default_preprocessing(self):
        for name, before in self.before.items():
            path = self.source / name
            run = subprocess.run([self.cxx, '-std=c++20', '-fsyntax-only', '-DNX_ASTRAL_STRICT=1',
                *self.includes, str(path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            # Compare the real default preprocessor output before/after the overlay.
            original = self.out / path.name
            original.write_text(before)
            def preprocess(p):
                r = subprocess.run([self.cxx, '-std=c++20', '-E', '-P', '-I', str(path.parent),
                    *self.includes, str(p)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r.stdout
            cache_only = self.out / ('cache-only-default-' + path.name)
            cache_only.write_text(self.cache_only[name])
            self.assertEqual(preprocess(original), preprocess(cache_only), name)


if __name__ == '__main__': unittest.main()
