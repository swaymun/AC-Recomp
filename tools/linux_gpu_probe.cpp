// Original synthetic Vulkan clear/readback probe. No game data or shaders.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static std::atomic<unsigned> errors{0};
static VKAPI_ATTR VkBool32 VKAPI_CALL debug(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT, const VkDebugUtilsMessengerCallbackDataEXT* data, void*) {
    if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) ++errors;
    std::cerr << "validation: " << data->pMessage << '\n';
    return VK_FALSE;
}
static void check(VkResult r) { if (r != VK_SUCCESS) throw std::runtime_error("Vulkan result " + std::to_string(r)); }
static std::string quote(const std::string& s) {
    std::string r = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { r += '\\'; r += c; }
        else if (c < 32) r += '?'; else r += c;
    }
    return r + '"';
}
struct Resources {
    VkInstance instance{}; VkDebugUtilsMessengerEXT messenger{}; VkDevice device{};
    VkImage image{}; VkDeviceMemory image_mem{}, buffer_mem{}; VkBuffer buffer{};
    VkCommandPool pool{};
    ~Resources() {
        if (device) {
            vkDeviceWaitIdle(device);
            if (pool) vkDestroyCommandPool(device, pool, nullptr);
            if (buffer) vkDestroyBuffer(device, buffer, nullptr);
            if (image) vkDestroyImage(device, image, nullptr);
            if (buffer_mem) vkFreeMemory(device, buffer_mem, nullptr);
            if (image_mem) vkFreeMemory(device, image_mem, nullptr);
            vkDestroyDevice(device, nullptr);
        }
        if (messenger) reinterpret_cast<PFN_vkDestroyDebugUtilsMessengerEXT>(
            vkGetInstanceProcAddr(instance, "vkDestroyDebugUtilsMessengerEXT"))(instance, messenger, nullptr);
        if (instance) vkDestroyInstance(instance, nullptr);
    }
};
int main(int argc, char** argv) {
    if (argc != 3) { std::cerr << "usage: linux_gpu_probe OUTPUT.ppm REPORT.json\n"; return 2; }
    VkPhysicalDeviceProperties props{};
    std::vector<VkExtensionProperties> extensions;
    std::string failure;
    bool pixels_ok = false, validation = false;
    unsigned queue_index = 0;
    try {
        Resources r;
        uint32_t count = 0;
        check(vkEnumerateInstanceLayerProperties(&count, nullptr));
        std::vector<VkLayerProperties> layers(count);
        check(vkEnumerateInstanceLayerProperties(&count, layers.data()));
        validation = std::any_of(layers.begin(), layers.end(), [](auto& p) {
            return std::string(p.layerName) == "VK_LAYER_KHRONOS_validation";
        });
        if (!validation) throw std::runtime_error("KHRONOS validation layer required");
        const char* layer = "VK_LAYER_KHRONOS_validation";
        const char* ext = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
        VkDebugUtilsMessengerCreateInfoEXT di{VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT};
        di.messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT;
        di.messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
        di.pfnUserCallback = debug;
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
        app.pApplicationName = "ACS original GPU preflight"; app.apiVersion = VK_API_VERSION_1_1;
        VkInstanceCreateInfo ii{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
        ii.pNext = &di; ii.pApplicationInfo = &app; ii.enabledLayerCount = 1; ii.ppEnabledLayerNames = &layer;
        ii.enabledExtensionCount = 1; ii.ppEnabledExtensionNames = &ext;
        check(vkCreateInstance(&ii, nullptr, &r.instance));
        auto create_debug = reinterpret_cast<PFN_vkCreateDebugUtilsMessengerEXT>(vkGetInstanceProcAddr(r.instance, "vkCreateDebugUtilsMessengerEXT"));
        if (!create_debug) throw std::runtime_error("debug utils unavailable");
        check(create_debug(r.instance, &di, nullptr, &r.messenger));
        check(vkEnumeratePhysicalDevices(r.instance, &count, nullptr));
        std::vector<VkPhysicalDevice> devices(count);
        check(vkEnumeratePhysicalDevices(r.instance, &count, devices.data()));
        VkPhysicalDevice physical{};
        for (auto d : devices) {
            VkPhysicalDeviceProperties p{}; vkGetPhysicalDeviceProperties(d, &p);
            if (p.vendorID == 0x10de && p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) { physical = d; props = p; break; }
        }
        if (!physical) throw std::runtime_error("No discrete NVIDIA Vulkan device; software fallback rejected");
        check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, nullptr));
        extensions.resize(count); check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, extensions.data()));
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, nullptr);
        std::vector<VkQueueFamilyProperties> queues(count); vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, queues.data());
        for (queue_index = 0; queue_index < count; ++queue_index) if (queues[queue_index].queueFlags & VK_QUEUE_GRAPHICS_BIT) break;
        if (queue_index == count) throw std::runtime_error("No graphics queue");
        float priority = 1;
        VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
        qi.queueFamilyIndex = queue_index; qi.queueCount = 1; qi.pQueuePriorities = &priority;
        VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dci.queueCreateInfoCount = 1; dci.pQueueCreateInfos = &qi;
        check(vkCreateDevice(physical, &dci, nullptr, &r.device));
        VkQueue queue{}; vkGetDeviceQueue(r.device, queue_index, 0, &queue);
        VkPhysicalDeviceMemoryProperties memory{}; vkGetPhysicalDeviceMemoryProperties(physical, &memory);
        auto allocate = [&](VkMemoryRequirements req, VkMemoryPropertyFlags flags, VkDeviceMemory& out) {
            uint32_t i = 0;
            for (; i < memory.memoryTypeCount; ++i) if ((req.memoryTypeBits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) break;
            if (i == memory.memoryTypeCount) throw std::runtime_error("No compatible memory type");
            VkMemoryAllocateInfo a{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; a.allocationSize = req.size; a.memoryTypeIndex = i;
            check(vkAllocateMemory(r.device, &a, nullptr, &out));
        };
        constexpr uint32_t width = 64, height = 64, bytes = width * height * 4;
        VkImageCreateInfo im{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        im.imageType = VK_IMAGE_TYPE_2D; im.format = VK_FORMAT_R8G8B8A8_UNORM; im.extent = {width, height, 1};
        im.mipLevels = im.arrayLayers = 1; im.samples = VK_SAMPLE_COUNT_1_BIT; im.tiling = VK_IMAGE_TILING_OPTIMAL;
        im.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        check(vkCreateImage(r.device, &im, nullptr, &r.image));
        VkMemoryRequirements req{}; vkGetImageMemoryRequirements(r.device, r.image, &req);
        allocate(req, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, r.image_mem); check(vkBindImageMemory(r.device, r.image, r.image_mem, 0));
        VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO}; bi.size = bytes; bi.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        check(vkCreateBuffer(r.device, &bi, nullptr, &r.buffer)); vkGetBufferMemoryRequirements(r.device, r.buffer, &req);
        allocate(req, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, r.buffer_mem);
        check(vkBindBufferMemory(r.device, r.buffer, r.buffer_mem, 0));
        VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pi.queueFamilyIndex = queue_index;
        check(vkCreateCommandPool(r.device, &pi, nullptr, &r.pool));
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; ai.commandPool = r.pool; ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; ai.commandBufferCount = 1;
        VkCommandBuffer cmd{}; check(vkAllocateCommandBuffers(r.device, &ai, &cmd));
        VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; check(vkBeginCommandBuffer(cmd, &begin));
        VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
        barrier.srcQueueFamilyIndex = barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.image = r.image; barrier.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED; barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
        VkClearColorValue color{{1, 0, 0, 1}};
        vkCmdClearColorImage(cmd, r.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &color, 1, &barrier.subresourceRange);
        barrier.oldLayout = barrier.newLayout; barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; barrier.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
        VkBufferImageCopy copy{}; copy.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}; copy.imageExtent = {width, height, 1};
        vkCmdCopyImageToBuffer(cmd, r.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, r.buffer, 1, &copy);
        VkBufferMemoryBarrier host{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER}; host.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; host.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
        host.srcQueueFamilyIndex = host.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED; host.buffer = r.buffer; host.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &host, 0, nullptr);
        check(vkEndCommandBuffer(cmd));
        VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.commandBufferCount = 1; submit.pCommandBuffers = &cmd;
        check(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE)); check(vkQueueWaitIdle(queue));
        void* mapped{}; check(vkMapMemory(r.device, r.buffer_mem, 0, bytes, 0, &mapped));
        const auto* p = static_cast<const uint8_t*>(mapped);
        pixels_ok = true;
        for (uint32_t i = 0; i < bytes; i += 4) if (p[i] != 255 || p[i+1] != 0 || p[i+2] != 0 || p[i+3] != 255) pixels_ok = false;
        if (pixels_ok) {
            std::ofstream ppm(argv[1], std::ios::binary); ppm << "P6\n64 64\n255\n";
            for (uint32_t i = 0; i < bytes; i += 4) ppm.write(reinterpret_cast<const char*>(p+i), 3);
            if (!ppm) throw std::runtime_error("Cannot write capture");
        }
        vkUnmapMemory(r.device, r.buffer_mem);
        if (!pixels_ok) throw std::runtime_error("GPU readback pixel mismatch");
    } catch (const std::exception& e) { failure = e.what(); }
    bool ok = failure.empty() && pixels_ok && errors == 0;
    std::ofstream report(argv[2]);
    report << "{\n  \"schema\":1,\"success\":" << (ok ? "true" : "false")
        << ",\"device\":" << quote(props.deviceName) << ",\"vendor_id\":" << props.vendorID
        << ",\"device_id\":" << props.deviceID << ",\"api_version\":" << props.apiVersion
        << ",\"driver_version_raw\":" << props.driverVersion << ",\"graphics_queue_family\":" << queue_index
        << ",\"validation_enabled\":" << (validation ? "true" : "false") << ",\"validation_errors\":" << errors.load()
        << ",\"pixels_checked\":" << (pixels_ok ? 4096 : 0) << ",\"expected_rgba\":[255,0,0,255],\"capture\":" << quote(argv[1])
        << ",\"mode\":\"offscreen_device_image_clear_readback\",\"presentation_verified\":false,\"failure\":" << quote(failure) << ",\"device_extensions\":[";
    for (size_t i = 0; i < extensions.size(); ++i) report << (i ? "," : "") << quote(extensions[i].extensionName);
    report << "]\n}\n";
    if (!report) return 1;
    std::cout << (ok ? "PASS: NVIDIA clear + 4096 RGBA pixel readbacks, zero validation errors" : "FAIL: " + failure) << '\n';
    return ok ? 0 : 1;
}
