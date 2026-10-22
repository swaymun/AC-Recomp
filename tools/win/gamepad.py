"""Controllable ViGEm Xbox 360 pad; JSON lines from a file or stdin.
Each line: {"buttons":["A","LEFT_SHOULDER"],"left_trigger":255,"ms":500}.
State is reset before each line; EOF disconnects. --self-test asserts XInput A on/off.
"""
import argparse
import ctypes
import json
import sys
import time

import vgamepad as vg


class Gamepad(ctypes.Structure):
    _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte),
                ("rt", ctypes.c_ubyte), ("lx", ctypes.c_short),
                ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class State(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_ulong), ("pad", Gamepad)]


def slots():
    dll = ctypes.WinDLL("xinput1_4.dll")
    result = {}
    for slot in range(4):
        state = State()
        if dll.XInputGetState(slot, ctypes.byref(state)) == 0:
            result[slot] = {"buttons": state.pad.buttons, "packet": state.packet}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", nargs="?", help="JSON-lines file; default stdin")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    before = slots()
    pad = vg.VX360Gamepad()
    time.sleep(1)
    if args.self_test:
        new = set(slots()) - set(before)
        if len(new) != 1:
            raise RuntimeError(f"Expected one new XInput slot, before={before}, after={slots()}")
        slot = new.pop()
        pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        pad.update()
        time.sleep(0.1)
        pressed = slots()[slot]
        assert pressed["buttons"] & 0x1000, pressed
        pad.reset()
        pad.update()
        time.sleep(0.1)
        released = slots()[slot]
        assert released["buttons"] == 0, released
        print(json.dumps({"slot": slot, "pressed": pressed, "released": released, "result": "OK"}))
        return
    source = open(args.script, encoding="utf-8") if args.script else sys.stdin
    try:
        for line in source:
            if not line.strip():
                continue
            command = json.loads(line)
            pad.reset()
            for name in command.get("buttons", []):
                pad.press_button(getattr(vg.XUSB_BUTTON, "XUSB_GAMEPAD_" + name.upper()))
            pad.left_trigger(int(command.get("left_trigger", 0)))
            pad.right_trigger(int(command.get("right_trigger", 0)))
            pad.left_joystick(x_value=int(command.get("lx", 0)), y_value=int(command.get("ly", 0)))
            pad.right_joystick(x_value=int(command.get("rx", 0)), y_value=int(command.get("ry", 0)))
            pad.update()
            print(json.dumps({"command": command, "xinput": slots()}), flush=True)
            time.sleep(max(0, min(60000, int(command.get("ms", 0)))) / 1000)
    finally:
        pad.reset()
        pad.update()
        if source is not sys.stdin:
            source.close()


if __name__ == "__main__":
    main()
