"""Original adapter lifetime, exact-pin overlay and real compiler rejection fixtures.
No game data, simulator mutation, cloud credentials or paid resources are used.
"""
import difflib
import hashlib
import json
import os
import plistlib
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMON = Path(subprocess.check_output(['git','-C',str(ROOT),'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()).parent
DEPENDENCY = COMMON / '.local/afternoon-control/moltenvk-1.3.0/receipt.json'
LIB_SHA = 'c6579190db24f622856c7fbc0bd2bdab7a2338f083945aa1ea0cab8afc38df27'


def run(args, **kw):
    return subprocess.run(list(map(str,args)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=60, **kw)


def dependency_block():
    patch = (ROOT/'runtime/patches/ios-vulkan.patch').read_text()
    lines = '\n'.join(x[1:] for x in patch.splitlines() if x.startswith('+') and not x.startswith('+++'))
    return lines.split('# BEGIN PINNED IOS VULKAN DEPENDENCY',1)[1].split('# END PINNED IOS VULKAN DEPENDENCY',1)[0]


class IOSVulkanAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.cmake = shutil.which('cmake') or str(COMMON/'.local/game-private/astral-work/venv/bin/cmake')

    def configure(self, library=None, include=None):
        source=self.d/'cmake'; source.mkdir(exist_ok=True)
        (source/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.20)\nproject(validation NONE)\n'+dependency_block())
        return run([self.cmake,'-S',source,'-B',self.d/('build-'+str(len(list(self.d.iterdir())))),
                    '-DNX_IOS_MOLTENVK_LIBRARY='+str(library or ''), '-DNX_VULKAN_INCLUDE='+str(include or '')])

    def test_missing_dependency_is_a_configure_failure(self):
        result=self.configure();self.assertNotEqual(result.returncode,0)
        self.assertIn('missing pinned simulator MoltenVK library',result.stdout)

    @unittest.skipUnless(sys.platform=='darwin','Apple platform compiler fixture')
    def test_real_macos_and_device_arm64_are_rejected_even_though_arch_matches(self):
        src=self.d/'fixture.c';src.write_text('int original_platform_fixture;\n')
        for target,sdk in [('arm64-apple-macos14.0','macosx'),('arm64-apple-ios26.0','iphoneos')]:
            lib=self.d/(sdk+'.a');obj=self.d/(sdk+'.o')
            compiled=run(['xcrun','--sdk',sdk,'clang','-target',target,'-c',src,'-o',obj]);self.assertEqual(compiled.returncode,0,compiled.stdout)
            archived=run(['xcrun','libtool','-static',obj,'-o',lib]);self.assertEqual(archived.returncode,0,archived.stdout)
            result=self.configure(lib);self.assertNotEqual(result.returncode,0)
            self.assertIn('wrong-platform MoltenVK',result.stdout)

    @unittest.skipUnless(sys.platform=='darwin','Apple platform compiler fixture')
    def test_unpinned_simulator_library_is_rejected(self):
        src=self.d/'fixture.c';src.write_text('int original_simulator_fixture;\n');obj=self.d/'sim.o';lib=self.d/'sim.a'
        result=run(['xcrun','--sdk','iphonesimulator','clang','-target','arm64-apple-ios26.0-simulator','-c',src,'-o',obj]);self.assertEqual(result.returncode,0,result.stdout)
        result=run(['xcrun','libtool','-static',obj,'-o',lib]);self.assertEqual(result.returncode,0,result.stdout)
        result=self.configure(lib);self.assertNotEqual(result.returncode,0);self.assertIn('unpinned simulator MoltenVK bytes',result.stdout)

    def test_pinned_bytes_and_headers_pass_real_cmake_platform_audit(self):
        if not DEPENDENCY.exists():self.skipTest('parent public dependency receipt absent')
        receipt=json.loads(DEPENDENCY.read_text());lib=Path(receipt['static_library'])
        self.assertEqual(hashlib.sha256(lib.read_bytes()).hexdigest(),LIB_SHA)
        result=self.configure(lib,receipt['include_dir']);self.assertEqual(result.returncode,0,result.stdout)
        result=self.configure(lib,self.d/'missing-headers');self.assertNotEqual(result.returncode,0);self.assertIn('missing pinned Vulkan headers',result.stdout)

    def test_threaded_window_layer_leases_inactive_disconnect_and_unknown_release(self):
        app=(ROOT/'ports/ios/App.mm').read_text()
        core=app.split('// BEGIN WINDOW STATE:',1)[1].split('\n',1)[1].split('// END WINDOW STATE',1)[0]
        src=self.d/'lease.cpp';src.write_text('''#include <mutex>
#include <unordered_map>
#include <cstdint>
#include <thread>
#include <atomic>
#include <cassert>
''' + core + '''
int window, layer, replacement, replacementLayer;
std::atomic<int> windowRefs{0}, layerRefs{0}, nextRefs{0}, nextLayerRefs{0};
std::atomic<int>& refs(void* p) { return p==&window?windowRefs:p==&layer?layerRefs:p==&replacement?nextRefs:nextLayerRefs; }
void retain(void* p) { ++refs(p); }
void release(void* p) { assert(refs(p).fetch_sub(1)>0); }
int main() {
 ACSWindowState s(retain,release);
 assert(!s.acquire());assert(!s.acquireLayer(&window));
 s.publish(&window,true,100,50,100,50,&layer);
 auto lease=s.acquire();assert(lease==&window&&windowRefs==2&&layerRefs==2);
 auto retained=s.acquireLayer(lease);assert(retained==&layer&&layerRefs==3);release(retained);
 s.publish(&window,false,100,50,100,50,&layer);
 assert(!s.acquire()&&!s.acquireLayer(lease));assert(layerRefs==2);
 s.publish(&window,true,50,100,100,50,&layer);assert(s.read().width==50);
 std::atomic<bool> stop{false};std::atomic<int> reads{0};
 std::thread guest([&]{while(!stop){auto p=s.acquire();if(p){auto l=s.acquireLayer(p);if(l)release(l);assert(s.relinquish(p));}++reads;}});
 while(reads<100)std::this_thread::yield();
 for(int i=0;i<1000;++i)s.publish(&window,i%2,100,50,100,50,&layer);
 stop=true;guest.join();
 s.publish(&replacement,true,200,100,200,100,&replacementLayer);
 assert(!s.acquireLayer(lease));assert(windowRefs==1&&layerRefs==1);
 assert(s.relinquish(lease));assert(windowRefs==0&&layerRefs==0);
 assert(!s.relinquish(lease));assert(!s.relinquish((void*)1));
 auto next=s.acquire();s.publish(nullptr,false,0,0,0,0);
 assert(!s.acquireLayer(next)&&nextRefs==1&&nextLayerRefs==1);
 assert(s.relinquish(next)&&nextRefs==0&&nextLayerRefs==0);
 s.publish(&window,true,100,50,100,50,&layer);auto old=s.acquire();
 s.publish(&window,true,100,50,100,50,&replacementLayer);
 assert(!s.acquire()&&!s.acquireLayer(old));assert(s.relinquish(old));
 assert(layerRefs==0&&windowRefs==1&&nextLayerRefs==1);
 auto fresh=s.acquire();assert(fresh==&window);s.publish(nullptr,false,0,0,0,0);
 assert(s.relinquish(fresh)&&windowRefs==0&&nextLayerRefs==0);
}
''')
        result=run(['clang++','-std=c++20','-pthread',src,'-o',self.d/'lease']);self.assertEqual(result.returncode,0,result.stdout)
        result=run([self.d/'lease']);self.assertEqual(result.returncode,0,result.stdout)
        self.retain_receipt('threaded-leases',src,self.d/'lease','Concurrent leases, replacement, closure and duplicate release passed')

    def test_incremental_overlay_applies_after_current_runtime_on_exact_wonder_pin(self):
        sys.path.insert(0,str(ROOT/'tools'));import prepare_runtime as r
        ref=COMMON/'.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        if not ref.exists():self.skipTest('private pinned public reference unavailable')
        source=self.d/'source'
        names=['apple-memory.patch','astral-bootstrap.patch','ios-runtime.patch','ios-nvn-compile.patch','ios-vulkan.patch']
        r.prepare_source(ref,source,[ROOT/'runtime/patches'/n for n in names])
        self.assertEqual(r.git(source,'rev-parse','HEAD'),'010ed7a596a621c15d3a8dfa5795ca8c3668b066')
        adapter=(source/'runtime/src/platform_ios.mm').read_text()
        self.assertIn('return acs_vulkan_get_instance_proc_addr()',adapter)
        self.assertIn('return acs_vulkan_create_surface(instance, window, surface, gipa)',adapter)
        self.assertIn('nx::fatal("unsupported iOS host operation: audio_open")',adapter)
        paths=[x.split(' b/')[1] for x in (ROOT/'runtime/patches/ios-vulkan.patch').read_text().splitlines() if x.startswith('diff --git')]
        self.assertEqual(paths,['CMakeLists.txt','runtime/src/platform_ios.mm'])


    def test_compiled_actual_main_thread_publication_and_surface_failure_cleanup(self):
        receipt=json.loads(DEPENDENCY.read_text())
        app=(ROOT/'ports/ios/App.mm').read_text()
        core=app.split('// BEGIN WINDOW STATE:',1)[1].split('\n',1)[1].split('// END WINDOW STATE',1)[0]
        host=app.split('static void retainWindow',1)[1].split('namespace nx::plat',1)[0]
        fixture=r"""
#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#include <mutex>
#include <unordered_map>
#include <cstdint>
#include <algorithm>
#include <cmath>
#include <exception>
#include <cassert>
#include <thread>
#include <atomic>
#include <iostream>
static std::atomic<int> uiReads{0},releasedOnMain{0};
@interface ReleaseWitness:NSObject
@end
@implementation ReleaseWitness
-(void)dealloc {assert(NSThread.isMainThread);++releasedOnMain;}
@end
static void checkUI(){assert(NSThread.isMainThread);++uiReads;}
@interface TestScreen:NSObject
@property(readonly) CGFloat scale;
@property(readonly) CGRect nativeBounds;
@end
@implementation TestScreen
-(CGFloat)scale {checkUI();return 2;}
-(CGRect)nativeBounds {checkUI();return CGRectMake(0,0,400,800);}
@end
@interface TestScene:NSObject
@property(readonly) NSInteger activationState;
@end
@implementation TestScene
-(NSInteger)activationState {checkUI();return 0;}
@end
static constexpr NSInteger UISceneActivationStateForegroundActive=0;
@interface UIView:NSObject
@property CGRect bounds;
@property(strong) CALayer* layer;
@end
@implementation UIView
@end
@interface TestController:NSObject
@property(strong) UIView* view;
@end
@implementation TestController
@end
@interface UIWindow:NSObject
@property(strong) TestScreen* screen;
@property(strong) TestScene* windowScene;
@property(strong) TestController* rootViewController;
@property BOOL hidden;
@end
@implementation UIWindow
@end
"""
        src=self.d/'adapter.mm';src.write_text(fixture+core+'static void retainWindow'+host+r"""
static int creates=0,destroys=0;
static VkResult nextResult=VK_SUCCESS;
static bool closeDuringCreate=false,missingCreate=false,missingDestroy=false;
static CAMetalLayer* expected;
extern "C" PFN_vkVoidFunction vkGetInstanceProcAddr(VkInstance,const char*) {return nullptr;}
static VKAPI_ATTR VkResult VKAPI_CALL create(VkInstance,const VkMetalSurfaceCreateInfoEXT* ci,const VkAllocationCallbacks*,VkSurfaceKHR* out){
 assert(ci->pLayer==expected);++creates;
 if(closeDuringCreate)windowState().publish(nullptr,false,0,0,0,0);
 if(nextResult==VK_SUCCESS)*out=reinterpret_cast<VkSurfaceKHR>(123);
 return nextResult;
}
static VKAPI_ATTR void VKAPI_CALL destroy(VkInstance,VkSurfaceKHR s,const VkAllocationCallbacks*){
 assert(s==reinterpret_cast<VkSurfaceKHR>(123));++destroys;
}
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL get(VkInstance,const char* name){
 if(!strcmp(name,"vkCreateMetalSurfaceEXT"))return missingCreate?nullptr:reinterpret_cast<PFN_vkVoidFunction>(&create);
 return missingDestroy?nullptr:reinterpret_cast<PFN_vkVoidFunction>(&destroy);
}
int main(int argc,char**){@autoreleasepool{
 if(argc>1){std::thread t([]{publishWindow(nil,false);});t.join();return 99;}
 UIWindow* w=[UIWindow new];w.screen=[TestScreen new];w.windowScene=[TestScene new];
 w.rootViewController=[TestController new];w.rootViewController.view=[UIView new];
 UIView* view=w.rootViewController.view;view.layer=[CALayer layer];view.bounds=CGRectMake(0,0,100,200);
 publishWindow(w,true);expected=sceneLayer;assert(expected.superlayer==view.layer);
 assert(windowState().read().width==200&&expected.drawableSize.height==400);
 auto lease=windowState().acquire();assert(lease==(__bridge void*)w);
 auto instance=reinterpret_cast<void*>(1);auto gipa=reinterpret_cast<void*>(&get);
 uint64_t surface=9;
 assert(acs_vulkan_get_instance_proc_addr()==reinterpret_cast<void*>(&vkGetInstanceProcAddr));
 assert(acs_vulkan_create_surface(instance,lease,nullptr,gipa)==VK_ERROR_INITIALIZATION_FAILED);
 assert(acs_vulkan_create_surface(nullptr,lease,&surface,gipa)==VK_ERROR_INITIALIZATION_FAILED&&surface==0);
 auto reads=uiReads.load();std::thread guest([&]{@autoreleasepool{
 assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==VK_SUCCESS&&surface==123);
 }});guest.join();assert(uiReads==reads); // surface acquisition touches no UIKit off-main
 destroy(nullptr,reinterpret_cast<VkSurfaceKHR>(surface),nullptr);
 view.bounds=CGRectMake(0,0,50,200);publishWindow(w,true);
 assert(windowState().read().width==100&&sceneLayer.drawableSize.width==100);
 publishWindow(w,false);assert(sceneLayer.hidden);
 assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==VK_ERROR_SURFACE_LOST_KHR&&surface==0);
 publishWindow(w,true);assert(!sceneLayer.hidden);
 for(auto failure:{VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY,VK_ERROR_INITIALIZATION_FAILED}){
 nextResult=failure;assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==failure&&surface==0);}
 nextResult=VK_SUCCESS;
 missingCreate=true;assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==VK_ERROR_EXTENSION_NOT_PRESENT);
 missingCreate=false;missingDestroy=true;
 auto before=creates;assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==VK_ERROR_EXTENSION_NOT_PRESENT&&creates==before);
 missingDestroy=false;closeDuringCreate=true;before=destroys;
 assert(acs_vulkan_create_surface(instance,lease,&surface,gipa)==VK_ERROR_SURFACE_LOST_KHR&&surface==0&&destroys==before+1);
 assert(windowState().relinquish(lease));assert(!windowState().relinquish(lease));
 publishWindow(nil,false);assert(!sceneLayer&&!layerWindow);
 assert(!expected.superlayer);
 // Exercise the shipped deferred release, then drain the actual main queue.
 void* witness=nullptr;
 @autoreleasepool {ReleaseWitness* object=[ReleaseWitness new];witness=(__bridge_retained void*)object;}
 std::thread releaser([&]{releaseWindow(witness);});releaser.join();assert(releasedOnMain==0);
 const auto deadline=CFAbsoluteTimeGetCurrent()+2;
 while(!releasedOnMain&&CFAbsoluteTimeGetCurrent()<deadline)CFRunLoopRunInMode(kCFRunLoopDefaultMode,.01,true);
 assert(releasedOnMain==1);
 std::cout<<"actual adapter: main-thread publication, worker surface access, resize/lifecycle, target closure, missing cleanup proc, driver allocation failures and main-queue final release passed\n";
 }}
""")
        result=run(['xcrun','clang++','-std=c++20','-fobjc-arc','-I'+receipt['include_dir'],src,
                    '-framework','Foundation','-framework','QuartzCore','-o',self.d/'adapter'])
        self.assertEqual(result.returncode,0,result.stdout)
        result=run([self.d/'adapter']);self.assertEqual(result.returncode,0,result.stdout);print(result.stdout.strip())
        result=run([self.d/'adapter','off-main']);self.assertNotEqual(result.returncode,0)
        self.assertNotEqual(result.returncode,99,'off-main publication must terminate before layer access')
        self.retain_receipt('compiled-adapter',src,self.d/'adapter',result.stdout)

    def retain_receipt(self,name,source,binary,output):
        if not os.environ.get('ACS_ADAPTER_EVIDENCE'):return
        dest=Path(os.environ['ACS_ADAPTER_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
        for path in (source,binary):shutil.copy2(path,dest/(name+path.suffix))
        (dest/(name+'.json')).write_text(json.dumps({'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(), 'observation':output or 'compiled adapter execution passed',
            'app_sha256':hashlib.sha256((ROOT/'ports/ios/App.mm').read_bytes()).hexdigest()},indent=2))

    def test_both_family_packages_link_actual_adapter_with_pinned_slice(self):
        receipt=json.loads(DEPENDENCY.read_text())
        # Compile the shipped production host, replacing only guest runtime declarations.
        (self.d/'nx').mkdir();(self.d/'nx/runtime.h').write_text('''#pragma once
#include <cstdint>
#include <cstddef>
namespace nx {struct LongJmp {uint64_t buf;}; [[noreturn]] void fatal(const char*,...);}
''')
        (self.d/'platform.h').write_text('namespace nx::plat {void start_memory_guard(); void start_thread(void(*)(void*),void*,unsigned long long);}\n')
        stub=self.d/'guest-stub.cpp';stub.write_text('''#include <cstdlib>
namespace nx {void boot(){} [[noreturn]] void fatal(const char*,...){abort();}}
namespace nx::plat {void start_memory_guard(){} void start_thread(void(*)(void*),void*,unsigned long long){}}
''')
        sdk=run(['xcrun','--sdk','iphonesimulator','--show-sdk-path']).stdout.strip()
        for family in ('iPhone','iPad'):
            package=self.d/(family+'.app');package.mkdir()
            binary=package/'AdapterLink'
            plist={'CFBundleExecutable':'AdapterLink','CFBundleIdentifier':'local.acs.adapter.'+family.lower(),
                   'CFBundlePackageType':'APPL','MinimumOSVersion':'26.0','UIDeviceFamily':[1 if family=='iPhone' else 2]}
            (package/'Info.plist').write_bytes(plistlib.dumps(plist))
            self.assertEqual(plistlib.loads((package/'Info.plist').read_bytes())['UIDeviceFamily'],[1 if family=='iPhone' else 2])
            args=['xcrun','--sdk','iphonesimulator','clang++','-std=c++20','-fobjc-arc','-DNX_IOS_RUNTIME=1',
                  '-target','arm64-apple-ios26.0-simulator','-isysroot',sdk,'-I'+str(self.d),'-I'+receipt['include_dir'],
                  ROOT/'ports/ios/App.mm',ROOT/'ports/ios/InputBridge.cpp',stub,receipt['static_library'],'-o',binary]
            for framework in ['UIKit','Metal','MetalKit','QuartzCore','Foundation','CoreGraphics','IOSurface']:args+=['-framework',framework]
            result=run(args);self.assertEqual(result.returncode,0,result.stdout)
            result=run(['xcrun','vtool','-show-build',binary]);self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('IOSSIMULATOR',result.stdout);self.assertIn('minos 26.0',result.stdout)
            deps=run(['xcrun','otool','-L',binary]);self.assertEqual(deps.returncode,0,deps.stdout)
            self.assertNotIn('libMoltenVK.dylib',deps.stdout)
            audited=[]
            for line in deps.stdout.splitlines()[1:]:
                install=line.strip().split(' (',1)[0]
                path=Path(sdk+install)
                path=path.with_suffix('.tbd') if path.suffix=='.dylib' else Path(str(path)+'.tbd')
                data=path.read_bytes()
                self.assertRegex(data.decode(),r'targets:\s*\[[^\]]*arm64-ios-simulator')
                audited.append({'install_name':install,'sdk_tbd':str(path),'sha256':hashlib.sha256(data).hexdigest()})
            self.assertEqual(len(audited),11)
            if os.environ.get('ACS_ADAPTER_EVIDENCE'):
                dest=Path(os.environ['ACS_ADAPTER_EVIDENCE'])
                dest.mkdir(parents=True,exist_ok=True)
                (dest/(family+'-sdk-dependencies.json')).write_text(json.dumps(audited,indent=2))
                (dest/(family+'-Info.plist')).write_bytes((package/'Info.plist').read_bytes())
                (dest/(family+'-build-command.json')).write_text(json.dumps(args,indent=2,default=str))
                shutil.copy2(stub,dest/'guest-link-stub.cpp')
            print(f'{family}: production adapter link passed, arm64 IOSSIMULATOR minimum 26.0; not executed')
            self.retain_receipt(family,ROOT/'ports/ios/App.mm',binary,result.stdout+deps.stdout)

    def test_full_authorized_receipt_headers_and_platform_identities(self):
        self.assertEqual(hashlib.sha256(DEPENDENCY.read_bytes()).hexdigest(),'666bc78ede4976b3c30588625a6e73f19fd7d0b158eb419e18d2aac3c03caaa8')
        receipt=json.loads(DEPENDENCY.read_text())
        for entry in receipt['artifacts'].values():
            data=Path(entry['path']).read_bytes();self.assertEqual(len(data),entry['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
        manifest=json.loads(Path(receipt['artifacts']['headers_manifest']['path']).read_text())
        for entry in manifest:
            data=Path(entry['path']).read_bytes()
            self.assertEqual(len(data),entry['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
        metadata=plistlib.loads(Path(receipt['artifacts']['static_xcframework_metadata']['path']).read_bytes())
        selected=[x for x in metadata['AvailableLibraries'] if x['LibraryIdentifier']=='ios-arm64_x86_64-simulator'][0]
        self.assertEqual(selected['SupportedPlatform'],'ios');self.assertEqual(selected['SupportedPlatformVariant'],'simulator')
        self.assertIn('arm64',selected['SupportedArchitectures'])
        result=run(['xcrun','otool','-arch','arm64','-l',receipt['static_library']]);self.assertEqual(result.returncode,0,result.stdout)
        platforms=re.findall(r'\bplatform\s+(\w+)',result.stdout);self.assertTrue(platforms)
        self.assertTrue(all(x in ('7','IOSSIMULATOR') for x in platforms))
        print(f'Authorized receipt: {len(receipt["artifacts"])} artifacts, {len(manifest)} headers, {len(platforms)} arm64 simulator objects revalidated')


if __name__=='__main__':unittest.main()
