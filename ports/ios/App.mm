// Original UIKit/Metal/input host adopted from IOS-HOST-002 (9ae75b0).
// IOS-LAUNCH-RESCUE-026 creates a fresh bundle and explicit scene configuration.
#import <UIKit/UIKit.h>
#import <MetalKit/MetalKit.h>
#import <TargetConditionals.h>
#include "InputBridge.h"
#include <array>
#include <algorithm>
#include <cmath>
#include <mutex>
#include <unordered_map>
#include <cstdint>
#include <cstdlib>
#include <exception>
#if defined(NX_IOS_RUNTIME)
#include <nx/runtime.h>
#include "platform.h"
namespace nx { void boot(); }
#endif

#if defined(NX_IOS_RUNTIME)
// BEGIN WINDOW STATE: UIKit-free core, also executed by the threaded fixture.
namespace {
struct ACSWindowSnapshot {
    void* window = nullptr;
    void* layer = nullptr;
    uint64_t generation = 0;
    bool minimized = true;
    uint32_t width = 0, height = 0, screenWidth = 0, screenHeight = 0;
};
class ACSWindowState {
    std::mutex mutex;
    ACSWindowSnapshot state;
    struct Lease { size_t count; void* layer; };
    std::unordered_map<void*, Lease> leases;
    void (*retain)(void*);
    void (*release)(void*);
public:
    ACSWindowState(void (*r)(void*), void (*d)(void*)) : retain(r), release(d) {}
    void publish(void* window, bool active, uint32_t w, uint32_t h, uint32_t sw, uint32_t sh, void* layer = nullptr) {
        void* old = nullptr; void* oldLayer = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (state.window != window || state.layer != layer) {
                if (window) retain(window);
                if (layer) retain(layer);
                old = state.window; oldLayer = state.layer; state.layer = layer;
                state.window = window;
                ++state.generation;
            }
            state.minimized = !window || !active || !w || !h;
            state.width = window ? w : 0; state.height = window ? h : 0;
            state.screenWidth = window ? sw : 0; state.screenHeight = window ? sh : 0;
        }
        if (old) release(old);
        if (oldLayer) release(oldLayer);
    }
    ACSWindowSnapshot read() { std::lock_guard<std::mutex> lock(mutex); return state; }
    void* acquire() {
        std::lock_guard<std::mutex> lock(mutex);
        if (state.minimized) return nullptr;
        auto existing = leases.find(state.window);
        // A UIWindow can reconnect with a new layer while an old lease survives.
        // Pointer-only public handles cannot distinguish those generations.
        if (existing != leases.end() && existing->second.layer != state.layer) return nullptr;
        retain(state.window);
        if (state.layer) retain(state.layer);
        auto& lease = leases[state.window]; ++lease.count; lease.layer = state.layer;
        return state.window;
    }
    void* acquireLayer(void* window) {
        std::lock_guard<std::mutex> lock(mutex);
        auto it = leases.find(window);
        if (state.minimized || state.window != window || it == leases.end() || !it->second.layer || it->second.layer != state.layer) return nullptr;
        retain(it->second.layer); return it->second.layer;
    }
    bool relinquish(void* window) {
        if (!window) return true;
        void* layer = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex);
            auto it = leases.find(window);
            if (it == leases.end()) return false;
            layer = it->second.layer;
            if (!--it->second.count) leases.erase(it);
        }
        release(window); if (layer) release(layer); return true;
    }
};
} // namespace
// END WINDOW STATE
static void retainWindow(void* p) { CFRetain(static_cast<CFTypeRef>(p)); }
static void releaseWindow(void* p) {
    // A last guest lease may outlive the scene. Final UIKit destruction stays on main.
    if (NSThread.isMainThread) CFRelease(static_cast<CFTypeRef>(p));
    else dispatch_async(dispatch_get_main_queue(), ^{ CFRelease(static_cast<CFTypeRef>(p)); });
}
static ACSWindowState& windowState() {
    // Process-lifetime state avoids teardown racing an owned guest worker.
    static auto* state = new ACSWindowState(retainWindow, releaseWindow);
    return *state;
}
static bool sceneActive = false; // main-thread lifecycle intent, including will-resign ordering
// Main owns attachment and geometry. Guest callers only consume retained snapshots.
static CAMetalLayer* sceneLayer;
static __weak UIWindow* layerWindow;
static void publishWindow(UIWindow* window, bool active) {
    if (!NSThread.isMainThread) std::terminate(); // Enforced in release builds too.
    if (!window) {
        [sceneLayer removeFromSuperlayer]; sceneLayer = nil; layerWindow = nil;
        windowState().publish(nullptr, false, 0, 0, 0, 0); return;
    }
    if (layerWindow != window) {
        [sceneLayer removeFromSuperlayer]; sceneLayer = [CAMetalLayer layer]; layerWindow = window;
        sceneLayer.opaque = YES;
    }
    UIView* view = window.rootViewController.view;
    if (sceneLayer.superlayer != view.layer) [view.layer insertSublayer:sceneLayer atIndex:0];
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    sceneLayer.frame = view.bounds; sceneLayer.contentsScale = window.screen.scale;
    sceneLayer.drawableSize = CGSizeMake(view.bounds.size.width * window.screen.scale, view.bounds.size.height * window.screen.scale);
    sceneLayer.hidden = !active;
    [CATransaction commit];
    const CGFloat scale = window.screen.scale;
    const CGSize size = view.bounds.size;
    const CGSize display = window.screen.nativeBounds.size;
    auto pixels = [](CGFloat n) { return uint32_t(std::clamp(std::round(double(n)), 0.0, double(UINT32_MAX))); };
    windowState().publish((__bridge void*)window,
        active && window.windowScene.activationState == UISceneActivationStateForegroundActive && !window.hidden,
        pixels(size.width * scale), pixels(size.height * scale),
        pixels(MAX(display.width, display.height)), pixels(MIN(display.width, display.height)), (__bridge void*)sceneLayer);
}
// BEGIN VULKAN ADAPTER
#define VK_USE_PLATFORM_METAL_EXT
#include <vulkan/vulkan.h>
extern "C" void* acs_vulkan_get_instance_proc_addr() { return reinterpret_cast<void*>(&vkGetInstanceProcAddr); }
extern "C" int acs_vulkan_create_surface(void* instance, void* window, uint64_t* surface, void* gipa) {
    if (!surface) return VK_ERROR_INITIALIZATION_FAILED;
    *surface = 0;
    if (!instance || !window || !gipa) return VK_ERROR_INITIALIZATION_FAILED;
    void* layer = windowState().acquireLayer(window);
    if (!layer) return VK_ERROR_SURFACE_LOST_KHR;
    auto get = reinterpret_cast<PFN_vkGetInstanceProcAddr>(gipa);
    auto create = reinterpret_cast<PFN_vkCreateMetalSurfaceEXT>(get(static_cast<VkInstance>(instance), "vkCreateMetalSurfaceEXT"));
    auto destroy = reinterpret_cast<PFN_vkDestroySurfaceKHR>(get(static_cast<VkInstance>(instance), "vkDestroySurfaceKHR"));
    VkResult result = VK_ERROR_EXTENSION_NOT_PRESENT;
    if (create && destroy) {
        VkMetalSurfaceCreateInfoEXT ci{VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT};
        ci.pLayer = (__bridge CAMetalLayer*)layer;
        VkSurfaceKHR created = VK_NULL_HANDLE;
        result = create(static_cast<VkInstance>(instance), &ci, nullptr, &created);
        if (result == VK_SUCCESS) {
            auto current = windowState().read();
            if (current.minimized || current.window != window || current.layer != layer) {
                destroy(static_cast<VkInstance>(instance), created, nullptr);
                result = VK_ERROR_SURFACE_LOST_KHR;
            } else *surface = reinterpret_cast<uint64_t>(created);
        }
    }
    // MoltenVK's MVKSurface retains pLayer. Release only our temporary reference.
    releaseWindow(layer);
    return result;
}
// END VULKAN ADAPTER
namespace nx::plat {
void* create_window() {
    void* window = windowState().acquire();
    if (!window) nx::fatal("iOS native window unavailable (scene inactive or disconnected)");
    return window; // window and layer leased together until release_window
}
void release_window(void* window) {
    if (!windowState().relinquish(window)) nx::fatal("iOS release_window: unknown or already released handle");
}
uint64_t window_generation() { return windowState().read().generation; }
bool window_minimized() { return windowState().read().minimized; }
void window_size(uint32_t& w, uint32_t& h) { auto s = windowState().read(); w = s.width; h = s.height; }
void screen_size(uint32_t& w, uint32_t& h) { auto s = windowState().read(); w = s.screenWidth; h = s.screenHeight; }
}
#endif

