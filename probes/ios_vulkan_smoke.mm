// Original synthetic Vulkan presentation probe. No guest code or game assets.
// Including the shipped host guarantees this probe uses the exact same adapter.
#define NX_IOS_RUNTIME 1
#include "../ports/ios/App.mm"
#include <vector>
#include <thread>
#include <stdexcept>
#include <string>
#include <atomic>
#include <utility>

namespace {
std::atomic<uint64_t> messages{0}, errors{0};
VKAPI_ATTR VkBool32 VKAPI_CALL debugMessage(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT, const VkDebugUtilsMessengerCallbackDataEXT* data, void*) {
    ++messages; if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) ++errors;
    NSLog(@"Vulkan: %s", data->pMessage); return VK_FALSE;
}
void checked(VkResult result, const char* operation) {
    if (result != VK_SUCCESS) throw std::runtime_error(std::string(operation)+": "+std::to_string(result));
}
// BEGIN PRESENT SYNC: compiled unchanged by the deterministic Vulkan driver fixture.
// This bounded probe is deliberately serial. EXT present fences establish that the
// presentation engine released the semaphore/swapchain resources, unlike queue idle.
struct PresentationSync {
    VkDevice device{}; VkQueue queue{};
    VkSemaphore rendered{};
    VkFence acquired{}, submitted{}, presented{};
    bool acquirePending=false, submitPending=false, presentPending=false, lost=false, stopped=false, unresolved=false, ready=false;
    uint64_t submissions=0, presentationWaits=0;
    VkResult init(VkDevice d, VkQueue q) {
        if(device || stopped)return VK_ERROR_INITIALIZATION_FAILED;
        device=d;queue=q;
        VkSemaphoreCreateInfo si{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO}; // binary
        VkResult r=vkCreateSemaphore(device,&si,nullptr,&rendered);if(r!=VK_SUCCESS)return r;
        VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        for(auto f:{&acquired,&submitted,&presented}) {
            r=vkCreateFence(device,&fi,nullptr,f);if(r!=VK_SUCCESS)return r;
        }
        ready=true;
        return VK_SUCCESS;
    }
    VkResult wait(VkFence fence, bool& pending) {
        if(!pending)return VK_SUCCESS;
        VkResult r=vkWaitForFences(device,1,&fence,VK_TRUE,UINT64_MAX);
        if(r==VK_ERROR_DEVICE_LOST)lost=true;
        if(r==VK_SUCCESS)pending=false;
        return r;
    }
    VkResult drain() {
        if(unresolved)return VK_ERROR_UNKNOWN;
        if(lost)return VK_SUCCESS; // lost-device pending work is no longer in use
        for(auto entry:{std::pair{acquired,&acquirePending},std::pair{submitted,&submitPending},std::pair{presented,&presentPending}}) {
            VkResult r=wait(entry.first,*entry.second);
            if(r!=VK_SUCCESS)return lost?VK_SUCCESS:r;
        }
        return VK_SUCCESS;
    }
    VkResult acquire(VkSwapchainKHR chain, uint32_t* index) {
        if(!ready||stopped||lost)return VK_ERROR_INITIALIZATION_FAILED;
        VkResult r=drain();if(r!=VK_SUCCESS)return r;
        if(lost)return VK_ERROR_DEVICE_LOST; // A drain may observe terminal device loss.
        r=vkResetFences(device,1,&acquired);if(r==VK_ERROR_DEVICE_LOST)lost=true;if(r!=VK_SUCCESS)return r;
        r=vkAcquireNextImageKHR(device,chain,1000000000,VK_NULL_HANDLE,acquired,index);
        if(r==VK_ERROR_DEVICE_LOST)lost=true;
        if(r!=VK_SUCCESS&&r!=VK_SUBOPTIMAL_KHR)return r;
        acquirePending=true;VkResult done=wait(acquired,acquirePending);
        return done==VK_SUCCESS?r:done;
    }
    VkResult submitPresent(VkCommandBuffer cmd, VkSwapchainKHR chain, uint32_t index) {
        if(!ready||stopped||lost)return VK_ERROR_INITIALIZATION_FAILED;
        VkResult r=drain();if(r!=VK_SUCCESS)return r;
        if(lost)return VK_ERROR_DEVICE_LOST;
        VkFence fences[]={submitted,presented};r=vkResetFences(device,2,fences);if(r==VK_ERROR_DEVICE_LOST)lost=true;if(r!=VK_SUCCESS)return r;
        VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};submit.commandBufferCount=1;submit.pCommandBuffers=&cmd;
        submit.signalSemaphoreCount=1;submit.pSignalSemaphores=&rendered;
        r=vkQueueSubmit(queue,1,&submit,submitted);
        if(r==VK_ERROR_DEVICE_LOST)lost=true;
        if(r!=VK_SUCCESS)return r;
        submitPending=true;++submissions;
        VkSwapchainPresentFenceInfoEXT completion{VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT};
        completion.swapchainCount=1;completion.pFences=&presented;
        VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};present.pNext=&completion;
        present.waitSemaphoreCount=1;present.pWaitSemaphores=&rendered;
        present.swapchainCount=1;present.pSwapchains=&chain;present.pImageIndices=&index;
        r=vkQueuePresentKHR(queue,&present);
        // OUT_OF_DATE/SURFACE_LOST still enqueue the wait and the present fence.
        // OOM leaves present resources unaffected: only the submit fence is pending.
        if(r==VK_SUCCESS||r==VK_SUBOPTIMAL_KHR||r==VK_ERROR_OUT_OF_DATE_KHR||r==VK_ERROR_SURFACE_LOST_KHR) {
            presentPending=true;++presentationWaits;
        } else {
            stopped=true;
            if(r==VK_ERROR_DEVICE_LOST)lost=true;
            else if(r!=VK_ERROR_OUT_OF_HOST_MEMORY&&r!=VK_ERROR_OUT_OF_DEVICE_MEMORY)unresolved=true;
        }
        return r;
    }
    VkResult destroy() {
        VkResult r=drain();if(r!=VK_SUCCESS)return r;
        for(auto f:{&acquired,&submitted,&presented})if(*f){vkDestroyFence(device,*f,nullptr);*f=VK_NULL_HANDLE;}
        if(rendered){vkDestroySemaphore(device,rendered,nullptr);rendered=VK_NULL_HANDLE;}
        ready=false;stopped=true;
        return VK_SUCCESS;
    }
};
// END PRESENT SYNC
void smoke() {
    VkInstance instance = VK_NULL_HANDLE; VkDevice device = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE; VkSwapchainKHR chain = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE; VkDebugUtilsMessengerEXT messenger = VK_NULL_HANDLE;
    PresentationSync sync;
    void* window = nullptr; uint64_t presents=0, rebuilds=0, inactive=0, outdated=0;
    uint32_t lastW=0,lastH=0; bool failed=false;
    NSMutableArray* extents = [NSMutableArray array];
    NSMutableArray* advertised = [NSMutableArray array];
    bool debugSupported=false; uint32_t apiVersion=0,deviceVersion=0;
    NSString* deviceName=@"not created";
    auto save = [&](NSString* status, NSString* error) {
        writeJSON(@"vulkan.json", @{@"kind":@"synthetic_vulkan", @"game_frames":@0,
            @"status":status, @"error":error, @"presents":@(presents), @"render_submissions":@(sync.submissions), @"present_waits":@(sync.presentationWaits), @"present_fences_enabled":@YES, @"swapchains":@(rebuilds),
            @"inactive_samples":@(inactive), @"out_of_date_results":@(outdated), @"extents":extents, @"advertised_extensions":advertised,
            @"instance_api_version":@(apiVersion), @"device_api_version":@(deviceVersion), @"device_name":deviceName,
            @"instance_created":@(instance!=VK_NULL_HANDLE), @"device_created":@(device!=VK_NULL_HANDLE),
            @"surface_created":@(surface!=VK_NULL_HANDLE), @"debug_utils_enabled":@(debugSupported), @"debug_messages":@(messages.load()),
            @"debug_errors":@(errors.load()), @"validation_layer":@"not supplied; debug-utils and VkResult checks only",
            @"runtime":UIDevice.currentDevice.systemVersion, @"minimum_target":@"26.0", @"evidence_run":evidenceRun()});
    };
    try {
        // Exercise real adapter rejection before attempting a valid surface.
        uint64_t invalid = 42;
        if (acs_vulkan_create_surface(nullptr,nullptr,&invalid,nullptr) != VK_ERROR_INITIALIZATION_FAILED || invalid)
            throw std::runtime_error("invalid surface arguments were accepted");
        checked(vkEnumerateInstanceVersion(&apiVersion),"instance version");
        if (apiVersion < VK_API_VERSION_1_3) throw std::runtime_error("Vulkan 1.3 unavailable");
        uint32_t extensionCount=0;
        checked(vkEnumerateInstanceExtensionProperties(nullptr,&extensionCount,nullptr),"extension count");
        std::vector<VkExtensionProperties> available(extensionCount);
        checked(vkEnumerateInstanceExtensionProperties(nullptr,&extensionCount,available.data()),"extensions");
        for(auto& extension:available) [advertised addObject:[NSString stringWithUTF8String:extension.extensionName]];
        auto has=[&](const char* name){return std::any_of(available.begin(),available.end(),[&](auto& e){return !strcmp(e.extensionName,name);});};
        std::vector<const char*> extensions={VK_KHR_SURFACE_EXTENSION_NAME,VK_EXT_METAL_SURFACE_EXTENSION_NAME,VK_KHR_GET_SURFACE_CAPABILITIES_2_EXTENSION_NAME,VK_EXT_SURFACE_MAINTENANCE_1_EXTENSION_NAME};
        for(auto extension:extensions) if(!has(extension))throw std::runtime_error(std::string("required extension missing: ")+extension);
        // Portability enumeration is a loader extension and may be absent when linking the ICD directly.
        bool portability=has(VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME);
        if(portability)extensions.push_back(VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME);
        debugSupported=has(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
        if(debugSupported)extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.pApplicationName="ACS synthetic Vulkan"; app.apiVersion=VK_API_VERSION_1_3;
        VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ci.pApplicationInfo=&app;
        ci.flags=portability?VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR:0; ci.enabledExtensionCount=uint32_t(extensions.size());ci.ppEnabledExtensionNames=extensions.data();
        checked(vkCreateInstance(&ci,nullptr,&instance),"instance");
        auto createDebug=(PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkCreateDebugUtilsMessengerEXT");
        VkDebugUtilsMessengerCreateInfoEXT debug{VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT};
        debug.messageSeverity=VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT;
        debug.messageType=VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT|VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
        debug.pfnUserCallback=debugMessage;
        if (debugSupported) {
            if (!createDebug) throw std::runtime_error("debug-utils entry missing");
            checked(createDebug(instance,&debug,nullptr,&messenger),"debug messenger");
        }
        window=windowState().acquire(); // Exact active-scene checkpoint; no readiness polling.
        if(!window) throw std::runtime_error("no active leased scene");
        uint64_t handle=99;
        auto missingProc = +[](VkInstance, const char*) -> PFN_vkVoidFunction { return nullptr; };
        if (acs_vulkan_create_surface(instance,window,&handle,reinterpret_cast<void*>(missingProc)) != VK_ERROR_EXTENSION_NOT_PRESENT || handle)
            throw std::runtime_error("missing extension was accepted");
        if (acs_vulkan_create_surface(instance,reinterpret_cast<void*>(1),&handle,acs_vulkan_get_instance_proc_addr()) != VK_ERROR_SURFACE_LOST_KHR || handle)
            throw std::runtime_error("unowned window was accepted");
        checked((VkResult)acs_vulkan_create_surface(instance,window,&handle,acs_vulkan_get_instance_proc_addr()),"Metal surface");
        surface=reinterpret_cast<VkSurfaceKHR>(handle);
        uint32_t n=0; checked(vkEnumeratePhysicalDevices(instance,&n,nullptr),"GPU count");
        if(!n) throw std::runtime_error("no Vulkan physical devices");
        std::vector<VkPhysicalDevice> gpus(n); checked(vkEnumeratePhysicalDevices(instance,&n,gpus.data()),"GPUs");
        auto gpu=gpus[0];
        checked(vkEnumerateDeviceExtensionProperties(gpu,nullptr,&n,nullptr),"device extension count");
        std::vector<VkExtensionProperties> deviceExtensions(n);
        checked(vkEnumerateDeviceExtensionProperties(gpu,nullptr,&n,deviceExtensions.data()),"device extensions");
        if(!std::any_of(deviceExtensions.begin(),deviceExtensions.end(),[](auto& e){return !strcmp(e.extensionName,VK_EXT_SWAPCHAIN_MAINTENANCE_1_EXTENSION_NAME);}))
            throw std::runtime_error("VK_EXT_swapchain_maintenance1 required for proven presentation resource cleanup");
        VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT maintenance{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SWAPCHAIN_MAINTENANCE_1_FEATURES_EXT};
        VkPhysicalDeviceFeatures2 features{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};features.pNext=&maintenance;
        vkGetPhysicalDeviceFeatures2(gpu,&features);
        if(!maintenance.swapchainMaintenance1)throw std::runtime_error("swapchainMaintenance1 feature unavailable"); VkPhysicalDeviceProperties properties{};vkGetPhysicalDeviceProperties(gpu,&properties);
        deviceName=[NSString stringWithUTF8String:properties.deviceName];deviceVersion=properties.apiVersion;
        vkGetPhysicalDeviceQueueFamilyProperties(gpu,&n,nullptr);
        std::vector<VkQueueFamilyProperties> families(n);vkGetPhysicalDeviceQueueFamilyProperties(gpu,&n,families.data());
        uint32_t family=UINT32_MAX;
        for(uint32_t i=0;i<n;++i) { VkBool32 support=0;checked(vkGetPhysicalDeviceSurfaceSupportKHR(gpu,i,surface,&support),"present support");
            if(support && (families[i].queueFlags&VK_QUEUE_GRAPHICS_BIT)) {family=i;break;} }
        if(family==UINT32_MAX) throw std::runtime_error("no presentation queue");
        float priority=1; VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};qi.queueFamilyIndex=family;qi.queueCount=1;qi.pQueuePriorities=&priority;
        const char* dext[]={VK_KHR_SWAPCHAIN_EXTENSION_NAME,"VK_KHR_portability_subset",VK_EXT_SWAPCHAIN_MAINTENANCE_1_EXTENSION_NAME};
        VkDeviceCreateInfo di{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};di.queueCreateInfoCount=1;di.pQueueCreateInfos=&qi;di.pNext=&maintenance;di.enabledExtensionCount=3;di.ppEnabledExtensionNames=dext;
        checked(vkCreateDevice(gpu,&di,nullptr,&device),"device");
        VkQueue queue;vkGetDeviceQueue(device,family,0,&queue);
        checked(sync.init(device,queue),"presentation synchronization");
        VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pi.queueFamilyIndex=family;pi.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        checked(vkCreateCommandPool(device,&pi,nullptr,&pool),"command pool");
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=pool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;
        VkCommandBuffer cmd;checked(vkAllocateCommandBuffers(device,&ai,&cmd),"command buffer");
        std::vector<VkImage> images; bool wasInactive=false;
        for(uint64_t tick=0;tick<900;++tick) {
            auto snapshot=windowState().read();
            if(snapshot.window!=window) throw std::runtime_error("scene disconnected or replaced");
            if(snapshot.minimized) {++inactive;wasInactive=true;save(@"paused",@"none"); std::this_thread::sleep_for(std::chrono::milliseconds(30));continue;}
            VkSurfaceCapabilitiesKHR caps; checked(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(gpu,surface,&caps),"surface capabilities");
            auto extent=caps.currentExtent;
            if(!extent.width||!extent.height) {std::this_thread::sleep_for(std::chrono::milliseconds(30));continue;}
            if(!chain||wasInactive||extent.width!=lastW||extent.height!=lastH) {
                checked(sync.drain(),"resize presentation fences");checked(vkDeviceWaitIdle(device),"resize idle");if(chain)vkDestroySwapchainKHR(device,chain,nullptr);chain=VK_NULL_HANDLE;
                checked(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu,surface,&n,nullptr),"format count");
                if(!n)throw std::runtime_error("no surface formats"); std::vector<VkSurfaceFormatKHR> formats(n);checked(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu,surface,&n,formats.data()),"formats");
                if(!(caps.supportedUsageFlags&VK_IMAGE_USAGE_TRANSFER_DST_BIT))throw std::runtime_error("surface cannot clear by transfer");
                VkSwapchainCreateInfoKHR sc{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};sc.surface=surface;
                sc.minImageCount=std::max(2u,caps.minImageCount);if(caps.maxImageCount)sc.minImageCount=std::min(sc.minImageCount,caps.maxImageCount);
                sc.imageFormat=formats[0].format;sc.imageColorSpace=formats[0].colorSpace;sc.imageExtent=extent;sc.imageArrayLayers=1;
                sc.imageUsage=VK_IMAGE_USAGE_TRANSFER_DST_BIT;sc.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;sc.preTransform=caps.currentTransform;
                sc.compositeAlpha=(caps.supportedCompositeAlpha&VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR)?VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR:VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR;
                sc.presentMode=VK_PRESENT_MODE_FIFO_KHR;sc.clipped=VK_TRUE;
                checked(vkCreateSwapchainKHR(device,&sc,nullptr,&chain),"swapchain");checked(vkGetSwapchainImagesKHR(device,chain,&n,nullptr),"image count");
                images.resize(n);checked(vkGetSwapchainImagesKHR(device,chain,&n,images.data()),"images");
                lastW=extent.width;lastH=extent.height;wasInactive=false;++rebuilds;[extents addObject:@[@(lastW),@(lastH)]];
            }
            uint32_t index=0;VkResult acquired=sync.acquire(chain,&index);
            if(acquired==VK_ERROR_OUT_OF_DATE_KHR) {++outdated;wasInactive=true;continue;}
            if(acquired==VK_SUBOPTIMAL_KHR)wasInactive=true;else checked(acquired,"acquire");
            checked(vkResetCommandBuffer(cmd,0),"reset");VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};checked(vkBeginCommandBuffer(cmd,&bi),"begin");
            VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};barrier.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;barrier.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
            barrier.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;barrier.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;barrier.image=images[index];
            barrier.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};barrier.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
            vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&barrier);
            // Distinct original red/green/blue clears, changing every two seconds.
            VkClearColorValue color{};color.float32[(presents/60)%3]=.8f;color.float32[3]=1;
            vkCmdClearColorImage(cmd,images[index],VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&color,1,&barrier.subresourceRange);
            barrier.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;barrier.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;barrier.dstAccessMask=0;
            vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,0,nullptr,1,&barrier);
            checked(vkEndCommandBuffer(cmd),"end");
            VkResult result=sync.submitPresent(cmd,chain,index);
            // Wait before reuse, resize, lifecycle pause or teardown, including rejected presents.
            checked(sync.drain(),"render and presentation fences");
            if(result==VK_ERROR_OUT_OF_DATE_KHR) {++outdated;wasInactive=true;}
            else {if(result==VK_SUBOPTIMAL_KHR)wasInactive=true;else checked(result,"present");++presents;}
            if(presents%15==0)save(@"presenting",@"none");
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        }
        save(@"complete",@"none");
    } catch(const std::exception& e) {failed=true;save(@"failed",[NSString stringWithUTF8String:e.what()]);}
    if(device) {
        VkResult cleanup=sync.destroy();
        if(cleanup!=VK_SUCCESS) {save(@"failed",@"unresolved presentation fence: refusing unsafe resource destruction");startup(@"vulkan-cleanup-blocked");abort();}
        VkResult idle=vkDeviceWaitIdle(device);
        if(idle!=VK_SUCCESS) {failed=true;save(@"failed",@"device idle failed during cleanup");}
    }
    if(chain)vkDestroySwapchainKHR(device,chain,nullptr);
    if(pool)vkDestroyCommandPool(device,pool,nullptr);
    if(device)vkDestroyDevice(device,nullptr);
    if(surface)vkDestroySurfaceKHR(instance,surface,nullptr);
    if(messenger) {auto destroy=(PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance,"vkDestroyDebugUtilsMessengerEXT");if(destroy)destroy(instance,messenger,nullptr);}
    if(instance)vkDestroyInstance(instance,nullptr);
    if(window&&!windowState().relinquish(window))abort();
    writeJSON(@"cleanup.json", @{@"status":failed?@"failed":@"passed", @"evidence_run":evidenceRun(), @"vulkan_resources_destroyed":@YES, @"window_lease_released":@YES});
    startup(failed?@"vulkan-failed-cleaned":@"vulkan-cleaned");
}
}
void acs_start_vulkan_smoke(UIView* view) {
    // Geometry changes exercise the same main-thread publication path as rotation.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,4*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        CGRect frame=view.frame;frame.size.width*=.75;view.frame=frame;publishWindow(view.window,sceneActive);startup(@"synthetic-resize");
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,8*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        view.frame=view.window.bounds;publishWindow(view.window,sceneActive);startup(@"synthetic-restore-size");
    });
    std::thread([]{@autoreleasepool {smoke();}}).detach();
}

namespace nx {
void boot() {
    dispatch_async(dispatch_get_main_queue(), ^{
        UIWindow* window=(__bridge UIWindow*)windowState().read().window;
        if(!window) {startup(@"synthetic-missing-active-window");return;}
        for(UIView* child in window.rootViewController.view.subviews)
            if([child isKindOfClass:UILabel.class]) ((UILabel*)child).text=@"SYNTHETIC VULKAN · NO GAME FRAMES";
        acs_start_vulkan_smoke(window.rootViewController.view);
    });
}
[[noreturn]] void fatal(const char*,...) {startup(@"synthetic-host-fatal");abort();}
}
namespace nx::plat {
// Synthetic executable only: no guest memory or guest runtime is initialized.
void start_memory_guard() {}
void start_thread(void(*entry)(void*),void* arg,unsigned long long) {std::thread([=]{entry(arg);}).detach();}
}
