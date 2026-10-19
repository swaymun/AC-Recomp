"""Temporary Git, compiler and subprocess fixtures; no game data or simulator use."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as r


def platform_source():
    lines = (ROOT / 'runtime/patches/ios-runtime.patch').read_text().split('+++ b/runtime/src/platform_ios.mm\n', 1)[1].splitlines()
    return '\n'.join(line[1:] for line in lines if line.startswith('+')) + '\n'


class IOSRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)

    def test_reviewed_generated_identity_rejects_stale_input_pin_and_output(self):
        generated = {'main': {'files': {'code.cpp': '1' * 64}}, 'sdk': {'files': {'table.cpp': '2' * 64}}}
        receipt = {'identity': {'pin': r.PIN, 'manifest_sha256': '3' * 64, 'generated': generated}}
        r.validate_reviewed_generated(receipt, generated, '3' * 64)
        for field, value in [('pin', '0' * 40), ('manifest_sha256', '4' * 64), ('generated', {})]:
            bad = copy.deepcopy(receipt); bad['identity'][field] = value
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                r.validate_reviewed_generated(bad, generated, '3' * 64)

    def test_compile_commands_require_both_modules_simulator_adapter_and_all_macros(self):
        gen = self.d / 'gen'
        cmd = 'clang++ -isysroot /sdk/iPhoneSimulator.sdk -arch arm64 -mios-simulator-version-min=26.0 -DNX_ASTRAL_STRICT=1 -DNX_APPLE_HIGH_MEMORY=1'
        commands = [{'file': str(gen / 'main/table.cpp'), 'command': cmd},
                    {'file': str(gen / 'sdk/table.cpp'), 'command': cmd},
                    {'file': '/src/platform_ios.mm', 'command': cmd}]
        r.validate_ios_commands(commands, gen)
        for old, new in [('iPhoneSimulator', 'iPhoneOS'), ('iPhoneSimulator', 'MacOSX'),
                         ('-arch arm64', '-arch x86_64'), ('version-min=26.0', 'version-min=25.0'),
                         ('-DNX_ASTRAL_STRICT=1', ''), ('-DNX_APPLE_HIGH_MEMORY=1', '')]:
            bad = copy.deepcopy(commands); bad[1]['command'] = cmd.replace(old, new)
            with self.assertRaises(ValueError): r.validate_ios_commands(bad, gen)
        bad = copy.deepcopy(commands); bad[2]['file'] = '/src/platform_mac.cpp'
        with self.assertRaises(ValueError): r.validate_ios_commands(bad, gen)
        with self.assertRaises(ValueError): r.validate_ios_commands(commands[:1], gen)

    def test_stale_or_mismatched_native_build_is_rejected(self):
        (self.d / 'build/astral.app').mkdir(parents=True)
        files = [self.d / 'build/astral.app/astral', self.d / 'prepared.json',
                 self.d / 'build/compile_commands.json']
        for p in files: p.write_bytes(b'synthetic original')
        (self.d / 'built.json').write_text(json.dumps(r.simulator_build_identity(self.d)))
        r.validate_simulator_build(self.d)
        for p in files:
            p.write_bytes(b'stale or mismatched')
            with self.assertRaisesRegex(ValueError, 'build identity'):
                r.validate_simulator_build(self.d)
            p.write_bytes(b'synthetic original')

    def test_runtime_identity_requires_complete_current_overlay_and_host_set(self):
        patches = self.d / 'runtime/patches'; patches.mkdir(parents=True)
        host = self.d / 'ports/ios'; host.mkdir(parents=True)
        names = ('apple-memory.patch', 'astral-bootstrap.patch', 'ios-runtime.patch', 'ios-nvn-compile.patch')
        for name in names: (patches / name).write_text('synthetic ' + name)
        (host / 'App.mm').write_text('original synthetic host')
        identity = {'pin': r.PIN, 'profile': 'ios-simulator-high-v1',
                    'patches': {n: r.sha(patches / n) for n in names},
                    'host': {'App.mm': r.sha(host / 'App.mm')}}
        r.validate_ios_identity(identity, self.d)
        for section, name in [('patches', 'ios-nvn-compile.patch'), ('host', 'App.mm')]:
            bad = copy.deepcopy(identity); del bad[section][name]
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                r.validate_ios_identity(bad, self.d)
            bad = copy.deepcopy(identity); bad[section][name] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                r.validate_ios_identity(bad, self.d)

    def test_wrong_platform_library_rejected_by_real_bounded_subprocess(self):
        fake = self.d / 'xcrun'
        fake.write_text('#!/bin/sh\nprintf "    platform %s\\n" "$TEST_PLATFORM"\n')
        fake.chmod(0o755)
        lib = self.d / 'libMoltenVK.dylib'; lib.write_bytes(b'synthetic Mach-O fixture')
        with patch.dict(os.environ, {'PATH': str(self.d) + os.pathsep + os.environ['PATH']}):
            for platform in ('MACOS', 'IOS', 'MACOS\n    platform IOSSIMULATOR', ''):
                with patch.dict(os.environ, {'TEST_PLATFORM': platform}):
                    with self.assertRaisesRegex(ValueError, 'wrong-platform'):
                        r.validate_simulator_library(lib)
            with patch.dict(os.environ, {'TEST_PLATFORM': 'IOSSIMULATOR'}):
                self.assertEqual(r.validate_simulator_library(lib)['sha256'], r.sha(lib))

    def test_child_timeout_kills_owned_group_and_retains_log(self):
        log = self.d / 'child.log'
        with self.assertRaisesRegex(ValueError, 'timeout'):
            r.run_logged([sys.executable, '-u', '-c', 'import time; print("started"); time.sleep(30)'], log, timeout=.1)
        self.assertIn('started', log.read_text())

    def test_only_owned_upstream_paths_and_no_successful_gpu_audio_stubs(self):
        patch_text = (ROOT / 'runtime/patches/ios-runtime.patch').read_text()
        paths = [line.split(' b/', 1)[1] for line in patch_text.splitlines() if line.startswith('diff --git ')]
        self.assertEqual(paths, ['CMakeLists.txt', 'runtime/src/platform_ios.mm'])
        source = platform_source()
        for op in ('audio_open', 'audio_submit', 'vulkan_get_instance_proc_addr', 'vulkan_create_surface'):
            function = source.split(op + '(', 1)[1].split('}', 1)[0]
            self.assertIn('nx::fatal(', function)
        self.assertNotIn('int main(', source)
        self.assertNotIn('SDL_', source)

    def test_window_snapshot_lifecycle_ownership_and_concurrent_guest_reads(self):
        compiler = shutil.which('clang++')
        if not compiler: self.skipTest('C++ compiler unavailable')
        app = (ROOT / 'ports/ios/App.mm').read_text()
        core = app.split('// BEGIN WINDOW STATE:', 1)[1].split('\n', 1)[1].split('// END WINDOW STATE', 1)[0]
        fixture = self.d / 'window.cpp'
        fixture.write_text(r"""#include <mutex>