static NSString* documents() {
    return NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
}
static NSString* evidenceRun() {
    NSArray<NSString*>* args = NSProcessInfo.processInfo.arguments;
    NSUInteger index = [args indexOfObject:@"--evidence-run"];
    return index != NSNotFound && index+1 < args.count ? args[index+1] : @"manual-launch";
}
// Durable launch stages distinguish UIKit/Metal startup from simctl's launch RPC.
static void startup(NSString* stage) {
    static std::mutex journal;
    std::lock_guard<std::mutex> lock(journal);
    NSDictionary* entry = @{@"stage":stage, @"uptime":@(NSProcessInfo.processInfo.systemUptime),
                            @"pid":@(NSProcessInfo.processInfo.processIdentifier), @"evidence_run":evidenceRun()};
#if defined(NX_IOS_RUNTIME)
    auto snapshot = windowState().read();
    NSMutableDictionary* measured = [entry mutableCopy];
    measured[@"window_state"] = @{@"generation":@(snapshot.generation), @"minimized":@(snapshot.minimized),
        @"pixels":@[@(snapshot.width),@(snapshot.height)],
        @"screen_pixels":@[@(snapshot.screenWidth),@(snapshot.screenHeight)],
        @"main_thread":@(NSThread.isMainThread)};
    entry = measured;
#endif
    NSData* data = [NSJSONSerialization dataWithJSONObject:entry options:0 error:nil];
    NSString* path = [documents() stringByAppendingPathComponent:@"startup.jsonl"];
    NSFileHandle* file = [NSFileHandle fileHandleForWritingAtPath:path];
    if (!file) { [[NSData data] writeToFile:path atomically:YES]; file = [NSFileHandle fileHandleForWritingAtPath:path]; }
    if ([file seekToEndOfFile] < 1024 * 1024) {
        [file writeData:data]; [file writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    }
    [file closeFile];
}
static NSDictionary* inputJSON() {
    const auto s = acs_input_poll();
    return @{@"abi_version": @(s.abi_version), @"buttons": @(s.buttons),
             @"left": @[@(s.left_x), @(s.left_y)], @"right": @[@(s.right_x), @(s.right_y)],
             @"triggers": @[@(s.left_trigger), @(s.right_trigger)],
             @"active_touches": @(s.active_touches), @"sequence": @(s.sequence)};
}
static void writeJSON(NSString* file, NSDictionary* value) {
    NSData* data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:[documents() stringByAppendingPathComponent:file] atomically:YES];
}

