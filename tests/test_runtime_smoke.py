"""Temporary Git/CMake integration fixtures; no cloud, keys, game code or network."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("runtime_smoke", Path(__file__).resolve().parents[1] / "tools/runtime_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        self.git(self.repo, "init", "-q")
        (self.repo / ".gitignore").write_text(".local/\n")
        self.source = self.repo / ".local/reference"
        self.source.mkdir(parents=True)
        self.git(self.source, "init", "-q")
        (self.source / "main.cpp").write_text("int main() { return 0; }\n")
        lines = ["cmake_minimum_required(VERSION 3.16)", "project(Fixture CXX)", "enable_testing()"]
        for target in smoke.TARGETS:
            lines.append(f"add_executable({target} main.cpp)")
        for name, target in zip(["gpu_pick", "tiling", "astc"], smoke.TARGETS):
            lines.append(f"add_test(NAME {name} COMMAND {target})")
        (self.source / "CMakeLists.txt").write_text("\n".join(lines))
        self.git(self.source, "add", ".")
        self.git(self.source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.pin = self.git(self.source, "rev-parse", "HEAD")
        (self.repo / "dependencies.lock").write_text(json.dumps({"references": [{"name": "SuperMarioWonderRecomp", "revision": self.pin}]}))
        self.patcher = patch.object(smoke, "PIN", self.pin)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.out = self.repo / ".local/output"

    @staticmethod
    def git(repo, *args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE).strip()

    def test_pin_and_clean_checkout(self):
        smoke.validate(self.repo, self.source, self.out)
        (self.source / "main.cpp").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "dirty"):
            smoke.validate(self.repo, self.source, self.out)

    def test_wrong_head_and_lock(self):
        with patch.object(smoke, "PIN", "0" * 40):
            with self.assertRaisesRegex(ValueError, "lock"):
                smoke.validate(self.repo, self.source, self.out)
        data = {"references": [{"name": "SuperMarioWonderRecomp", "revision": "0" * 40}]}
        (self.repo / "dependencies.lock").write_text(json.dumps(data))
        with patch.object(smoke, "PIN", "0" * 40):
            with self.assertRaisesRegex(ValueError, "revision"):
                smoke.validate(self.repo, self.source, self.out)

    def test_private_paths(self):
        for out in (self.repo / "public", self.source / "build"):
            with self.assertRaises(ValueError):
                smoke.validate(self.repo, self.source, out)
        link = self.repo / ".local/link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            smoke.validate(self.repo, link, self.out)
        self.out.mkdir()
        (self.out / "old").write_text("old")
        with self.assertRaisesRegex(ValueError, "fresh"):
            smoke.validate(self.repo, self.source, self.out)

    def test_tracked_and_unignored_paths(self):
        tracked = self.repo / ".local/tracked"
        tracked.write_text("fixture")
        self.git(self.repo, "add", "-f", str(tracked))
        with self.assertRaisesRegex(ValueError, "tracked"):
            smoke.private_path(self.repo, tracked)
        (self.repo / ".gitignore").write_text("")
        with self.assertRaisesRegex(ValueError, "gitignored"):
            smoke.private_path(self.repo, self.out)

    def test_failed_command_writes_failure_receipt(self):
        with self.assertRaises(RuntimeError):
            smoke.run_smoke(self.repo, self.source, self.out, cmake="false")
        rec = json.loads((self.out / "receipt.json").read_text())
        self.assertFalse(rec["success"])
        self.assertEqual(rec["commands"][0]["exit_code"], 1)

    @unittest.skipUnless(all(shutil.which(x) for x in ("cmake", "ctest", "ninja", "clang++")), "native fixture tools absent")
    def test_real_native_build_and_tests(self):
        rec = smoke.run_smoke(self.repo, self.source, self.out)
        self.assertTrue(rec["success"])
        self.assertEqual(rec["tests_passed"], smoke.TESTS)
        self.assertFalse(rec["game_built"])
        self.assertTrue((self.out / "receipt.json").is_file())

    def test_missing_tests_cannot_pass(self):
        if not all(shutil.which(x) for x in ("cmake", "ctest", "ninja", "clang++")):
            self.skipTest("native fixture tools absent")
        cmake = self.source / "CMakeLists.txt"
        cmake.write_text(cmake.read_text().replace("add_test(NAME astc COMMAND astc_test)", ""))
        self.git(self.source, "add", ".")
        self.git(self.source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "missing test")
        pin = self.git(self.source, "rev-parse", "HEAD")
        (self.repo / "dependencies.lock").write_text(json.dumps({"references": [{"name": "SuperMarioWonderRecomp", "revision": pin}]}))
        with patch.object(smoke, "PIN", pin), self.assertRaisesRegex(RuntimeError, "exactly three"):
            smoke.run_smoke(self.repo, self.source, self.out)


if __name__ == "__main__":
    unittest.main()
