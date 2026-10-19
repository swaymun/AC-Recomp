"""Synthetic synchronization driver and source-bound simulator compiler fixtures.
No game data, simulator mutation, cloud credentials or paid resources are used.
"""
import plistlib
import re
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMON = Path(subprocess.check_output(['git','-C',str(ROOT),'rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()).parent
DEPENDENCY = COMMON / '.local/afternoon-control/moltenvk-1.3.0/receipt.json'


def run(args, **kw):
    return subprocess.run(list(map(str,args)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=60, **kw)


class IOSVulkanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.d=Path(self.temp.name)

    def test_actual_submit_present_helper_orders_and_retires_resources_on_success_and_failure(self):
        self.assertTrue(DEPENDENCY.is_file(), 'pinned staged Vulkan receipt required; no download fallback')
        include=json.loads(DEPENDENCY.read_text())['include_dir']
        probe=(ROOT/'probes/ios_vulkan_smoke.mm').read_text()
        core=probe.split('// BEGIN PRESENT SYNC:',1)[1].split('\n',1)[1].split('// END PRESENT SYNC',1)[0]
        fixture=r"""
#include <vulkan/vulkan.h>
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include <utility>
#include <unordered_map>
#include <vector>
#include <iostream>
static uintptr_t nextId=10;
template<class T>T handle(){return reinterpret_cast<T>(++nextId);}
static VkResult nextPresent=VK_SUCCESS,nextSubmit=VK_SUCCESS,nextAcquire=VK_SUCCESS,nextWait=VK_SUCCESS;
static VkResult nextReset=VK_SUCCESS, allocationError=VK_ERROR_OUT_OF_HOST_MEMORY;
static bool deviceLost=false;
static int failCreate=-1,created=0,destroyed=0,waits=0;
static VkSemaphore signaledSemaphore{};static bool signalPending=false,waitPending=false,semaphoreSignaled=false;
static VkFence renderFence{},presentFence{};
static std::unordered_map<VkFence,bool> pending;
static std::vector<VkFence> waited;
extern "C" {
VkResult vkCreateSemaphore(VkDevice,const VkSemaphoreCreateInfo* i,const VkAllocationCallbacks*,VkSemaphore* s){
 assert(!i->pNext);if(created==failCreate)return allocationError;*s=handle<VkSemaphore>();++created;return VK_SUCCESS;}
VkResult vkCreateFence(VkDevice,const VkFenceCreateInfo*,const VkAllocationCallbacks*,VkFence* f){
 if(created==failCreate)return allocationError;
 *f=handle<VkFence>();pending[*f]=false;++created;return VK_SUCCESS;}
VkResult vkResetFences(VkDevice,uint32_t n,const VkFence* f){for(unsigned i=0;i<n;++i)assert(!pending.at(f[i]));return nextReset;}
VkResult vkAcquireNextImageKHR(VkDevice,VkSwapchainKHR,uint64_t,VkSemaphore s,VkFence f,uint32_t* index){
 assert(!s);if(nextAcquire==VK_SUCCESS||nextAcquire==VK_SUBOPTIMAL_KHR){*index=0;pending.at(f)=true;}return nextAcquire;}
VkResult vkQueueSubmit(VkQueue,uint32_t n,const VkSubmitInfo* s,VkFence f){
 assert(n==1&&s->commandBufferCount==1&&s->signalSemaphoreCount==1&&s->pSignalSemaphores);
 assert(!signalPending&&!waitPending&&!semaphoreSignaled);if(nextSubmit!=VK_SUCCESS)return nextSubmit;
 signaledSemaphore=*s->pSignalSemaphores;signalPending=true;renderFence=f;pending.at(f)=true;return VK_SUCCESS;}
VkResult vkQueuePresentKHR(VkQueue,const VkPresentInfoKHR* p){
 assert(signalPending&&p->waitSemaphoreCount==1&&*p->pWaitSemaphores==signaledSemaphore);
 assert(p->swapchainCount==1&&p->pNext);
 auto completion=static_cast<const VkSwapchainPresentFenceInfoEXT*>(p->pNext);
 assert(completion->sType==VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT&&completion->swapchainCount==1);
 if(nextPresent==VK_ERROR_OUT_OF_HOST_MEMORY||nextPresent==VK_ERROR_OUT_OF_DEVICE_MEMORY||nextPresent==VK_ERROR_DEVICE_LOST)return nextPresent;
 presentFence=*completion->pFences;assert(presentFence!=renderFence&&!pending.at(presentFence));pending.at(presentFence)=true;waitPending=true;return nextPresent;}
VkResult vkWaitForFences(VkDevice,uint32_t n,const VkFence* f,VkBool32 all,uint64_t timeout){
 assert(n==1&&all&&timeout==UINT64_MAX&&pending.at(*f));if(nextWait!=VK_SUCCESS){if(nextWait==VK_ERROR_DEVICE_LOST)deviceLost=true;return nextWait;}++waits;waited.push_back(*f);
 if(*f==renderFence){signalPending=false;semaphoreSignaled=true;}
 if(*f==presentFence){assert(!signalPending&&semaphoreSignaled);waitPending=false;semaphoreSignaled=false;}
 pending.at(*f)=false;return VK_SUCCESS;}
void vkDestroyFence(VkDevice,VkFence f,const VkAllocationCallbacks*){assert(deviceLost||!pending.at(f));pending.erase(f);++destroyed;}
void vkDestroySemaphore(VkDevice,VkSemaphore,const VkAllocationCallbacks*){assert(deviceLost||(!signalPending&&!waitPending));semaphoreSignaled=false;++destroyed;}
}
"""
        src=self.d/'sync.cpp';src.write_text(fixture+core+r"""
int main(){auto device=handle<VkDevice>();auto queue=handle<VkQueue>();auto chain=handle<VkSwapchainKHR>();auto cmd=handle<VkCommandBuffer>();
 for(auto result:{VK_SUCCESS,VK_SUBOPTIMAL_KHR,VK_ERROR_OUT_OF_DATE_KHR,VK_ERROR_SURFACE_LOST_KHR,VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY}){
  PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextPresent=result;
  uint32_t index=99;assert(sync.acquire(chain,&index)==VK_SUCCESS&&index==0);
  assert(sync.submitPresent(cmd,chain,index)==result);
  assert(signalPending); // present must remain outstanding until its own fence is waited
  auto expected=sync.presentationWaits;assert(expected==(result==VK_ERROR_OUT_OF_HOST_MEMORY||result==VK_ERROR_OUT_OF_DEVICE_MEMORY?0:1));
  if(!expected)assert(sync.submitPresent(cmd,chain,index)==VK_ERROR_INITIALIZATION_FAILED);
  assert(sync.drain()==VK_SUCCESS&&!signalPending&&!waitPending);
  assert(semaphoreSignaled==!expected); // a render fence never consumes a binary signal
  if(expected){assert(waited.back()==presentFence); // render fence alone does not retire presentation
   if(result!=VK_ERROR_SURFACE_LOST_KHR){nextPresent=VK_SUCCESS;assert(sync.acquire(chain,&index)==VK_SUCCESS);
    assert(sync.submitPresent(cmd,chain,index)==VK_SUCCESS);}}
  assert(sync.destroy()==VK_SUCCESS);assert(sync.destroy()==VK_SUCCESS);
  assert(sync.acquire(chain,&index)==VK_ERROR_INITIALIZATION_FAILED);
  assert(sync.submitPresent(cmd,chain,index)==VK_ERROR_INITIALIZATION_FAILED);
  assert(created==destroyed&&pending.empty());
 }
 nextPresent=VK_SUCCESS;
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextAcquire=VK_ERROR_OUT_OF_DATE_KHR;
  uint32_t index;assert(sync.acquire(chain,&index)==VK_ERROR_OUT_OF_DATE_KHR);assert(!sync.acquirePending&&!sync.submissions);
  assert(sync.destroy()==VK_SUCCESS);nextAcquire=VK_SUCCESS;}
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextSubmit=VK_ERROR_OUT_OF_HOST_MEMORY;
  assert(sync.submitPresent(cmd,chain,0)==VK_ERROR_OUT_OF_HOST_MEMORY);assert(!sync.submitPending&&!sync.presentPending);
  assert(sync.destroy()==VK_SUCCESS);nextSubmit=VK_SUCCESS;}
 // Reuse automatically drains BOTH distinct outstanding fences, before reset/signal.
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);
  assert(sync.submitted!=sync.presented&&sync.acquired!=sync.submitted&&sync.acquired!=sync.presented);
  assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);auto before=waited.size();
  assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);
  assert(waited.size()==before+2&&waited[before]==sync.submitted&&waited[before+1]==sync.presented);
  assert(sync.destroy()==VK_SUCCESS);}
 // A failed completion wait cannot authorize destruction of live resources.
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);
  assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);nextWait=VK_TIMEOUT;auto before=destroyed;
  assert(sync.destroy()==VK_TIMEOUT&&destroyed==before&&waitPending);
  nextWait=VK_SUCCESS;assert(sync.destroy()==VK_SUCCESS&&!waitPending);}
 // Every allocation failure, including semaphore and all three fences.
 for(auto alloc:{VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY})for(int offset=0;offset<4;++offset){allocationError=alloc;PresentationSync sync;failCreate=created+offset;
  assert(sync.init(device,queue)==alloc);
  assert(sync.submitPresent(cmd,chain,0)==VK_ERROR_INITIALIZATION_FAILED);
  assert(sync.destroy()==VK_SUCCESS);failCreate=-1;assert(created==destroyed&&pending.empty());}
 // Both acquire/reset sites must reject errors before queue submission.
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);uint32_t index;
  nextReset=VK_ERROR_OUT_OF_HOST_MEMORY;
  assert(sync.acquire(chain,&index)==nextReset);assert(sync.submitPresent(cmd,chain,0)==nextReset);
  nextReset=VK_SUCCESS;assert(sync.destroy()==VK_SUCCESS);}
 for(auto error:{VK_TIMEOUT,VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY}) {
  // Exercise each of the actual three completion wait sites independently.
  for(int which=0;which<3;++which){PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);
   uint32_t index;auto before=destroyed;
   if(which==0){nextWait=error;assert(sync.acquire(chain,&index)==error);}
   else {assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);
    if(which==2)assert(sync.wait(sync.submitted,sync.submitPending)==VK_SUCCESS);
    nextWait=error;assert(sync.drain()==error);}
   assert(sync.destroy()==error&&destroyed==before);
   nextWait=VK_SUCCESS;assert(sync.destroy()==VK_SUCCESS);}
 }
 for(auto error:{VK_ERROR_SURFACE_LOST_KHR,VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY,VK_TIMEOUT,VK_NOT_READY}) {
  PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextAcquire=error;uint32_t index;
  assert(sync.acquire(chain,&index)==error);assert(sync.destroy()==VK_SUCCESS);nextAcquire=VK_SUCCESS;
 }
 for(auto error:{VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY}) {
  PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextSubmit=error;
  assert(sync.submitPresent(cmd,chain,0)==error);assert(sync.destroy()==VK_SUCCESS);nextSubmit=VK_SUCCESS;
 }
 // A device-lost wait permits only terminal destruction, never reuse.
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);
  nextWait=VK_ERROR_DEVICE_LOST;assert(sync.drain()==VK_SUCCESS&&sync.lost);
  assert(sync.submitPresent(cmd,chain,0)==VK_ERROR_INITIALIZATION_FAILED);
  assert(sync.destroy()==VK_SUCCESS);nextWait=VK_SUCCESS;deviceLost=false;signalPending=waitPending=false;}
 assert(created==destroyed&&pending.empty());assert(waits>12);
 for(int site=0;site<5;++site){PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);uint32_t index;
  if(site==0){nextReset=VK_ERROR_DEVICE_LOST;assert(sync.acquire(chain,&index)==nextReset);nextReset=VK_SUCCESS;}
  if(site==1){nextAcquire=VK_ERROR_DEVICE_LOST;assert(sync.acquire(chain,&index)==nextAcquire);nextAcquire=VK_SUCCESS;}
  if(site==2){nextSubmit=VK_ERROR_DEVICE_LOST;assert(sync.submitPresent(cmd,chain,0)==nextSubmit);nextSubmit=VK_SUCCESS;}
  if(site==3){nextPresent=VK_ERROR_DEVICE_LOST;assert(sync.submitPresent(cmd,chain,0)==nextPresent);nextPresent=VK_SUCCESS;}
  if(site==4){nextReset=VK_ERROR_DEVICE_LOST;assert(sync.submitPresent(cmd,chain,0)==nextReset);nextReset=VK_SUCCESS;}
  assert(sync.lost);deviceLost=true;assert(sync.destroy()==VK_SUCCESS);deviceLost=false;signalPending=waitPending=false;}
 assert(created==destroyed&&pending.empty());
 // A terminal drain inside either public operation must not enqueue more work.
 for(int operation=0;operation<2;++operation){PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);
  assert(sync.submitPresent(cmd,chain,0)==VK_SUCCESS);auto count=sync.submissions;
  nextWait=VK_ERROR_DEVICE_LOST;uint32_t index;
  assert((operation?sync.submitPresent(cmd,chain,0):sync.acquire(chain,&index))==VK_ERROR_DEVICE_LOST);
  assert(sync.submissions==count&&sync.lost);assert(sync.destroy()==VK_SUCCESS);
  nextWait=VK_SUCCESS;deviceLost=false;signalPending=waitPending=false;}
 assert(created==destroyed&&pending.empty());
 // An unknown result cannot authorize reuse or destruction. Leave it outstanding
 // until this isolated fixture process exits, exactly as the native abort path.
 {PresentationSync sync;assert(sync.init(device,queue)==VK_SUCCESS);nextPresent=VK_ERROR_UNKNOWN;
  auto before=destroyed;assert(sync.submitPresent(cmd,chain,0)==VK_ERROR_UNKNOWN);
  assert(sync.destroy()==VK_ERROR_UNKNOWN&&destroyed==before&&sync.unresolved);}

 std::cout<<"actual helper: semaphore signal/wait pairing, present-fence reuse/resize/teardown, out-of-date, surface-lost, submit/present OOM and partial-init cleanup passed\n";
}
""")
        compile_args=['clang++','-std=c++20','-I'+include,src,'-o',self.d/'sync']
        compiled=run(compile_args);self.assertEqual(compiled.returncode,0,compiled.stdout)
        result=run([self.d/'sync']);self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('partial-init cleanup passed',result.stdout)
        if os.environ.get('ACS_PRESENT_EVIDENCE'):
            dest=Path(os.environ['ACS_PRESENT_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dest/'sync-fixture.cpp');shutil.copy2(self.d/'sync',dest/'sync-fixture')
            (dest/'sync-fixture.log').write_text(result.stdout)
            (dest/'sync-receipt.json').write_text(json.dumps({
                'command':list(map(str,compile_args)), 'compile_exit':compiled.returncode,
                'compile_output':compiled.stdout or 'exit 0; no compiler diagnostics',
                'run_exit':result.returncode, 'run_output':result.stdout,
                'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
                'binary_sha256':hashlib.sha256((self.d/'sync').read_bytes()).hexdigest()},indent=2))
        print(result.stdout.strip())


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
        if os.environ.get('ACS_PRESENT_EVIDENCE'):
            dest=Path(os.environ['ACS_PRESENT_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
            (dest/'dependency-revalidation.json').write_text(json.dumps({
                'receipt_sha256':hashlib.sha256(DEPENDENCY.read_bytes()).hexdigest(),
                'artifacts_checked':len(receipt['artifacts']), 'headers_checked':len(manifest),
                'slice_metadata':selected, 'otool_command':['xcrun','otool','-arch','arm64','-l',receipt['static_library']],
                'otool_exit':result.returncode, 'otool_output':result.stdout},indent=2))
        print(f'Authorized receipt: {len(receipt["artifacts"])} artifacts, {len(manifest)} headers, {len(platforms)} arm64 simulator objects revalidated')

    def test_fresh_simulator_compile_link_uses_landed_host_without_execution(self):
        receipt=json.loads(DEPENDENCY.read_text())
        headers=self.d/'headers';(headers/'nx').mkdir(parents=True)
        (headers/'nx/runtime.h').write_text('#include <cstdint>\nnamespace nx {struct LongJmp {uint64_t buf;}; [[noreturn]] void fatal(const char*,...); }\n')
        (headers/'platform.h').write_text('namespace nx::plat {void start_memory_guard();void start_thread(void(*)(void*),void*,unsigned long long); }\n')
        sdk_result=run(['xcrun','--sdk','iphonesimulator','--show-sdk-path'])
        self.assertEqual(sdk_result.returncode,0,sdk_result.stdout)
        sdk=sdk_result.stdout.strip();self.assertTrue(sdk)
        binary=self.d/'SyntheticVulkan'
        args=['xcrun','--sdk','iphonesimulator','clang++','-std=c++20','-fobjc-arc','-target','arm64-apple-ios26.0-simulator',
              '-isysroot',sdk,'-I'+str(headers),'-I'+receipt['include_dir'],ROOT/'probes/ios_vulkan_smoke.mm',
              ROOT/'ports/ios/InputBridge.cpp',receipt['static_library'],'-o',binary]
        for framework in ['UIKit','Metal','MetalKit','QuartzCore','Foundation','CoreGraphics','IOSurface']:args+=['-framework',framework]
        result=run(args);self.assertEqual(result.returncode,0,result.stdout)
        platform=run(['xcrun','vtool','-show-build',binary]);self.assertEqual(platform.returncode,0,platform.stdout)
        self.assertIn('IOSSIMULATOR',platform.stdout);self.assertIn('minos 26.0',platform.stdout)
        deps=run(['xcrun','otool','-L',binary]);self.assertEqual(deps.returncode,0,deps.stdout)
        audited=[]
        for line in deps.stdout.splitlines()[1:]:
            install=line.strip().split(' (',1)[0];stub=Path(sdk+install)
            stub=stub.with_suffix('.tbd') if stub.suffix=='.dylib' else Path(str(stub)+'.tbd')
            data=stub.read_bytes();self.assertRegex(data.decode(),r'targets:\s*\[[^\]]*arm64-ios-simulator')
            audited.append({'install_name':install,'sha256':hashlib.sha256(data).hexdigest()})
        self.assertEqual(len(audited),11)
        if os.environ.get('ACS_PRESENT_EVIDENCE'):
            dest=Path(os.environ['ACS_PRESENT_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
            shutil.copy2(binary,dest/'compiler-synthetic')
            shutil.copytree(headers,dest/'synthetic-headers',dirs_exist_ok=True)
            (dest/'compiler-receipt.json').write_text(json.dumps({'command':list(map(str,args)),
                'compile_exit':result.returncode, 'compile_output':result.stdout or 'exit 0; no compiler/linker diagnostics',
                'executed':False, 'sdk':sdk,
                'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'platform':platform.stdout,
                'dependencies':audited,'source_sha256':hashlib.sha256((ROOT/'probes/ios_vulkan_smoke.mm').read_bytes()).hexdigest(),
                'inputs':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
                    ROOT/'probes/ios_vulkan_smoke.mm',ROOT/'tests/test_ios_vulkan.py',
                    ROOT/'ports/ios/App.mm',ROOT/'ports/ios/InputBridge.cpp',ROOT/'ports/ios/InputBridge.h']}},indent=2))
        print('Fresh unexecuted synthetic executable links unchanged landed App.mm; arm64 simulator minimum 26.0; all 11 SDK dependency platforms checked')

if __name__=='__main__':unittest.main()