// Switch-style on-screen controller (docs/ASTRAL_IOS_SIM.md): semi-transparent sticks, D-pad, A/B/X/Y, L/R/ZL/ZR,
// +/-, stick clicks, and a HIDE/PAD toggle. Touches that start on no control (or any touch while hidden) are
// touch-screen points for nn::hid::GetTouchScreenState (InputBridge acs_touch_*).
@interface ACSOverlay : UIView {
    std::array<CGRect, ACS_CONTROL_COUNT> _regions;
    CGRect _toggle;
    NSMutableDictionary<NSValue*, NSArray<NSNumber*>*>* _identities;
    NSMutableDictionary<NSValue*, NSNumber*>* _screenTouches;
    NSMutableSet<NSValue*>* _toggleTouches;
    uint64_t _nextIdentity;
    CGSize _lastSize;
}
@property(nonatomic) uint64_t touchEvents;
@property(nonatomic) uint64_t resets;
@property(nonatomic) uint64_t screenTouchesBegun;
@property(nonatomic) BOOL controlsHidden;
@property(nonatomic, copy) NSString* lastReset;
- (void)releaseInput:(NSString*)reason;
@end
@implementation ACSOverlay
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.opaque = NO; self.backgroundColor = UIColor.clearColor;
        self.multipleTouchEnabled = YES;
        self.accessibilityIdentifier = @"acs-controller-overlay";
        _identities = [NSMutableDictionary dictionary];
        _screenTouches = [NSMutableDictionary dictionary];
        _toggleTouches = [NSMutableSet set];
        _lastReset = @"startup";
        const char* shown = std::getenv("NX_IOS_OVERLAY");
        _controlsHidden = shown && shown[0] == '0';
        self.accessibilityLabel = @"Virtual controller. Left and right sticks, D-pad, A B X Y, L R ZL ZR, plus and minus.";
    }
    return self;
}
- (void)record:(NSString*)event {
    NSDictionary* entry = @{@"event": event, @"input": inputJSON(), @"ui_touch_events": @(_touchEvents),
                            @"resets": @(_resets), @"last_reset": _lastReset ?: @"startup",
                            @"bindings":_identities.allValues, @"screen_touches":@(_screenTouches.count),
                            @"screen_touches_begun":@(_screenTouchesBegun), @"controls_hidden":@(_controlsHidden),
                            @"uptime":@(NSProcessInfo.processInfo.systemUptime), @"pid":@(NSProcessInfo.processInfo.processIdentifier), @"evidence_run":evidenceRun()};
    writeJSON(@"input-state.json", entry);
    // A bounded original diagnostic journal, no game or account data.
    NSString* path = [documents() stringByAppendingPathComponent:@"input-events.jsonl"];
    NSData* data = [NSJSONSerialization dataWithJSONObject:entry options:0 error:nil];
    NSFileHandle* file = [NSFileHandle fileHandleForWritingAtPath:path];
    if (!file) { [[NSData data] writeToFile:path atomically:YES]; file = [NSFileHandle fileHandleForWritingAtPath:path]; }
    if ([file seekToEndOfFile] < 1024 * 1024) { [file writeData:data]; [file writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]]; }
    [file closeFile];
    [self setNeedsDisplay];
}
- (void)releaseInput:(NSString*)reason {
    acs_input_release_all(); [_identities removeAllObjects]; [_screenTouches removeAllObjects]; [_toggleTouches removeAllObjects];
    ++_resets; _lastReset = reason;
    [self record:reason];
}
- (void)layoutSubviews {
    [super layoutSubviews];
    if (!CGSizeEqualToSize(_lastSize, self.bounds.size)) {
        [self releaseInput:@"layout-size-change"]; _lastSize = self.bounds.size;
    }
    CGRect safe = UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets);
    // One unit: a tenth of the usable height, capped so the iPad layout keeps phone-sized thumbs.
    const CGFloat u = MIN(CGRectGetHeight(safe), 420) / 10;
    const CGFloat lo = CGRectGetMinX(safe) + .4 * u, hi = CGRectGetMaxX(safe) - .4 * u;
    const CGFloat top = CGRectGetMinY(safe) + .3 * u, bottom = CGRectGetMaxY(safe) - .3 * u;
    const CGFloat mid = CGRectGetMidX(safe);
    auto circle = [](CGFloat x, CGFloat y, CGFloat r) { return CGRectMake(x - r, y - r, 2 * r, 2 * r); };
    // Left: stick above, D-pad below and inward (Joy-Con L). Right: A/B/X/Y above, stick below and inward.
    const CGFloat stickR = 1.55 * u;
    _regions[ACS_STICK_LEFT] = circle(lo + 1.9 * u, bottom - 5.0 * u, stickR);
    _regions[ACS_STICK_RIGHT] = circle(hi - 4.3 * u, bottom - 1.75 * u, stickR);
    const CGFloat dx = lo + 4.3 * u, dy = bottom - 1.75 * u, d = 1.0 * u, ds = .5 * u;
    _regions[ACS_DPAD_UP] = circle(dx, dy - d, ds);
    _regions[ACS_DPAD_DOWN] = circle(dx, dy + d, ds);
    _regions[ACS_DPAD_LEFT] = circle(dx - d, dy, ds);
    _regions[ACS_DPAD_RIGHT] = circle(dx + d, dy, ds);
    const CGFloat fx = hi - 1.9 * u, fy = bottom - 5.0 * u, g = 1.1 * u, fr = .58 * u;
    _regions[ACS_A] = circle(fx + g, fy, fr);
    _regions[ACS_B] = circle(fx, fy + g, fr);
    _regions[ACS_X] = circle(fx, fy - g, fr);
    _regions[ACS_Y] = circle(fx - g, fy, fr);
    const CGFloat sw = 2.3 * u, sh = .85 * u;
    _regions[ACS_ZL] = CGRectMake(lo, top, sw, sh);
    _regions[ACS_L] = CGRectMake(lo, top + 1.05 * u, sw, sh);
    _regions[ACS_ZR] = CGRectMake(hi - sw, top, sw, sh);
    _regions[ACS_R] = CGRectMake(hi - sw, top + 1.05 * u, sw, sh);
    _regions[ACS_MINUS] = circle(mid - 2.2 * u, top + .45 * u, .42 * u);
    _regions[ACS_PLUS] = circle(mid + 2.2 * u, top + .45 * u, .42 * u);
    _regions[ACS_STICK_L_CLICK] = circle(lo + 1.0 * u, bottom - 1.0 * u, .42 * u);
    _regions[ACS_STICK_R_CLICK] = circle(hi - 1.0 * u, bottom - 1.0 * u, .42 * u);
    _toggle = CGRectMake(mid - .9 * u, top, 1.8 * u, .8 * u);
    [self setNeedsDisplay];
}
static NSString* controlName(int i) {
    static NSArray<NSString*>* names = @[@"L", @"R", @"A", @"B", @"X", @"Y", @"L", @"R", @"ZL", @"ZR", @"+", @"−",
                                         @"▲", @"▼", @"◀", @"▶", @"LS", @"RS"];
    return names[i];
}
- (void)drawLabel:(NSString*)text in:(CGRect)box size:(CGFloat)size alpha:(CGFloat)alpha {
    UIFont* font = [UIFont systemFontOfSize:size weight:UIFontWeightSemibold];
    NSDictionary* attrs = @{NSFontAttributeName:font, NSForegroundColorAttributeName:[UIColor colorWithWhite:1 alpha:alpha]};
    CGSize sz = [text sizeWithAttributes:attrs];
    [text drawAtPoint:CGPointMake(CGRectGetMidX(box) - sz.width / 2, CGRectGetMidY(box) - sz.height / 2) withAttributes:attrs];
}
- (void)drawRect:(CGRect)rect {
    (void)rect;
    const auto state = acs_input_poll();
    // The toggle is always drawn, faint while the controls are hidden.
    UIBezierPath* tog = [UIBezierPath bezierPathWithRoundedRect:_toggle cornerRadius:_toggle.size.height / 2];
    [[UIColor colorWithWhite:0 alpha:_controlsHidden ? .18 : .30] setFill]; [tog fill];
    [[UIColor colorWithWhite:1 alpha:_controlsHidden ? .30 : .45] setStroke]; tog.lineWidth = 1; [tog stroke];
    [self drawLabel:_controlsHidden ? @"PAD" : @"HIDE" in:_toggle size:_toggle.size.height * .42 alpha:_controlsHidden ? .45 : .75];
    if (_controlsHidden) return;
    for (int i = 0; i < ACS_CONTROL_COUNT; ++i) {
        CGRect box = _regions[i];
        const BOOL stick = i <= ACS_STICK_RIGHT;
        const BOOL shoulder = i >= ACS_L && i <= ACS_ZR;
        const BOOL held = stick ? (i == ACS_STICK_LEFT ? (state.left_x || state.left_y) : (state.right_x || state.right_y))
                                : ((state.buttons & ACS_BUTTON(i)) != 0);
        UIBezierPath* path = shoulder ? [UIBezierPath bezierPathWithRoundedRect:box cornerRadius:box.size.height / 2]
                                      : [UIBezierPath bezierPathWithOvalInRect:box];
        [[UIColor colorWithWhite:held ? .85 : 0 alpha:held ? .42 : .26] setFill]; [path fill];
        [[UIColor colorWithWhite:1 alpha:held ? .9 : .42] setStroke];
        path.lineWidth = held ? 2 : 1.25; [path stroke];
        if (stick) {
            const float x = i == ACS_STICK_LEFT ? state.left_x : state.right_x;
            const float y = i == ACS_STICK_LEFT ? state.left_y : state.right_y;
            const CGFloat range = box.size.width * .32, knobR = box.size.width * .22;
            CGRect knob = CGRectMake(CGRectGetMidX(box) + x * range - knobR, CGRectGetMidY(box) - y * range - knobR, 2 * knobR, 2 * knobR);
            UIBezierPath* k = [UIBezierPath bezierPathWithOvalInRect:knob];
            [[UIColor colorWithWhite:1 alpha:held ? .55 : .28] setFill]; [k fill];
            [[UIColor colorWithWhite:1 alpha:.5] setStroke]; k.lineWidth = 1; [k stroke];
            continue;
        }
        [self drawLabel:controlName(i) in:box size:MIN(box.size.height * .5, 22) alpha:held ? 1 : .8];
    }
}
// Stick deflection for a point, relative to the stick's centre and its travel (radius * .62).
- (CGPoint)deflection:(CGPoint)p control:(int)control {
    CGRect b = _regions[control];
    const CGFloat travel = b.size.width * .5 * .62;
    return CGPointMake((p.x - CGRectGetMidX(b)) / travel, (CGRectGetMidY(b) - p.y) / travel);
}
- (int)controlAt:(CGPoint)p {
    int best = -1;
    CGFloat bestDistance = CGFLOAT_MAX;
    for (int i = 0; i < ACS_CONTROL_COUNT; ++i) {
        // Small slop around each control; sticks take a larger catch area.
        const CGFloat slop = i <= ACS_STICK_RIGHT ? _regions[i].size.width * .2 : 6;
        if (!CGRectContainsPoint(CGRectInset(_regions[i], -slop, -slop), p)) continue;
        const CGFloat distance = std::hypot(p.x - CGRectGetMidX(_regions[i]), p.y - CGRectGetMidY(_regions[i]));
        if (distance < bestDistance) { bestDistance = distance; best = i; }
    }
    return best;
}
- (void)beginTouch:(UITouch*)touch {
    NSValue* key = [NSValue valueWithNonretainedObject:touch];
    CGPoint p = [touch locationInView:self];
    if (CGRectContainsPoint(CGRectInset(_toggle, -6, -6), p)) { [_toggleTouches addObject:key]; return; }
    const int control = _controlsHidden ? -1 : [self controlAt:p];
    if (control >= 0) {
        const uint64_t identity = ++_nextIdentity;
        CGPoint v = control <= ACS_STICK_RIGHT ? [self deflection:p control:control] : CGPointZero;
        if (acs_input_begin(identity, (ACSInputControl)control, v.x, v.y)) _identities[key] = @[@(identity), @(control)];
        return;
    }
    const CGSize size = self.bounds.size;
    if (size.width <= 0 || size.height <= 0) return;
    const uint64_t identity = ++_nextIdentity;
    if (acs_touch_begin(identity, p.x / size.width, p.y / size.height)) {
        _screenTouches[key] = @(identity); ++_screenTouchesBegun;
    }
}
- (void)moveTouch:(UITouch*)touch {
    NSValue* key = [NSValue valueWithNonretainedObject:touch];
    CGPoint p = [touch locationInView:self];
    if (NSNumber* screen = _screenTouches[key]) {
        const CGSize size = self.bounds.size;
        if (size.width > 0 && size.height > 0) acs_touch_move(screen.unsignedLongLongValue, p.x / size.width, p.y / size.height);
        return;
    }
    NSArray<NSNumber*>* binding = _identities[key];
    if (!binding) return;
    const int control = binding[1].intValue;
    if (control <= ACS_STICK_RIGHT) {
        CGPoint v = [self deflection:p control:control];
        acs_input_move(binding[0].unsignedLongLongValue, v.x, v.y);
    }
}
- (void)endTouch:(UITouch*)touch {
    NSValue* key = [NSValue valueWithNonretainedObject:touch];
    if ([_toggleTouches containsObject:key]) {
        [_toggleTouches removeObject:key];
        if (CGRectContainsPoint(CGRectInset(_toggle, -12, -12), [touch locationInView:self])) {
            _controlsHidden = !_controlsHidden;
            // Hiding drops held controls so nothing stays pressed; screen touches continue.
            for (NSArray<NSNumber*>* binding in _identities.allValues) acs_input_end(binding[0].unsignedLongLongValue);
            [_identities removeAllObjects];
            [self record:_controlsHidden ? @"controls-hidden" : @"controls-shown"];
        }
        return;
    }
    if (NSNumber* screen = _screenTouches[key]) { acs_touch_end(screen.unsignedLongLongValue); [_screenTouches removeObjectForKey:key]; }
    NSArray<NSNumber*>* binding = _identities[key];
    if (binding) acs_input_end(binding[0].unsignedLongLongValue);
    [_identities removeObjectForKey:key];
}
- (void)touchesBegan:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event; for (UITouch* t in touches) [self beginTouch:t];
    _touchEvents += touches.count; [self record:@"touch-began"];
}
- (void)touchesMoved:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event; for (UITouch* t in touches) [self moveTouch:t];
    _touchEvents += touches.count; [self setNeedsDisplay];
}
- (void)touchesEnded:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)event; for (UITouch* t in touches) [self endTouch:t];
    _touchEvents += touches.count; [self record:@"touch-ended"];
}
- (void)touchesCancelled:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
    (void)touches; (void)event; [self releaseInput:@"touch-cancelled"];
}
@end

