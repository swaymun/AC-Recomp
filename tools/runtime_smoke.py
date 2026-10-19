#!/usr/bin/env python3
"""Build pinned Wonder's original no-data native tests; never launch game code."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

PIN = "010ed7a596a621c15d3a8dfa5795ca8c3668b066"
ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["gpu_pick_test", "tiling_test", "astc_test", "shader_cache_test"]
TESTS = ["astc", "gpu_pick", "tiling"]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE, text=True).strip()


def private_path(repo, path):
    repo = Path(repo).resolve()
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(repo / ".local"):
        raise ValueError("source/output must be inside repository .local")
    for p in (path, *path.parents):
        if p == repo:
            break
        if p.is_symlink():
            raise ValueError("symlink private path refused")
    if git(repo, "ls-files", "--", str(path)):
        raise ValueError("tracked private path refused")
    if subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--", str(path)]).returncode:
        raise ValueError("private path must be gitignored")
    return path


def validate(repo, source, output):
    repo = Path(repo).resolve()
    source, output = private_path(repo, source), private_path(repo, output)
    lock = json.loads((repo / "dependencies.lock").read_text())
    refs = [x for x in lock["references"] if x["name"] == "SuperMarioWonderRecomp"]
    if len(refs) != 1 or refs[0]["revision"] != PIN:
        raise ValueError("lock does not contain exact supported Wonder pin")
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("source and output must be separate")
    if git(source, "rev-parse", "--show-toplevel") != str(source):
        raise ValueError("source must be its own checkout")
    if git(source, "rev-parse", "HEAD") != PIN:
        raise ValueError("wrong Wonder checkout revision")
    if git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("dirty Wonder checkout refused")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be fresh and empty")
    return source, output


def run_smoke(repo, source, output, jobs=3, cmake="cmake", ctest="ctest", compiler="clang++"):
    if not 1 <= jobs <= 3:
        raise ValueError("jobs must be between 1 and 3 on shared host")
    source, output = validate(repo, source, output)
    output.mkdir(parents=True, exist_ok=True)
    record = {"schema": 1, "revision": PIN, "source": str(source), "output": str(output),
              "platform": platform.platform(), "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "mode": "original_synthetic_native_tests", "game_built": False, "success": False,
              "lock_sha256": hashlib.sha256((Path(repo) / "dependencies.lock").read_bytes()).hexdigest(),
              "source_cmake_sha256": hashlib.sha256((source / "CMakeLists.txt").read_bytes()).hexdigest(),
              "commands": [], "shader_cache": "compiled only; private shader-dependent test not run"}
    def run(args):
        index = len(record["commands"])
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log = output / (str(index) + ".log")
        log.write_text(proc.stdout)
        record["commands"].append({"argv": args, "exit_code": proc.returncode, "log": log.name})
        if proc.returncode:
            raise RuntimeError("command failed: " + " ".join(args) + "; see " + str(log))
        return proc.stdout
    try:
        for tool in (cmake, ctest, compiler, "ninja"):
            run([tool, "--version"])
        build = output / "build"
        # This must stay empty: avoids upstream's generated-game branch and SDL/game data.
        no_gen = output / "no-generated-code"
        no_gen.mkdir()
        run([cmake, "-S", str(source), "-B", str(build), "-G", "Ninja", "-DNX_TESTS=ON",
             "-DNX_GAME=wonder", "-DNX_GEN_DIR=" + str(no_gen), "-DCMAKE_BUILD_TYPE=Release",
             "-DCMAKE_CXX_COMPILER=" + compiler])
        run([cmake, "--build", str(build), "--parallel", str(jobs), "--target", *TARGETS])
        expression = "^(gpu_pick|tiling|astc)$"
        listing = json.loads(run([ctest, "--test-dir", str(build), "--show-only=json-v1", "-R", expression]))
        names = sorted(x["name"] for x in listing["tests"])
        if names != TESTS:
            raise RuntimeError("expected exactly three synthetic tests; got " + repr(names))
        run([ctest, "--test-dir", str(build), "--output-on-failure", "--no-tests=error", "-R", expression])
        record["tests_passed"] = names
        record["success"] = True
    except Exception as exc:
        record["failure"] = str(exc)
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--ctest", default="ctest")
    parser.add_argument("--compiler", default="clang++")
    args = parser.parse_args()
    try:
        result = run_smoke(ROOT, args.source, args.output, args.jobs, args.cmake, args.ctest, args.compiler)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("runtime smoke failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
