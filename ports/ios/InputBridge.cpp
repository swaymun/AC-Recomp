#include "InputBridge.h"
#include <algorithm>
#include <cmath>
#include <map>
#include <mutex>
#include <vector>

namespace {
struct Touch { ACSInputControl control; float x, y; };
struct Point { uint64_t id; float x, y; };
std::mutex lock;
std::map<uint64_t, Touch> touches;
std::vector<Point> points;  // touch-screen points, in the order they began
uint64_t sequence = 0;
void normalize(float& x, float& y) {
    if (!std::isfinite(x) || !std::isfinite(y)) { x = y = 0; return; }
    const double length = std::hypot(static_cast<double>(x), static_cast<double>(y));
    if (length > 1) { x = static_cast<float>(x / length); y = static_cast<float>(y / length); }
}
float unit(float v) { return std::clamp(v, 0.0f, 1.0f); }
std::vector<Point>::iterator find_point(uint64_t id) {
    return std::find_if(points.begin(), points.end(), [id](const Point& p) { return p.id == id; });
}
}
extern "C" int acs_input_begin(uint64_t id, ACSInputControl control, float x, float y) {
    std::lock_guard<std::mutex> guard(lock);
    if (control < ACS_STICK_LEFT || control >= ACS_CONTROL_COUNT || touches.count(id) || touches.size() >= 32) return 0;
    if (control <= ACS_STICK_RIGHT)
        for (const auto& entry : touches) if (entry.second.control == control) return 0;
    normalize(x, y);
    touches.emplace(id, Touch{control, x, y});
    ++sequence;
    return 1;
}
extern "C" void acs_input_move(uint64_t id, float x, float y) {
    std::lock_guard<std::mutex> guard(lock);
    auto it = touches.find(id);
    if (it == touches.end()) return;
    normalize(x, y);
    it->second.x = x; it->second.y = y; ++sequence;
}
extern "C" void acs_input_end(uint64_t id) {
    std::lock_guard<std::mutex> guard(lock);
    if (touches.erase(id)) ++sequence;
}
extern "C" void acs_input_release_all() {
    std::lock_guard<std::mutex> guard(lock);
    touches.clear(); points.clear(); ++sequence;
}
extern "C" ACSInputState acs_input_poll() {
    std::lock_guard<std::mutex> guard(lock);
    ACSInputState out{};
    out.abi_version = ACS_INPUT_ABI_VERSION; out.sequence = sequence;
    out.active_touches = static_cast<uint32_t>(touches.size() + points.size());
    for (const auto& entry : touches) {
        const auto& t = entry.second;
        if (t.control == ACS_STICK_LEFT) { out.left_x = t.x; out.left_y = t.y; }
        else if (t.control == ACS_STICK_RIGHT) { out.right_x = t.x; out.right_y = t.y; }
        else out.buttons |= ACS_BUTTON(t.control);
    }
    out.left_trigger = (out.buttons & ACS_BUTTON(ACS_ZL)) ? 1.f : 0.f;
    out.right_trigger = (out.buttons & ACS_BUTTON(ACS_ZR)) ? 1.f : 0.f;
    return out;
}
extern "C" int acs_touch_begin(uint64_t id, float x, float y) {
    std::lock_guard<std::mutex> guard(lock);
    if (!std::isfinite(x) || !std::isfinite(y) || points.size() >= ACS_TOUCH_MAX || find_point(id) != points.end())
        return 0;
    points.push_back(Point{id, unit(x), unit(y)});
    ++sequence;
    return 1;
}
extern "C" void acs_touch_move(uint64_t id, float x, float y) {
    std::lock_guard<std::mutex> guard(lock);
    auto it = find_point(id);
    if (it == points.end() || !std::isfinite(x) || !std::isfinite(y)) return;
    it->x = unit(x); it->y = unit(y); ++sequence;
}
extern "C" void acs_touch_end(uint64_t id) {
    std::lock_guard<std::mutex> guard(lock);
    auto it = find_point(id);
    if (it == points.end()) return;
    points.erase(it); ++sequence;
}
extern "C" size_t acs_touch_poll(ACSTouchPoint* out, size_t max) {
    std::lock_guard<std::mutex> guard(lock);
    size_t n = std::min(max, points.size());
    for (size_t k = 0; k < n; ++k) out[k] = ACSTouchPoint{points[k].id, points[k].x, points[k].y};
    return n;
}