@interface ACSHostController : UIViewController <MTKViewDelegate> {
    MTKView* _metal;
    id<MTLCommandQueue> _queue;
    id<MTLRenderPipelineState> _pipeline;
    ACSOverlay* _overlay;
    UILabel* _title;
    UILabel* _status;
    CFTimeInterval _started;
    uint64_t _submitted, _completed;
    BOOL _failed, _drawStarted;
}
- (void)setActive:(BOOL)active;
- (void)releaseForGeometryChange;
@end
@implementation ACSHostController
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (void)viewDidLoad {
    [super viewDidLoad];
#if defined(NX_IOS_RUNTIME)
    self.view.backgroundColor = UIColor.blackColor;
    _overlay = [[ACSOverlay alloc] initWithFrame:self.view.bounds];
    _overlay.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:_overlay];
    // The game's frames fill the view (CAMetalLayer under the overlay); no host captions over them.
    startup(@"guest-view-ready");
    return;
#endif
 startup(@"view-did-load");
    self.view.backgroundColor = UIColor.blackColor;
    _started = CACurrentMediaTime();
    startup(@"metal-device-begin");
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    startup(@"metal-device-ready");
    _metal = [[MTKView alloc] initWithFrame:self.view.bounds device:device];
    _metal.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    _metal.userInteractionEnabled = NO;
    _metal.colorPixelFormat = MTLPixelFormatBGRA8Unorm;
    _metal.preferredFramesPerSecond = 60;
    _queue = [device newCommandQueue];
    // Original analytic diagnostic only: no game assets, shaders or runtime.
    NSString* source = @R"METAL(
