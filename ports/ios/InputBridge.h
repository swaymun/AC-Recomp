#ifndef ACS_IOS_INPUT_BRIDGE_H
#define ACS_IOS_INPUT_BRIDGE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Stable host ABI v1, extended additively (D-pad, stick clicks, touch-screen points):
 * new controls only add button bits and functions, so v1 consumers keep working.
 * Axes: right/up positive, radial magnitude <= 1.
 * Triggers: 0..1 (digital overlay); buttons use the masks below.
 * Poll copies a coherent snapshot; no pointers escape. All calls thread-safe.
 * Touch IDs must be unique while held. Unknown move/end are harmless.
 * Runtime HID mapping and worker lifetime are intentionally caller-owned. */
#define ACS_INPUT_ABI_VERSION 1u
enum ACSInputControl {
    ACS_STICK_LEFT = 0, ACS_STICK_RIGHT,
    ACS_A, ACS_B, ACS_X, ACS_Y, ACS_L, ACS_R, ACS_ZL, ACS_ZR,
    ACS_PLUS, ACS_MINUS,
    ACS_DPAD_UP, ACS_DPAD_DOWN, ACS_DPAD_LEFT, ACS_DPAD_RIGHT,
    ACS_STICK_L_CLICK, ACS_STICK_R_CLICK,
    ACS_CONTROL_COUNT
};
#define ACS_BUTTON(control) (UINT32_C(1) << ((control) - ACS_A))
typedef struct ACSInputState {
    uint32_t abi_version;
    uint32_t buttons;
    float left_x, left_y, right_x, right_y;
    float left_trigger, right_trigger;
    uint32_t active_touches;
    uint64_t sequence;
} ACSInputState;
/* Returns 0 for duplicate IDs, invalid controls, full capacity (32), or an
 * already owned stick. Multiple touch owners of a button are supported. */
int acs_input_begin(uint64_t touch, enum ACSInputControl control, float x, float y);
void acs_input_move(uint64_t touch, float x, float y);
void acs_input_end(uint64_t touch);
/* Releases every control and every touch-screen point. */
void acs_input_release_all(void);
ACSInputState acs_input_poll(void);

/* Touch-screen points (touches that are not on a control): x, y are fractions
 * (0..1, top-left origin) of the game view, clamped. At most ACS_TOUCH_MAX
 * held at once; begin returns 0 when full, for a duplicate ID or non-finite x/y. */
#define ACS_TOUCH_MAX 16
typedef struct ACSTouchPoint {
    uint64_t id;
    float x, y;
} ACSTouchPoint;
int acs_touch_begin(uint64_t touch, float x, float y);
void acs_touch_move(uint64_t touch, float x, float y);
void acs_touch_end(uint64_t touch);
/* Copies up to `max` held points in the order they began; returns the count. */
size_t acs_touch_poll(ACSTouchPoint* out, size_t max);
#ifdef __cplusplus
}
#endif
#endif
