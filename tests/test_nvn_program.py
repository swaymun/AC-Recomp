"""CPU regression of the real NVN program, record/replay and draw-selection code.

Uses the pinned public runtime and existing Vulkan headers; no game or GPU.
Draw/dispatch prefixes are compiled verbatim up to their first GPU-dependent work.
Full changed translation units also receive a compiler syntax check.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_runtime import PIN

FIXTURE = r'''
#include <cassert>
#include <iostream>
#include <stdexcept>
#include "nvn/nvn_draw_state.h"
namespace nx {
std::map<std::string,HleFn> hooks;
HleRegistrar::HleRegistrar(const char* n,HleFn f) {hooks[n]=f;}
void log(const char*,...) {}
namespace plat { uint64_t monotonic_ns() {throw std::runtime_error("unexpected clock");} }
namespace nvn {
ObjectsLock& objects_lock() {static ObjectsLock v;return v;}
std::unordered_map<uint64_t,std::unique_ptr<Object>>& objects() {static std::unordered_map<uint64_t,std::unique_ptr<Object>> v;return v;}
Object* find_object(uint64_t k,uint64_t) {auto i=objects().find(k);return i==objects().end()?nullptr:i->second.get();}
bool resolve_cache_on() {return false;}
void defer_object(std::unique_ptr<Object>) {}
MemoryPool pool;
MemoryPool* pool_at_gpu(uint64_t a,uint64_t* off) {
 if (a<0x100000000ULL || a-0x100000000ULL>=pool.size)return nullptr;
 *off=a-0x100000000ULL;return &pool;
}
std::map<uint64_t,const ShaderInfo*> synthetic_cache;
const ShaderInfo* shader_for(uint64_t code,uint64_t control) {
 assert(code==control); // synthetic identity mapping, verifies the production pointer plumbing
 auto i=synthetic_cache.find(code);return i==synthetic_cache.end()?nullptr:i->second;
}
Cmd recorded{Cmd::BindProgram};
void record(uint64_t,Cmd c,const void*,size_t) {recorded=c;}
uint64_t real_proc(CPU&,const char*) {throw std::runtime_error("unexpected guest driver");}
uint64_t guest_call(CPU&,uint64_t,std::initializer_list<uint64_t>) {throw std::runtime_error("unexpected guest call");}
uint64_t scratch(CPU&,size_t) {throw std::runtime_error("unexpected scratch");}
const DeferredValues* current_deferred() {return nullptr;}
uint64_t submit_start_ns() {throw std::runtime_error("unexpected submit");}
void dispatch_call(VkCommandBuffer,const Cmd&) {throw std::runtime_error("unexpected GPU dispatch");}
bool draw_call(VkCommandBuffer,const Targets&,uint32_t,bool,const Cmd&) {throw std::runtime_error("unexpected GPU draw");}
namespace replay {
State g_state;
Stats g_stats;
const uint8_t* guest_bytes(uint64_t) {throw std::runtime_error("unexpected GPU memory");}
void dedup_invalidate(const uint8_t*,uint64_t) {throw std::runtime_error("unexpected upload");}
void written_cpu_write(const uint8_t*,uint64_t) {throw std::runtime_error("unexpected write");}
bool raster_command(const Cmd&) {throw std::runtime_error("unexpected raster");}
}
}
}
#include "nvn/nvn_program.cpp"
#include "nvn/nvn_state.cpp"
#include "nvn/nvn_draw_state.cpp"
using namespace nx;
using namespace nx::nvn;
using namespace nx::nvn::replay;
const ShaderInfo* expected_vs=nullptr;
const ShaderInfo* expected_fs=nullptr;
bool graphics_prefix() {
@DRAW_PREFIX@
 assert(vs==expected_vs && fs==expected_fs);
 return true; // only reached after the actual production CPU rejection boundary
}
const ShaderInfo* compute_prefix() {
@COMPUTE_PREFIX@
 return cs;
}
void bind(uint64_t program,uint32_t mask) {
 CPU c{};c.x[0]=0x900;c.x[1]=program;c.x[2]=0xfeedface00000000ULL|mask;
 hooks.at("nvnCommandBufferBindProgram")(c);
 assert(recorded.op==Cmd::BindProgram && recorded.a[0]==program && recorded.mask==mask);
 draw_command(VK_NULL_HANDLE,recorded,CmdList{},Targets{});
}
void init(uint64_t program,const std::vector<uint64_t>& offsets,bool ext=false) {
 CPU c{};c.x[0]=program;hooks.at("nvnProgramInitialize")(c);assert(c.x[0]==1);
 std::vector<uint64_t> entries;
 for(auto off:offsets) {entries.push_back(0x100000000ULL+off);entries.push_back(pool.memory+off);if(ext)entries.push_back(0);}
 c.x[0]=program;c.x[1]=offsets.size();c.x[2]=uint64_t(entries.data());
 hooks.at(ext?"nvnProgramSetShadersExt":"nvnProgramSetShaders")(c);assert(c.x[0]==1);
}
void clear_state() {g_state=State{};g_stats=Stats{};}
int main() {
 uint8_t memory[64]{};pool.memory=uint64_t(memory);pool.size=sizeof memory;
 ShaderInfo vs{},fs{},cs{},vs2{};vs.stage=vs2.stage=ShaderStage::Vertex;
 fs.stage=ShaderStage::Fragment;cs.stage=ShaderStage::Compute;
 synthetic_cache={{pool.memory,&vs},{pool.memory+8,&fs},{pool.memory+16,&cs},{pool.memory+24,&vs2}};
 init(0x100,{0});init(0x200,{8},true);init(0x300,{16});init(0x400,{0,8});init(0x500,{24});
 init(0x600,{40}); // untranslated input leaves an empty program, never a success shader
 assert(program_shaders(0x600)->empty());assert(!program_shaders(0xbad));
 expected_vs=&vs;expected_fs=&fs;
 bind(0x100,1);bind(0x200,2);
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
 assert(graphics_prefix());assert(g_stats.no_vertex==0);
 bind(0x300,32);assert(compute_prefix()==&cs);assert(graphics_prefix());
 bind(0x400,32);assert(!compute_prefix());assert(graphics_prefix()); // graphics stages cannot masquerade as compute
 bind(0,32);assert(!compute_prefix());assert(graphics_prefix());
 bind(0x300,32);assert(compute_prefix()==&cs);
 bind(0x500,0);assert(graphics_prefix()); // empty masks preserve every stage
 bind(0x500,0x80000000);assert(graphics_prefix()); // unknown bits cannot replace a stage
 bind(0x500,1);expected_vs=&vs2;assert(graphics_prefix());assert(compute_prefix()==&cs);
 bind(0,2);expected_fs=nullptr;assert(graphics_prefix()); // selective null unbind
 bind(0x400,3);expected_vs=&vs;expected_fs=&fs;assert(graphics_prefix());
 bind(0x200,1);assert(!graphics_prefix()); // wrong reflected stage: no vertex fallback
 bind(0x400,3);bind(0x600,1);assert(!graphics_prefix()); // missing cache cannot retain old VS
 bind(0xbad,1);assert(!graphics_prefix()); // nonexistent program cannot retain old VS
 bind(0,3);assert(!graphics_prefix());assert(g_stats.no_program>0);
 clear_state();bind(0x100,1);bind(0x200,2);
 CPU c{};c.x[0]=0x100;hooks.at("nvnProgramFinalize")(c);
 assert(!graphics_prefix()); // resolve objects at replay; no dangling cached stage pointer
 init(0x100,{24});expected_vs=&vs2;assert(graphics_prefix());
 clear_state();assert(!graphics_prefix());assert(!compute_prefix());
 std::cout<<"PASS patched Astral production: split-stage bind, draw rejection, selective replacement/unbind, compute isolation, missing/wrong/finalized program, reset\n";
#else
 assert(!graphics_prefix());assert(g_stats.no_vertex==1); // actual before failure
 bind(0x400,3);assert(graphics_prefix()); // inherited combined-program path
 bind(0x300,32);assert(compute_prefix()==&cs);
 bind(0,0);assert(!graphics_prefix());assert(g_stats.no_program==1);
 std::cout<<"PASS inherited production: split-stage sequence rejected no_vertex=1; combined program unchanged\n";
#endif
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NvnProgramTests(unittest.TestCase):
    def test_actual_production_before_after_and_default(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        repo = common.parent
        reference = Path(os.environ.get('NVN_REFERENCE', str(repo / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', str(repo / '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include')))
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required; no downloads')
        self.assertEqual(subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip(), PIN)
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out = ROOT / '.local/nvn-program-087' / ('verify-' + uuid.uuid4().hex)
        source = out / 'source'
        source.mkdir(parents=True)
        # Archive public runtime only. Never read or copy the reference's private directory.
        archive = subprocess.check_output(['git', '-C', str(reference), 'archive', PIN, 'runtime/include', 'runtime/src'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                self.assertFalse(member.issym() or member.islnk())
                self.assertTrue((member.name == 'runtime' or member.name.startswith('runtime/')) and '..' not in Path(member.name).parts)
            tar.extractall(source, filter='data')
        subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
        nvn = source / 'runtime/src/nvn'
        before = {p.name: digest(p) for p in nvn.iterdir() if p.name in ('nvn_draw.cpp', 'nvn_draw_state.cpp', 'nvn_draw_state.h', 'nvn_program.cpp', 'nvn_state.cpp')}
        patch = ROOT / 'runtime/patches/astral-nvn-program.patch'
        results = []
        for mode, flags in (('before-astral', ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1']),
                            ('after-astral', ['-DNX_ASTRAL_STRICT=1']), ('after-default', [])):
            if mode == 'after-astral':
                subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source, check=True, capture_output=True)
                subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True, capture_output=True)
                self.assertIn('stage_programs[kStages]', (nvn / 'nvn_draw_state.h').read_text())
            draw = (nvn / 'nvn_draw.cpp').read_text()
            # These exact CPU prefixes run without the rest of the GPU renderer.
            graphics = draw.split('bool draw(VkCommandBuffer cb,')[1].split('{', 1)[1].split('    std::vector<const ShaderInfo*> swapped;')[0]
            compute = draw.split('void dispatch(VkCommandBuffer cb, const Cmd& c) {')[1].split('    uint32_t x =')[0]
            # The production compute prefix returns void on a miss. Match that with a
            # void lambda, preserving its text, and expose its selected pointer.
            compute = 'const ShaderInfo* result=nullptr;\n[&]() {\n' + compute + '\nresult=cs;\n}();\nconst ShaderInfo* cs=result;'
            fixture = out / (mode + '.cpp')
            fixture.write_text(FIXTURE.replace('@DRAW_PREFIX@', graphics).replace('@COMPUTE_PREFIX@', compute))
            includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), '-I', str(vulkan)]
            binary = out / mode
            argv = [compiler, '-std=c++20', '-pthread', *flags, *includes, str(fixture), '-o', str(binary)]
            build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            (out / (mode + '-compile.log')).write_text(build.stdout + build.stderr)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            fixture_env = os.environ.copy()
            fixture_env.pop('NX_NO_COMPUTE', None)
            result = subprocess.run([str(binary)], cwd=out, env=fixture_env, capture_output=True, text=True, timeout=10)
            (out / (mode + '-result.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')
            results.append({'mode': mode, 'exit_code': result.returncode, 'output': result.stdout,
                            'fixture_sha256': digest(fixture), 'binary_sha256': digest(binary)})
        # Verify the whole changed production TUs with real declarations, beyond prefixes.
        for flags in (['-DNX_ASTRAL_STRICT=1'], []):
            for name in ('nvn_draw.cpp', 'nvn_draw_state.cpp'):
                check = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes,
                                        '-fsyntax-only', str(nvn / name)], capture_output=True, text=True, timeout=60)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        (out / 'receipt.json').write_text(json.dumps({'pin': PIN, 'before': before,
            'patch_sha256': digest(patch),
            'after': {name: digest(nvn / name) for name in before}, 'results': results,
            'limits': 'CPU production boundary and syntax checks only; shader cache adapter is synthetic; no game, GPU or native launch.'}, indent=2) + '\n')
        print('PASS full changed production TUs: Astral and default syntax checks')
        print('private receipt:', out / 'receipt.json')
        shutil.rmtree(source)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