#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; float2 uv; };
vertex V vertexMain(uint i [[vertex_id]]) {
    float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)};
    V o; o.position=float4(p[i],0,1); o.uv=p[i]*.5+.5; return o;
}
fragment float4 fragmentMain(V in [[stage_in]], constant float4& data [[buffer(0)]]) {
    float2 uv=in.uv;
    float wave=.5+.15*sin(uv.x*15+data.x*1.6);
    float trace=1-smoothstep(.002,.006,abs(uv.y-wave));
    float cursor=1-smoothstep(.008,.014,length(uv-float2(.5+data.y*.18,.5+data.z*.18)));
    float sweep=exp(-90*abs(uv.x-fract(data.x*.12)));
    float3 color=float3(.018,.042,.061)+float3(.025,.06,.075)*uv.y;
    color+=trace*float3(.12,.68,.78)+cursor*float3(.88,.73,.28)+sweep*float3(.025,.06,.07);
    return float4(color,1);
}
)METAL";
    NSError* error = nil;
    startup(@"metal-library-begin");
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    startup(@"metal-library-ready");
    MTLRenderPipelineDescriptor* descriptor = [MTLRenderPipelineDescriptor new];
    descriptor.vertexFunction = [library newFunctionWithName:@"vertexMain"];
    descriptor.fragmentFunction = [library newFunctionWithName:@"fragmentMain"];
    descriptor.colorAttachments[0].pixelFormat = _metal.colorPixelFormat;
    startup(@"metal-pipeline-begin");
    _pipeline = library ? [device newRenderPipelineStateWithDescriptor:descriptor error:&error] : nil;
    startup(@"metal-pipeline-ready");
    if (!device || !_queue || !_pipeline) {
        _failed = YES;
        writeJSON(@"failure.json", @{@"error":error.localizedDescription ?: @"Metal unavailable"});
    }
    [self.view addSubview:_metal];
    _overlay = [[ACSOverlay alloc] initWithFrame:self.view.bounds];
    _overlay.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:_overlay];
    _title = [UILabel new]; _title.text = @"ACS · HOST PREFLIGHT";
    _title.font = [UIFont systemFontOfSize:23 weight:UIFontWeightBold];
    _title.textColor = UIColor.whiteColor; _title.textAlignment = NSTextAlignmentCenter;
    _title.adjustsFontSizeToFitWidth = YES;
    _title.userInteractionEnabled = NO; [self.view addSubview:_title];
    _status = [UILabel new];
    _status.font = [UIFont monospacedDigitSystemFontOfSize:12 weight:UIFontWeightMedium];
    _status.textColor = [UIColor colorWithRed:.75 green:.89 blue:.93 alpha:1];
    _status.numberOfLines = 2; _status.textAlignment = NSTextAlignmentCenter;
    _status.userInteractionEnabled = NO; [self.view addSubview:_status];
    _metal.delegate = self; startup(@"view-ready");
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
#if defined(NX_IOS_RUNTIME)
    publishWindow(self.view.window, sceneActive);