#include <unordered_map>
#include <cstdint>
#include <atomic>
#include <thread>
#include <cassert>
""" + core + r"""
std::atomic<int> refsA{0}, refsB{0};
int a, b;
void retain(void* p) { (p == &a ? refsA : refsB).fetch_add(1); }
void release(void* p) { assert((p == &a ? refsA : refsB).fetch_sub(1) > 0); }
int main() {
 ACSWindowState state(retain, release);
 assert(state.read().minimized && state.read().generation == 0);
 assert(!state.acquire()); assert(state.relinquish(nullptr));
 state.publish(&a,true,2556,1179,2556,1179);
 auto s=state.read(); assert(!s.minimized && s.width==2556 && s.height==1179);
 assert(s.screenWidth==2556 && s.screenHeight==1179 && s.generation==1);
 void* old=state.acquire(); assert(old==&a && refsA==2);
 for (bool active : {false,false,true}) { // inactive, background, foreground
  state.publish(&a,active,2556,1179,2556,1179);
  assert(state.read().minimized==!active && state.read().generation==1);
  if (!active) assert(!state.acquire());
 }
 state.publish(&a,true,1179,2556,2556,1179); // geometry changes pixels, not identity
 assert(state.read().width==1179 && state.read().generation==1);
 state.publish(&b,true,2420,1668,2420,1668);
 assert(state.read().generation==2 && refsA==1 && refsB==1);
 assert(state.relinquish(old) && refsA==0); // old lease cannot release replacement
 assert(!state.relinquish(old)); assert(!state.relinquish(reinterpret_cast<void*>(1)));
 std::atomic<bool> stop{false}; std::atomic<int> reads{0};
 std::thread guest([&]{ while(!stop.load()) {
   auto t=state.read();
   assert((t.width==2420 && t.height==1668) || (t.width==1668 && t.height==2420));
   if(void* p=state.acquire()) assert(state.relinquish(p));
   ++reads;
 }});
 while(reads.load()<100) std::this_thread::yield();
 for(int i=0;i<10000;++i) state.publish(&b,i%3==0,i%2?2420:1668,i%2?1668:2420,2420,1668);
 stop=true; guest.join(); assert(reads>100);
 void* last=nullptr; state.publish(&b,true,2420,1668,2420,1668); last=state.acquire();
 state.publish(nullptr,false,0,0,0,0);
 s=state.read(); assert(s.minimized && !s.width && !s.screenWidth && s.generation==3);
 assert(refsB==1); assert(state.relinquish(last) && refsB==0);
}
""")
        subprocess.run([compiler, '-std=c++20', '-pthread', str(fixture), '-o', str(self.d / 'window')],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        subprocess.run([str(self.d / 'window')], check=True, timeout=10)

    def test_actual_input_adapter_compiles_and_maps_every_button_and_axes(self):
        compiler = shutil.which('clang++')
        if not compiler: self.skipTest('C++ compiler unavailable')
        source = platform_source()
        function = source[source.index('void read_pad('):source.index('bool audio_open(')]
        fixture = self.d / 'mapping.cpp'
        fixture.write_text('''#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include "InputBridge.h"
namespace nx { [[noreturn]] void fatal(const char*) { std::abort(); } }
namespace nx::plat {
constexpr int kStickMax=32767;
enum : uint64_t { kA=1, kB=2, kX=4, kY=8, kL=64, kR=128, kZL=256, kZR=512,
 kPlus=1024,kMinus=2048,kStickLLeft=1<<16,kStickLUp=1<<17,kStickLRight=1<<18,kStickLDown=1<<19,
 kStickRLeft=1<<20,kStickRUp=1<<21,kStickRRight=1<<22,kStickRDown=1<<23 };
struct PadState { uint64_t buttons=0; int32_t lx=0,ly=0,rx=0,ry=0; };
''' + function + '''}
#include <cassert>
int main() {
 using namespace nx::plat;
 const uint64_t masks[]={kA,kB,kX,kY,kL,kR,kZL,kZR,kPlus,kMinus};
 for(int i=0;i<10;++i) { acs_input_release_all();
 assert(acs_input_begin(1,static_cast<ACSInputControl>(ACS_A+i),0,0));
 PadState p; read_pad(p); assert(p.buttons==masks[i]); }
 acs_input_release_all(); acs_input_begin(2,ACS_STICK_LEFT,1,0); acs_input_begin(3,ACS_STICK_RIGHT,0,-1);
 PadState p; read_pad(p); assert(p.lx==32767 && p.ly==0 && p.rx==0 && p.ry==-32767);
 assert(p.buttons==(kStickLRight|kStickRDown));
 acs_input_release_all(); PadState neutral; read_pad(neutral); assert(neutral.buttons==0 && neutral.lx==0 && neutral.ry==0);
}
''')
        subprocess.run([compiler, '-std=c++20', '-pthread', '-I' + str(ROOT / 'ports/ios'), str(fixture),
                        str(ROOT / 'ports/ios/InputBridge.cpp'), '-o', str(self.d / 'mapping')], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        subprocess.run([str(self.d / 'mapping')], check=True, timeout=10)

    def test_incremental_patch_on_exact_pin_and_real_cmake_generated_fixtures(self):
        common = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--path-format=absolute', '--git-common-dir'], timeout=10).decode().strip()
        main = Path(common).parent
        ref = main / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        cmake = main / '.local/game-private/astral-work/venv/bin/cmake'
        ninja = main / '.local/game-private/astral-work/venv/bin/ninja'
        headers = main / '.local/orchestrate/2026-10-18-game/worktrees/RUNTIME-BOOTSTRAP-001/.local/runtime-bootstrap/vulkan-headers/include'
        if not ref.exists() or not cmake.exists() or sys.platform != 'darwin':
            self.skipTest('optional local pinned source/CMake/iOS SDK unavailable')
        source = self.d / 'source'
        patches = [ROOT / 'runtime/patches' / n for n in ('apple-memory.patch','astral-bootstrap.patch','ios-runtime.patch','ios-nvn-compile.patch')]
        r.prepare_source(ref, source, patches)
        self.assertEqual(r.git(source, 'rev-parse', 'HEAD'), r.PIN)
        gen = self.d / 'gen'
        for mod in ('main','sdk'):
            (gen/mod).mkdir(parents=True); (gen/mod/'table.cpp').write_text('int fixture_'+mod+';\n')
        sdk = subprocess.check_output(['xcrun','--sdk','iphonesimulator','--show-sdk-path'],timeout=20).decode().strip()
        args = [str(cmake),'-S',str(source),'-B',str(self.d/'build'),'-G','Ninja', '-DNX_GAME=astral',
                '-DNX_GEN_DIR='+str(gen),'-DCMAKE_SYSTEM_NAME=iOS','-DCMAKE_OSX_SYSROOT='+sdk,
                '-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_OSX_DEPLOYMENT_TARGET=26.0',
                '-DCMAKE_MAKE_PROGRAM='+str(ninja),'-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                '-DNX_IOS_HOST_DIR='+str(ROOT/'ports/ios'),'-DNX_VULKAN_INCLUDE='+str(headers)]
        subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        commands = json.loads((self.d/'build/compile_commands.json').read_text())
        r.validate_ios_commands(commands,gen)
        self.assertFalse(any(c['file'].endswith('platform_mac.cpp') for c in commands))
        device_sdk = subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],timeout=20).decode().strip()
        device_args = [x.replace(sdk,device_sdk).replace(str(self.d/'build'),str(self.d/'device-build')) for x in args]
        result = subprocess.run(device_args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'arm64 simulator only',result.stdout)
