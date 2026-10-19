#!/usr/bin/env python3
"""Run the Astral iOS-simulator app on one simulator device type for a bounded time and collect evidence.

Creates a fresh, owned simulator of the requested device type (or uses --udid, which must start Shutdown), boots it,
installs a staged, ad-hoc-signed copy of the app, launches it with NX_* environment (simctl SIMCTL_CHILD_*), takes
periodic screenshots, stops early on FATAL/CRASH or process exit, and collects the guest log, startup journal, input
journal, stdout/stderr and dumped frames into --out. The simulator is always shut down (and deleted when this tool
created it), including on errors and SIGINT/SIGTERM. Standard library only; every subprocess has a deadline.

Example:
  tools/ios_sim_run.py --app build/astral.app --device-type "iPhone 17 Pro" --seconds 240 \
      --data-root .local/ios-parity/data --env NX_PERF_HUD=1 --env NX_DUMP_FRAMES=300 --out .local/ios-parity/run-iphone
See docs/ASTRAL_IOS_SIM.md.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

DEFAULT_BUNDLE = "local.acs.astral-sim"
FATAL_RE = re.compile(r"^(FATAL|CRASH)\b.*$", re.M)


class RunError(Exception):
    pass


class Sim:
    """Thin, bounded wrapper over `xcrun simctl` (the xcrun path is injectable for tests)."""

    def __init__(self, xcrun: str, log: Path):
        self.xcrun = xcrun
        self.log = log

    def run(self, args: list[str], timeout: float, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
        cmd = [self.xcrun, "simctl", *args]
        started = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            self._record(cmd, None, started, "timeout")
            raise RunError(f"timed out after {timeout:.0f}s: simctl {' '.join(args[:2])}")
        self._record(cmd, proc.returncode, started, proc.stderr.strip()[-400:])
        if check and proc.returncode != 0:
            raise RunError(f"simctl {' '.join(args[:2])} failed ({proc.returncode}): {proc.stderr.strip()[-400:]}")
        return proc

    def _record(self, cmd, code, started, note):
        with self.log.open("a") as f:
            f.write(json.dumps({"cmd": cmd[1:], "code": code, "seconds": round(time.time() - started, 3),
                                "note": note}) + "\n")


def pick_runtime(listing: dict, wanted: str | None) -> dict:
    runtimes = [r for r in listing.get("runtimes", []) if r.get("isAvailable") and r.get("platform", "iOS") == "iOS"]
    if wanted:
        runtimes = [r for r in runtimes if wanted in (r.get("identifier"), r.get("version"), r.get("name"))]
    if not runtimes:
        raise RunError(f"no available iOS runtime matching {wanted!r}")
    return max(runtimes, key=lambda r: tuple(int(x) for x in re.findall(r"\d+", r.get("version", "0"))))


def pick_device_type(listing: dict, name: str) -> dict:
    for t in listing.get("devicetypes", []):
        if name in (t.get("name"), t.get("identifier")):
            return t
    raise RunError(f"unknown simulator device type {name!r}")


def stage_app(app: Path, staging: Path, bundle_id: str, codesign: str) -> Path:
    """Copies the app, names its real executable and bundle id in Info.plist, signs it ad hoc."""
    if not (app / "Info.plist").is_file():
        raise RunError(f"{app} is not an app bundle")
    dest = staging / app.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(app, dest, symlinks=True)
    info_path = dest / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    executable = info.get("CFBundleExecutable")
    if not executable or not (dest / executable).is_file():
        candidates = [p.name for p in dest.iterdir() if p.is_file() and os.access(p, os.X_OK)]
        if len(candidates) != 1:
            raise RunError(f"cannot identify the app executable among {candidates}")
        executable = candidates[0]
    info["CFBundleExecutable"] = executable
    info["CFBundleIdentifier"] = bundle_id
    info["CFBundleName"] = "Astral"
    info_path.write_bytes(plistlib.dumps(info))
    proc = subprocess.run([codesign, "--force", "--sign", "-", "--timestamp=none", str(dest)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RunError(f"codesign failed: {proc.stderr.strip()[-400:]}")
    return dest


def parse_env(pairs: list[str]) -> dict[str, str]:
    env = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise RunError(f"bad --env {pair!r}: expected KEY=VALUE")
        env[key] = value
    return env


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


GPU_TIMEOUT_MAX_S = 5.0  # the runtime clamps NX_GPU_TIMEOUT_S to this (nvn_vk.cpp, docs/ASTRAL_IOS_SIM.md)
GAME_PROCESS_RE = re.compile(r"/astral\.app/astral(\s|$)")


def check_gpu_timeout(env: dict[str, str]) -> None:
    value = env.get("NX_GPU_TIMEOUT_S")
    if value is None:
        return
    try:
        seconds = float(value)
    except ValueError:
        raise RunError(f"NX_GPU_TIMEOUT_S={value!r} is not a number")
    if not seconds > 0 or seconds > GPU_TIMEOUT_MAX_S:
        raise RunError(f"NX_GPU_TIMEOUT_S={value} refused: at most {GPU_TIMEOUT_MAX_S:g} s (longer waits on a stuck "
                       "GPU froze and restarted the host twice on 2026-10-19)")


# GPU-heavy settings refused for simulator runs (the simulator's GPU work runs on the host GPU).
MAX_IN_FLIGHT = {"NX_PIPELINED": 2, "NX_ASYNC_GPU": 2}
REFUSED_READBACKS = ("NX_DUMP_TEXTURES", "NX_DUMP_ON_TARGET", "NX_DUMP_ON_FS")


def check_gpu_load(env: dict[str, str]) -> None:
    for key, limit in MAX_IN_FLIGHT.items():
        if key in env:
            try:
                value = float(env[key])
            except ValueError:
                raise RunError(f"{key}={env[key]!r} is not a number")
            if value > limit:
                raise RunError(f"{key}={env[key]} refused: at most {limit} on the simulator")
    for key in REFUSED_READBACKS:
        if key in env:
            raise RunError(f"{key} refused on the simulator: debug readbacks of textures/targets stall the host GPU")


def check_exclusive(listing: dict, own_udid: str | None, ps: str) -> None:
    """One game simulator at a time: no other booted simulator and no running game instance."""
    booted = [f"{d.get('name')} ({d.get('udid')})" for devices in listing.get("devices", {}).values() for d in devices
              if d.get("state") not in ("Shutdown", None) and d.get("udid") != own_udid]
    if booted:
        raise RunError("refusing to start: other simulators are booted: " + ", ".join(booted))
    games = [line.strip() for line in ps.splitlines() if GAME_PROCESS_RE.search(line)]
    if games:
        raise RunError("refusing to start: a game instance is already running: " + "; ".join(games[:3]))


def process_list(ps_cmd: str) -> str:
    try:
        return subprocess.run([ps_cmd, "-axo", "pid=,command="], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RunError(f"cannot list processes: {e}")


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def collect(container: Path | None, out: Path, data_root: Path | None) -> dict:
    found = {}
    if container:
        docs = container / "Documents"
        for name in ("guest.log", "startup.jsonl", "input-state.json", "input-events.jsonl"):
            src = docs / name
            if src.is_file():
                shutil.copy2(src, out / name)
                found[name] = src.stat().st_size
    if data_root:
        frames = data_root / "frames"
        if frames.is_dir():
            dest = out / "frames"
            dest.mkdir(exist_ok=True)
            moved = 0
            for f in sorted(frames.iterdir()):
                if f.is_file():
                    shutil.move(str(f), dest / f.name)
                    moved += 1
            found["frames"] = moved
        if (data_root / "nx.log").is_file():
            shutil.copy2(data_root / "nx.log", out / "nx.log")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--app", required=True, type=Path, help="built .app bundle")
    ap.add_argument("--device-type", required=True, help='simulator device type name, e.g. "iPhone 17 Pro"')
    ap.add_argument("--runtime", help="iOS runtime identifier or version (default: newest available)")
    ap.add_argument("--udid", help="use this existing (Shutdown) simulator instead of creating one")
    ap.add_argument("--seconds", type=float, default=120, help="run time after launch (bounded to 3600)")
    ap.add_argument("--screenshot-every", type=float, default=15, help="seconds between screenshots (0: only the last)")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE for the app (repeatable)")
    ap.add_argument("--data-root", type=Path, help="host data root (NX_DATA_ROOT); frames are moved out of it")
    ap.add_argument("--bundle-id", default=DEFAULT_BUNDLE)
    ap.add_argument("--out", required=True, type=Path, help="evidence directory (created)")
    ap.add_argument("--keep-going-after-fatal", action="store_true", help="do not stop at the first FATAL/CRASH")
    ap.add_argument("--xcrun", default=os.environ.get("ACS_XCRUN", "xcrun"))
    ap.add_argument("--codesign", default=os.environ.get("ACS_CODESIGN", "codesign"))
    ap.add_argument("--ps", default=os.environ.get("ACS_PS", "ps"), help=argparse.SUPPRESS)
    ap.add_argument("--boot-timeout", type=float, default=240)
    args = ap.parse_args(argv)

    seconds = max(1.0, min(args.seconds, 3600.0))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "shots").mkdir(exist_ok=True)
    token = uuid.uuid4().hex[:12]
    sim = Sim(args.xcrun, out / "simctl.jsonl")
    summary: dict = {"token": token, "device_type": args.device_type, "seconds_requested": seconds,
                     "app": str(args.app), "env": {}, "status": "error", "screenshots": []}
    udid = None
    created = False
    booted = False
    boot_attempted = False
    container = None
    data_root = args.data_root.resolve() if args.data_root else None

    def on_signal(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    old_handlers = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        env = parse_env(args.env)
        check_gpu_timeout(env)
        check_gpu_load(env)
        if data_root:
            env.setdefault("NX_DATA_ROOT", str(data_root))
        summary["env"] = env
        listing = json.loads(sim.run(["list", "-j"], timeout=60).stdout)
        check_exclusive(listing, None, process_list(args.ps))
        runtime = pick_runtime(listing, args.runtime)
        dtype = pick_device_type(listing, args.device_type)
        summary["runtime"] = {"identifier": runtime["identifier"], "version": runtime.get("version"),
                              "build": runtime.get("buildversion")}
        summary["device_type_identifier"] = dtype["identifier"]
        if args.udid:
            udid = args.udid
            state = None
            for devices in listing.get("devices", {}).values():
                for d in devices:
                    if d.get("udid") == udid:
                        state = d.get("state")
            if state != "Shutdown":
                raise RunError(f"--udid {udid} must exist and be Shutdown (is {state})")
        else:
            name = f"ACS ios_sim_run {args.device_type} {token}"
            udid = sim.run(["create", name, dtype["identifier"], runtime["identifier"]], timeout=120).stdout.strip()
            created = True
        summary["udid"] = udid
        staged = stage_app(args.app.resolve(), out, args.bundle_id, args.codesign)
        boot_attempted = True  # a boot that failed or timed out may still have started the device
        sim.run(["boot", udid], timeout=args.boot_timeout)
        booted = True
        sim.run(["bootstatus", udid, "-b"], timeout=args.boot_timeout)
        sim.run(["install", udid, str(staged)], timeout=300)
        container = Path(sim.run(["get_app_container", udid, args.bundle_id, "data"], timeout=60).stdout.strip())
        summary["container"] = str(container)
        # Only this run's settings reach the app: inherited SIMCTL_CHILD_* variables are dropped.
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("SIMCTL_CHILD_")}
        for k, v in env.items():
            child_env[f"SIMCTL_CHILD_{k}"] = v
        launched = time.time()
        proc = sim.run(["launch", "--terminate-running-process", f"--stdout={out / 'stdout.log'}",
                        f"--stderr={out / 'stderr.log'}", udid, args.bundle_id, "--evidence-run", token],
                       timeout=120, env=child_env)
        m = re.search(r":\s*(\d+)\s*$", proc.stdout.strip())
        summary["pid"] = int(m.group(1)) if m else None
        summary["status"] = "running"
        next_shot = launched + (args.screenshot_every if args.screenshot_every > 0 else seconds)
        shot = 0
        while True:
            now = time.time()
            elapsed = now - launched
            log_text = read_text(container / "Documents" / "guest.log")
            fatal = FATAL_RE.search(log_text)
            if fatal and not args.keep_going_after_fatal:
                summary["status"] = "fatal"
                summary["fatal"] = fatal.group(0)[:400]
                break
            if summary.get("pid") and not pid_alive(summary["pid"]):
                summary["status"] = "exited"  # simulator apps are host processes
                break
            if now >= next_shot or elapsed >= seconds:
                path = out / "shots" / f"t{int(elapsed):04d}-{shot:03d}.png"
                if sim.run(["io", udid, "screenshot", str(path)], timeout=60, check=False).returncode == 0:
                    summary["screenshots"].append(str(path))
                shot += 1
                next_shot = now + (args.screenshot_every if args.screenshot_every > 0 else seconds)
            if elapsed >= seconds:
                summary["status"] = "completed"
                break
            time.sleep(min(2.0, max(0.1, seconds - elapsed)))
        summary["elapsed"] = round(time.time() - launched, 1)
        if summary["status"] in ("fatal", "exited") and not summary["screenshots"]:
            path = out / "shots" / "final.png"
            if sim.run(["io", udid, "screenshot", str(path)], timeout=60, check=False).returncode == 0:
                summary["screenshots"].append(str(path))
    except KeyboardInterrupt as e:
        summary["status"] = "interrupted"
        summary["error"] = str(e)
    except (RunError, OSError, ValueError, json.JSONDecodeError) as e:
        summary["status"] = "error"
        summary["error"] = str(e)
    finally:
        for s, h in old_handlers.items():
            signal.signal(s, h)
        cleanup = []

        def step(name, cmd):
            try:
                cleanup.append({name: sim.run(cmd, timeout=120, check=False).returncode})
            except RunError as e:
                cleanup.append({name: str(e)})

        if udid and booted:
            step("terminate", ["terminate", udid, args.bundle_id])
        # Collect before the device (and with it the app container) goes away.
        try:
            summary["collected"] = collect(container, out, data_root)
        except OSError as e:
            summary["collect_error"] = str(e)
        if udid and (booted or boot_attempted or created):
            step("shutdown", ["shutdown", udid])
        if udid and created:
            step("delete", ["delete", udid])
        summary["cleanup"] = cleanup
        log_text = read_text(out / "guest.log")
        summary["log_tail"] = log_text.splitlines()[-25:]
        fps = re.findall(r"(\d+(?:\.\d+)?) fps", log_text)
        if fps:
            summary["last_fps_in_log"] = fps[-1]
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary.get(k) for k in ("status", "device_type", "runtime", "udid", "elapsed", "fatal",
                                                  "error", "collected")}, indent=2))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