#endif
    CGRect safe = UIEdgeInsetsInsetRect(self.view.bounds, self.view.safeAreaInsets);
    _title.frame = CGRectMake(safe.origin.x+16, safe.origin.y+12, safe.size.width-32,30);
    _status.frame = CGRectMake(safe.origin.x+16,safe.origin.y+44,safe.size.width-32,34);
}
- (void)viewWillTransitionToSize:(CGSize)size withTransitionCoordinator:(id<UIViewControllerTransitionCoordinator>)coordinator {
    [_overlay releaseInput:@"orientation-change"];
    [super viewWillTransitionToSize:size withTransitionCoordinator:coordinator];
}
- (void)releaseForGeometryChange { [_overlay releaseInput:@"scene-geometry-change"]; }
- (void)setActive:(BOOL)active {
    [_overlay releaseInput:active ? @"foreground" : @"background-or-inactive"];
    _overlay.userInteractionEnabled = active;
    _metal.paused = !active;
}
- (void)mtkView:(MTKView*)view drawableSizeWillChange:(CGSize)size { (void)view; (void)size; }
- (void)drawInMTKView:(MTKView*)view {
    if (_failed) return;
    if (!_drawStarted) { _drawStarted = YES; startup(@"first-draw"); }
    MTLRenderPassDescriptor* pass = view.currentRenderPassDescriptor;
    id<CAMetalDrawable> drawable = view.currentDrawable;
    if (!pass || !drawable) return;
    const auto input = acs_input_poll();
    float data[4] = {(float)(CACurrentMediaTime()-_started), input.left_x, input.left_y, 0};
    id<MTLCommandBuffer> buffer = [_queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder = [buffer renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:_pipeline];
    [encoder setFragmentBytes:data length:sizeof(data) atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [encoder endEncoding]; [buffer presentDrawable:drawable];
    ++_submitted;
    __weak ACSHostController* weakSelf = self;
    [buffer addCompletedHandler:^(id<MTLCommandBuffer> finished) {
        BOOL ok = finished.status == MTLCommandBufferStatusCompleted;
        NSString* message = finished.error.localizedDescription;
        dispatch_async(dispatch_get_main_queue(), ^{
            ACSHostController* host = weakSelf;
            if (!host) return;
            if (!ok) {
                host->_failed = YES;
                writeJSON(@"failure.json", @{@"error":message ?: @"GPU completion failed"});
                return;
            }
            ++host->_completed;
            if (host->_completed == 1) startup(@"first-gpu-completed");
            if (host->_completed % 30 == 0) {
                auto s = acs_input_poll();
                host->_status.text = [NSString stringWithFormat:@"Original Metal diagnostic · no game runtime\nGPU frames %llu · touches %u · buttons 0x%03x", (unsigned long long)host->_completed, s.active_touches, s.buttons];
            }
            if (host->_completed % 60 == 0) {
                UIEdgeInsets insets = host.view.safeAreaInsets;
                NSDictionary* report = @{@"kind":@"original_metal_host_preflight", @"game_runtime_integrated":@NO, @"evidence_run":evidenceRun(),
                    @"pid":@(NSProcessInfo.processInfo.processIdentifier), @"bundle":NSBundle.mainBundle.bundleIdentifier,
                    @"simulator":@(TARGET_OS_SIMULATOR), @"runtime":UIDevice.currentDevice.systemVersion,
                    @"model":UIDevice.currentDevice.model, @"minimum_target":@"26.0", @"gpu":view.device.name ?: @"unknown",
                    @"completed_gpu_frames":@(host->_completed), @"submitted_frames":@(host->_submitted),
                    @"drawable_size":@[@(view.drawableSize.width),@(view.drawableSize.height)],
                    @"view_size":@[@(host.view.bounds.size.width),@(host.view.bounds.size.height)],
                    @"safe_area":@[@(insets.top),@(insets.left),@(insets.bottom),@(insets.right)],
                    @"input":inputJSON(), @"ui_touch_events":@(host->_overlay.touchEvents),
                    @"last_reset":host->_overlay.lastReset ?: @"startup"};
                writeJSON(@"completed.json", report);
            }
        });
    }];
    [buffer commit];
}
@end

@interface ACSSceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(nonatomic, strong) UIWindow* window;
@end
@implementation ACSSceneDelegate
@synthesize window = _window;
- (void)setWindow:(UIWindow*)window {
    _window = window;
#if defined(NX_IOS_RUNTIME)
    publishWindow(window, sceneActive);
#endif
}
- (void)sampleWindow:(BOOL)active {
#if defined(NX_IOS_RUNTIME)
    sceneActive = active; publishWindow(self.window, active);
#else
    (void)active;
#endif
}
- (void)scene:(UIScene*)scene willConnectToSession:(UISceneSession*)session options:(UISceneConnectionOptions*)options {
    (void)session; (void)options;
    startup(@"scene-connect");
    if (![scene isKindOfClass:UIWindowScene.class]) return;
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene*)scene];
    self.window.rootViewController = [ACSHostController new];
    [self.window makeKeyAndVisible]; [self sampleWindow:NO]; startup(@"window-visible");
}
- (void)windowScene:(UIWindowScene*)scene didUpdateEffectiveGeometry:(UIWindowSceneGeometry*)previous {
    (void)scene; (void)previous;
#if defined(NX_IOS_RUNTIME)
    [self sampleWindow:sceneActive];
#endif
    [(ACSHostController*)self.window.rootViewController releaseForGeometryChange];
}
- (void)sceneDidBecomeActive:(UIScene*)scene {
    (void)scene; [self sampleWindow:YES]; startup(@"scene-active"); [(ACSHostController*)self.window.rootViewController setActive:YES];
#if defined(NX_IOS_RUNTIME)
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSString* log = [documents() stringByAppendingPathComponent:@"guest.log"];
        setenv("NX_LOG", log.fileSystemRepresentation, 1);
        nx::plat::start_memory_guard();
        nx::plat::start_thread([](void*) {
            @autoreleasepool {
                startup(@"nx-boot-enter");
                dispatch_async(dispatch_get_main_queue(), ^{ startup(@"ui-responsive-during-boot"); });
                try { nx::boot(); startup(@"nx-boot-return"); }
                catch (const nx::LongJmp& j) { nx::fatal("iOS unmatched longjmp %llx", (unsigned long long)j.buf); }
                catch (const std::exception& e) { nx::fatal("iOS host exception: %s", e.what()); }
            }
        }, nullptr, 64ull << 20);
    });
