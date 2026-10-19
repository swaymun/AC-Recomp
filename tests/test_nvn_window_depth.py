"""CPU regression of the real nvnWindowGetCrop and NVN depth-mode code (astral-nvn-window-depth.patch).

The overlay is applied in the native overlay order on a fresh copy of the pinned public runtime. The changed
window/depth region of nvn_queue.cpp and the clip-control decision of nvn_pipeline.cpp are compiled verbatim with
synthetic object/texture adapters; the full changed translation units get syntax checks in both profiles, and the
default profile's preprocessed source must be identical to the unpatched one. No game, GPU or device is used.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime
from test_nvn_init import PATCHES

# Native (Mac/Linux) overlay order: the cumulative stack, then the NVN, fiber and service overlays, then this one.
NATIVE_ORDER = (*PATCHES, 'astral-nvn-texture.patch', 'astral-nvn-program.patch', 'astral-fiber.patch',
                'astral-hwopus.patch', 'astral-prepo.patch', 'astral-fs-commit.patch')
OVERLAY = 'astral-nvn-window-depth.patch'
CHANGED = ('nvn_queue.cpp', 'nvn_pipeline.cpp')

FIXTURE = r'''
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include "nvn/nvn.h"
#include "nvn/nvn_ultrawide.h"
namespace nx {
std::map<std::string,HleFn> hooks;
HleRegistrar::HleRegistrar(const char* n,HleFn f) {hooks[n]=f;}
void log(const char*,...) {}
[[noreturn]] void fatal(const char* f,...) {throw std::runtime_error(f);}
namespace nvn {
ObjectsLock& objects_lock() {static ObjectsLock v;return v;}
std::unordered_map<uint64_t,std::unique_ptr<Object>>& objects() {static std::unordered_map<uint64_t,std::unique_ptr<Object>> v;return v;}
Object* find_object(uint64_t k,uint64_t) {auto i=objects().find(k);return i==objects().end()?nullptr:i->second.get();}
bool resolve_cache_on() {return false;}
Texture::~Texture() {}
bool widen = false, remap = false, clip_ext = true;
bool uw_crop(int32_t v[4]) {if(!widen)return false;v[0]-=240;v[2]+=480;return true;} // synthetic NX_ULTRAWIDE
bool depth_remap() {return remap;}
bool vk_depth_clip_control() {return clip_ext;}
namespace {
@QUEUE_REGION@
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
namespace {
@CLIP_DECISION@
}
bool clip(int mode) {return depth_clip_control(mode);}
#endif
}
}
using namespace nx;
using namespace nx::nvn;
template<class T> T* add(uint64_t guest) {
 std::unique_lock lk(objects_lock());auto p=std::make_unique<T>();T* r=p.get();objects()[guest]=std::move(p);return r;
}
void set_crop(uint64_t w,int x,int y,int wd,int ht) {
 CPU c{};c.x[0]=w;c.x[1]=uint64_t(int64_t(x));c.x[2]=uint64_t(int64_t(y));c.x[3]=uint64_t(int64_t(wd));c.x[4]=uint64_t(int64_t(ht));
 hooks.at("nvnWindowSetCrop")(c);
}
bool fails(const char* hook,CPU c,const char* text) {
 try {hooks.at(hook)(c);} catch(const std::runtime_error& e) {assert(std::string(e.what()).find(text)!=std::string::npos);return true;}
 return false;
}
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
void get_crop(uint64_t w,int32_t out[4]) {
 for(int k=0;k<4;k++)out[k]=0x5a5a5a5a; // the guest's unwritten rectangle
 CPU c{};c.x[0]=w;c.x[1]=uint64_t(out);hooks.at("nvnWindowGetCrop")(c);
}
int get_mode() {CPU c{};c.x[0]=0xd00;hooks.at("nvnDeviceGetDepthMode")(c);return int(c.x[0]);}
void set_mode(uint64_t mode) {CPU c{};c.x[0]=0xd00;c.x[1]=mode;hooks.at("nvnDeviceSetDepthMode")(c);}
#endif
int main(int argc,char** argv) {
 const std::string mode=argc>1?argv[1]:"";
 Texture* t=add<Texture>(0x7000);t->width=1920;t->height=1080;
 Window* w=add<Window>(0x100);w->textures={0x7000};
 add<Window>(0x200); // a window without textures
 Window* x=add<Window>(0x300);x->textures={0xdead}; // a texture the runtime does not know
#if defined(BEFORE)
 assert(!hooks.count("nvnWindowGetCrop")&&!hooks.count("nvnDeviceSetDepthMode")&&!hooks.count("nvnDeviceGetDepthMode"));
 std::cout<<"PASS before overlay: nvnWindowGetCrop and depth-mode procs have no HLE\n";
#elif defined(NX_ASTRAL_STRICT)
 if(mode=="crop") {
  int32_t r[4];
  get_crop(0x100,r);assert(r[0]==0&&r[1]==0&&r[2]==1920&&r[3]==1080); // default: first texture size
  widen=true;set_crop(0x100,0,0,1280,720);
  assert(w->crop[0]==-240&&w->crop[2]==1760); // presentation keeps the widened rectangle
  get_crop(0x100,r);assert(r[0]==0&&r[1]==0&&r[2]==1280&&r[3]==720); // the guest's own, not widened
  widen=false;set_crop(0x100,16,8,0,0);get_crop(0x100,r);assert(r[0]==16&&r[1]==8&&r[2]==0&&r[3]==0); // as set
  CPU c{};c.x[0]=0x100;c.x[1]=0;hooks.at("nvnWindowGetCrop")(c); // null output pointer writes nothing
  c=CPU{};c.x[0]=0xbad;c.x[1]=uint64_t(r);
  assert(fails("nvnWindowGetCrop",c,"unknown window"));
  c.x[0]=0x200;assert(fails("nvnWindowGetCrop",c,"without a known texture"));
  c.x[0]=0x300;assert(fails("nvnWindowGetCrop",c,"without a known texture"));
  set_crop(0x300,0,0,640,360);get_crop(0x300,r);assert(r[2]==640&&r[3]==360); // SetCrop needs no texture
  std::cout<<"PASS strict crop: default first texture, guest (unwidened) rectangle, unknown window/texture fatal\n";
 } else if(mode=="depth") {
  assert(get_mode()==0);
  assert(clip(0)&&!clip(1)); // clip control (-w..w) only for mode 0
  clip_ext=false;assert(!clip(0)&&!clip(1));clip_ext=true;
  CPU c{};c.x[0]=0xd00;c.x[1]=2;assert(fails("nvnDeviceSetDepthMode",c,"unknown mode"));
  c.x[1]=0xffffffffULL;assert(fails("nvnDeviceSetDepthMode",c,"unknown mode"));
  assert(get_mode()==0);
  set_mode(0);set_mode(0x100000001ULL);assert(get_mode()==1); // 32-bit enum argument
  set_mode(1);assert(get_mode()==1&&device_depth_mode()==1);
  assert(pipeline_depth_mode()==1);
  set_mode(1); // the same mode again is no change
  c.x[1]=0;assert(fails("nvnDeviceSetDepthMode",c,"after a pipeline was created"));
  assert(get_mode()==1);
  std::cout<<"PASS strict depth mode: stores/returns 1, unknown mode fatal, clip control per mode, change after pipeline fatal\n";
 } else if(mode=="twice") {
  set_mode(1);CPU c{};c.x[0]=0xd00;c.x[1]=0;assert(fails("nvnDeviceSetDepthMode",c,"after start-up"));
  std::cout<<"PASS strict depth mode: a second change before any pipeline is fatal\n";
 } else if(mode=="remap") {
  remap=true;assert(!clip(0)); // NX_CLIP_Z_PATCH keeps its mode-0 behaviour
  set_mode(0);assert(get_mode()==0);
  CPU c{};c.x[0]=0xd00;c.x[1]=1;assert(fails("nvnDeviceSetDepthMode",c,"NX_CLIP_Z_PATCH"));
  assert(get_mode()==0);
  std::cout<<"PASS strict depth mode: NX_CLIP_Z_PATCH with NEAR_IS_ZERO is fatal\n";
 } else return 2;
#else
 assert(!hooks.count("nvnWindowGetCrop")&&!hooks.count("nvnDeviceSetDepthMode")&&!hooks.count("nvnDeviceGetDepthMode"));
 widen=true;set_crop(0x100,0,0,1280,720);assert(w->crop[0]==-240&&w->crop[2]==1760);
 std::cout<<"PASS default profile: no new HLE procs; SetCrop unchanged\n";
#endif
 return 0;
}
'''


def queue_region(text):
    start = text.index('// (NVNwindow*, int x, int y, int width, int height)')
    end = text.index('NX_HLE("nvnSyncInitialize"')
    return text[start:end] + '\n'


def one_line(text, signature):
    match = re.search('^' + re.escape(signature) + r' \{[^\n]*\}\n', text, re.M)
    assert match, signature
    return match.group(0)


def preprocessed(compiler, includes, path):
    out = subprocess.run([compiler, '-std=c++20', '-E', '-P', *includes, str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    # NX_HLE names its registrar after __LINE__; nothing else may differ.
    return [re.sub(r'\bhle_reg_\d+\b', 'hle_reg_N', line) for line in out.splitlines() if line.strip()]


class NvnWindowDepthTests(unittest.TestCase):
    def test_overlay_order_and_production_profiles(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        repo = common.parent
        reference = Path(os.environ.get('NVN_REFERENCE', str(repo /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        vulkan = Path(os.environ.get('NVN_VULKAN_INCLUDE', str(repo /
            '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include')))
        self.assertTrue((vulkan / 'vulkan/vulkan.h').is_file(), 'existing Vulkan headers required; no downloads')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out = ROOT / '.local/nvn-window-depth-110' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        source = out / 'source'
        stacked = runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in NATIVE_ORDER])
        nvn = source / 'runtime/src/nvn'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'), '-I', str(vulkan)]

        def run(name, flags, queue, decision, modes):
            fixture = out / (name + '.cpp')
            fixture.write_text(FIXTURE.replace('@QUEUE_REGION@', queue_region(queue)).replace('@CLIP_DECISION@', decision))
            binary = out / name
            build = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, str(fixture), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            for mode in modes:
                result = subprocess.run([str(binary), *([mode] if mode else [])], cwd=out, capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS', result.stdout)
                print(result.stdout, end='')

        # The actual before: the stacked runtime has no GetCrop or depth-mode HLE.
        run('before', ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1'], (nvn / 'nvn_queue.cpp').read_text(), '', [''])
        patch = ROOT / 'runtime/patches' / OVERLAY
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(applied.keys(), stacked.keys())
        self.assertEqual(sorted(k for k in applied if applied[k] != stacked[k]), ['runtime/src/nvn/nvn.h', 'runtime/src/nvn/nvn_pipeline.cpp',
                                           'runtime/src/nvn/nvn_queue.cpp'])
        queue = (nvn / 'nvn_queue.cpp').read_text()
        pipeline = (nvn / 'nvn_pipeline.cpp').read_text()

        # Pipeline creation reads (and so freezes) the depth mode before any shader module or Vulkan pipeline.
        graphics = pipeline.split('VkPipeline graphics_pipeline(const PipelineKey& key,')[1].split('\n}\n')[0]
        self.assertLess(graphics.index('depth_clip_control(pipeline_depth_mode())'), graphics.index('module_of('))
        self.assertIn('#if defined(NX_ASTRAL_STRICT)\n    if (clip_control) vp.pNext = &clip;\n#else', graphics)
        compute = pipeline.split('VkPipeline compute_pipeline(const ShaderInfo* cs,')[1].split('\n}\n')[0]
        self.assertLess(compute.index('pipeline_depth_mode();'), compute.index('module_of(cs)'))

        decision = one_line(pipeline, 'bool depth_clip_control(int depth_mode)')
        run('strict', ['-DNX_ASTRAL_STRICT=1'], queue, decision, ['crop', 'depth', 'twice', 'remap'])
        run('default', [], queue, decision, [''])

        for flags in (['-DNX_ASTRAL_STRICT=1'], []):
            for name in CHANGED:
                check = subprocess.run([compiler, '-std=c++20', '-pthread', *flags, *includes, '-fsyntax-only',
                                        str(nvn / name)], capture_output=True, text=True, timeout=60)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

        # Default profile: preprocessed patched TUs equal the unpatched ones (headers included).
        patched = {n: preprocessed(compiler, includes, nvn / n) for n in CHANGED}
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        for n in CHANGED:
            original = preprocessed(compiler, includes, nvn / n)
            diff = next((i for i, (a, b) in enumerate(zip(patched[n], original)) if a != b), None)
            self.assertTrue(diff is None and len(patched[n]) == len(original),
                            f'{n}: default profile differs at preprocessed line {diff}')
        print('PASS full changed TUs: strict/default syntax; default profile preprocesses identically')
        shutil.rmtree(source)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
