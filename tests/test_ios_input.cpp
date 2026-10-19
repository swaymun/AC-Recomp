#include "../ports/ios/InputBridge.h"
#include <atomic>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <limits>
#include <thread>

static void neutral() {
    auto s = acs_input_poll();
    assert(s.abi_version == ACS_INPUT_ABI_VERSION && s.buttons == 0 && s.active_touches == 0);
    assert(s.left_x == 0 && s.left_y == 0 && s.right_x == 0 && s.right_y == 0);
    assert(s.left_trigger == 0 && s.right_trigger == 0);
}
int main() {
    acs_input_release_all(); neutral();
    // A second stick and trigger must not steal the first stick's identity.
    assert(acs_input_begin(60, ACS_STICK_LEFT, -.4f, .8f));
    assert(acs_input_begin(61, ACS_STICK_RIGHT, .2f, -.9f));
    assert(acs_input_begin(62, ACS_ZL, 0, 0));
    acs_input_end(61); auto s = acs_input_poll();
    assert(s.active_touches == 2 && s.right_x == 0 && s.right_y == 0);
    assert(s.left_x == -.4f && s.left_y == .8f && s.left_trigger == 1);
    acs_input_release_all(); acs_input_move(60, 1, 1); acs_input_end(62); neutral();
    assert(!acs_input_begin(70, static_cast<ACSInputControl>(-1), 0, 0));
    assert(!acs_input_begin(70, ACS_CONTROL_COUNT, 0, 0));
    for (uint64_t id = 0; id < 32; ++id) assert(acs_input_begin(id, ACS_A, 0, 0));
    assert(!acs_input_begin(32, ACS_B, 0, 0));
    assert(acs_input_poll().active_touches == 32 && acs_input_poll().buttons == ACS_BUTTON(ACS_A));
    for (uint64_t id = 0; id < 31; ++id) acs_input_end(id);
    assert(acs_input_poll().buttons == ACS_BUTTON(ACS_A));
    acs_input_end(31); neutral();
    assert(acs_input_begin(10, ACS_STICK_LEFT, 3, 4));
    assert(acs_input_begin(20, ACS_A, 0, 0));
    s = acs_input_poll();
    assert(s.active_touches == 2 && s.buttons == ACS_BUTTON(ACS_A));
    assert(std::abs(s.left_x - .6f) < .00001f && std::abs(s.left_y - .8f) < .00001f);
    assert(!acs_input_begin(10, ACS_B, 0, 0));
    assert(!acs_input_begin(30, ACS_STICK_LEFT, 0, 0));
    acs_input_end(20); s = acs_input_poll();
    assert(s.buttons == 0 && s.active_touches == 1 && s.left_x > .59f);
    acs_input_move(10, -2, 0); assert(acs_input_poll().left_x == -1);
    acs_input_move(10, std::numeric_limits<float>::infinity(), 0);
    assert(acs_input_poll().left_x == 0);
    acs_input_move(999, 1, 1); acs_input_end(999);
    acs_input_release_all(); neutral();
    assert(acs_input_begin(40, ACS_ZR, 0, 0));
    assert(acs_input_begin(41, ACS_ZR, 0, 0));
    acs_input_end(40); assert(acs_input_poll().right_trigger == 1);
    acs_input_release_all(); acs_input_move(41, 1, 1); neutral();
    assert(acs_input_begin(50, ACS_STICK_RIGHT, .25f, -.5f));
    assert(acs_input_begin(51, ACS_MINUS, 0, 0));
    acs_input_end(50); s = acs_input_poll();
    assert(s.right_x == 0 && s.buttons == ACS_BUTTON(ACS_MINUS));
    acs_input_release_all(); neutral();
    // Independent reader observes only coherent aggregate snapshots while UI
    // producer updates. Cancel must never leave trigger/button disagreement.
    std::atomic<bool> done{false};
    std::thread reader([&] {
        uint64_t previous = 0;
        while (!done.load()) {
            const auto q = acs_input_poll();
            assert(q.sequence >= previous); previous = q.sequence;
            assert(q.right_trigger == ((q.buttons & ACS_BUTTON(ACS_ZR)) ? 1.f : 0.f));
            assert(q.active_touches <= 1);
        }
    });
    for (unsigned i = 0; i < 10000; ++i) {
        assert(acs_input_begin(i, ACS_ZR, 0, 0));
        if (i % 2) acs_input_end(i); else acs_input_release_all();
    }
    done = true; reader.join(); neutral();
    puts("PASS: dual sticks/trigger, independent identity/release, shared-button ownership, 32-touch capacity, invalid controls, cancel/stale events, radial/nonfinite clamping, concurrent polling (10000 cycles)");
}