#endif

}
- (void)sceneWillResignActive:(UIScene*)scene {
    (void)scene; [self sampleWindow:NO]; startup(@"scene-inactive"); [(ACSHostController*)self.window.rootViewController setActive:NO];
}
- (void)sceneDidEnterBackground:(UIScene*)scene {
    [self sampleWindow:NO]; startup(@"scene-background"); (void)scene; [(ACSHostController*)self.window.rootViewController setActive:NO];
}
- (void)sceneWillEnterForeground:(UIScene*)scene {
    (void)scene; [self sampleWindow:NO]; startup(@"scene-foreground");
}
- (void)sceneDidDisconnect:(UIScene*)scene {
    [(ACSHostController*)self.window.rootViewController setActive:NO];
    [self sampleWindow:NO]; self.window.hidden = YES;
    self.window = nil;
    startup(@"scene-disconnect"); (void)scene;
}
@end
@interface ACSAppDelegate : UIResponder <UIApplicationDelegate>
@end
@implementation ACSAppDelegate
- (UISceneConfiguration*)application:(UIApplication*)application
    configurationForConnectingSceneSession:(UISceneSession*)session options:(UISceneConnectionOptions*)options {
    (void)application; (void)options; startup(@"scene-configuration");
    UISceneConfiguration* configuration = [[UISceneConfiguration alloc] initWithName:@"ACS Host" sessionRole:session.role];
    configuration.sceneClass = UIWindowScene.class;
    configuration.delegateClass = ACSSceneDelegate.class;
    return configuration;
}
- (BOOL)application:(UIApplication*)app didFinishLaunchingWithOptions:(NSDictionary*)options {
    (void)options; startup(@"did-finish-launching");
    dispatch_async(dispatch_get_main_queue(), ^{
        startup([NSString stringWithFormat:@"main-runloop-ready sessions=%lu connected=%lu", (unsigned long)app.openSessions.count, (unsigned long)app.connectedScenes.count]);
    });
    acs_input_release_all(); return YES;
}
@end
int main(int argc, char** argv) {
    @autoreleasepool { startup(@"main"); return UIApplicationMain(argc, argv, nil, NSStringFromClass(ACSAppDelegate.class)); }
}
