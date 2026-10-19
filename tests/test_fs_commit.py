"""Compile the patched production FS TU; synthetic scratch files, no game inputs.

FS_COMMIT_REFERENCE can name a clean checkout at the pinned Wonder revision.
One compiler process; all fixture sources, binaries and receipts stay ignored.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime

HOST = r'''
#pragma once
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <unistd.h>
namespace nx {
struct CPU { uint64_t x[32] = {}; };
inline bool g_trace = false;
inline void log(const char*, ...) {}
template<class T> void st(uint64_t p, T v) { std::memcpy((void*)p, &v, sizeof v); }
template<class T> T ld(uint64_t p) { T v; std::memcpy(&v, (void*)p, sizeof v); return v; }
using Hle = void(*)(CPU&);
inline std::map<std::string, Hle>& registry() { static std::map<std::string, Hle> r; return r; }
struct Register { Register(const char* n, Hle f) { assert(registry().emplace(n,f).second); } };
}
#define JOIN1(a,b) a##b
#define JOIN(a,b) JOIN1(a,b)
#define NX_HLE(n,f) static nx::Register JOIN(reg_,__LINE__)(n,f)
namespace plat {
inline int64_t current_thread_id() { return 1; }
inline uint64_t monotonic_ns() { return std::chrono::steady_clock::now().time_since_epoch().count(); }
inline std::string data_root() { return std::getenv("FS_SCRATCH_ROOT"); }
inline FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(),m); }
inline int fseek64(FILE* f, int64_t o, int w) { return fseeko(f,o,w); }
inline int64_t ftell64(FILE* f) { return ftello(f); }
inline uint64_t read_at(FILE* f, int64_t o, void* p, uint64_t n) {
    auto r = pread(fileno(f),p,n,o); return r < 0 ? 0 : uint64_t(r);
}
}
'''

HARNESS = r'''
#include "host.h"
#include "hle_fs.cpp"
using namespace nx;
constexpr auto save = "_ZN2nn2fs14CommitSaveDataEPKc";
constexpr auto commit = "_ZN2nn2fs6CommitEPKc";
constexpr auto mount_save = "_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE";
constexpr auto mount_cache = "_ZN2nn2fs17MountCacheStorageEPKci";
constexpr auto unmount = "_ZN2nn2fs7UnmountEPKc";
constexpr auto create = "_ZN2nn2fs10CreateFileEPKcl";
constexpr auto open = "_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci";
constexpr auto close_file = "_ZN2nn2fs9CloseFileENS0_10FileHandleE";
constexpr auto write_file = "_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE";
constexpr auto read_file = "_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm";
constexpr auto flush_file = "_ZN2nn2fs9FlushFileENS0_10FileHandleE";
uint64_t ptr(const void* p) { return reinterpret_cast<uint64_t>(p); }
uint64_t call(const char* n, std::initializer_list<uint64_t> args) {
    CPU c; std::copy(args.begin(),args.end(),c.x); registry().at(n)(c); return c.x[0];
}
uint64_t opened(const char* path, int mode = 2) {
    uint64_t h = 0; assert(call(open,{ptr(&h),ptr(path),uint64_t(mode)}) == 0); assert(h); return h;
}
void make(const char* path) { assert(call(create,{ptr(path),0}) == 0); }
void write(uint64_t h) {
    const char text[] = "synthetic-persistent-save";
    assert(call(write_file,{h,0,ptr(text),sizeof text,0}) == 0);
}
void verify(uint64_t h) {
    char got[sizeof "synthetic-persistent-save"] = {}; uint64_t n = 0;
    assert(call(read_file,{ptr(&n),h,0,ptr(got),sizeof got}) == 0);
    assert(n == sizeof got); assert(std::memcmp(got, "synthetic-persistent-save", sizeof got) == 0);
}
// Test-only fault setup: retain the real production FILE ownership, buffer and
// host syscalls. No replacement commit/flush/write implementation or result stub.
struct BrokenFd {
    FILE* f; int fd, backup;
    BrokenFd(FILE* stream) : f(stream), fd(fileno(f)), backup(dup(fd)) {
        assert(backup >= 0); assert(::close(fd) == 0);
    }
    ~BrokenFd() { assert(dup2(backup,fd) == fd); ::close(backup); }
};
int main(int argc, char** argv) {
    assert(argc == 2); std::string test = argv[1];
    if (test == "unsafe-root") {
        assert(call(mount_save,{ptr("save"),0}) == kPathNotFound);
        assert(call(save,{ptr("save")}) == kTargetNotFound);
        return 0;
    }
    assert(call(mount_save,{ptr("save"),0}) == 0);
    if (test == "persist" || test == "legacy") {
        make("save:/persist.bin"); auto h = opened("save:/persist.bin"); write(h);
        assert(call(test == "legacy" ? commit : save,{ptr("save")}) == 0);
        // Abrupt process termination: no CloseFile, fclose or static destructors.
        std::_Exit(0);
    } else if (test == "reopen") {
        auto h = opened("save:/persist.bin",1); verify(h); call(close_file,{h});
        assert(call(save,{ptr("save")}) == 0);
    } else if (test == "buffered") {
        make("save:/buffer.bin"); auto h = opened("save:/buffer.bin");
        auto f = open_file(h); assert(std::fwrite("pending",1,7,f->f) == 7);
        assert(std::filesystem::file_size(std::filesystem::path(plat::data_root())/"user/save/buffer.bin") == 0);
        assert(call(save,{ptr("save")}) == 0);
        assert(std::filesystem::file_size(std::filesystem::path(plat::data_root())/"user/save/buffer.bin") == 7);
        call(close_file,{h}); assert(call(save,{ptr("save")}) == 0);
    } else if (test == "invalid") {
        for (const char* n : {"", "save:", "../save", "save/x", "save\\x", "unknown", "abcdefghijklmnop"})
            assert(call(save,{ptr(n)}) == kTargetNotFound);
        assert(call(save,{0}) == kTargetNotFound);
        assert(call(mount_save,{ptr("../escape"),0}) != 0);
        assert(call(mount_save,{ptr("save"),0}) != 0);
        assert(call(create,{ptr("save:/../escape"),0}) != 0);
        assert(call(create,{ptr("save:/a/../../escape"),0}) != 0);
        assert(call(create,{ptr("save:/C:/escape"),0}) != 0);
        auto outside = std::filesystem::path(plat::data_root()) / "outside";
        std::filesystem::create_directory(outside);
        std::filesystem::create_directory_symlink(outside,std::filesystem::path(plat::data_root())/"user/save/link");
        assert(call(create,{ptr("save:/link/escape"),0}) != 0);
        assert(!std::filesystem::exists(outside/"escape"));
        assert(call(flush_file,{9999}) == kTargetNotFound);
        call(unmount,{ptr("save")}); assert(call(save,{ptr("save")}) == kTargetNotFound);
    } else if (test == "isolation") {
        assert(call(mount_cache,{ptr("cache"),2}) == 0);
        make("cache:/other.bin"); auto h = opened("cache:/other.bin"); auto f = open_file(h);
        assert(std::fwrite("cache",1,5,f->f) == 5);
        assert(call(save,{ptr("save")}) == 0);
        assert(std::filesystem::file_size(std::filesystem::path(plat::data_root())/"user/cache2/other.bin") == 0);
        assert(call(commit,{ptr("cache")}) == 0);
        assert(std::filesystem::file_size(std::filesystem::path(plat::data_root())/"user/cache2/other.bin") == 5);
        call(close_file,{h});
        assert(call("_ZN2nn2fs8MountRomEPKc",{ptr("rom")}) == 0);
        assert(call(commit,{ptr("rom")}) == 0);
    } else if (test == "flush-failure" || test == "sync-failure" || test == "write-failure") {
        assert(call(mount_cache,{ptr("cache"),0}) == 0);
        make("save:/bad.bin"); auto h = opened("save:/bad.bin"); auto f = open_file(h);
        if (test == "flush-failure") assert(std::fwrite("pending",1,7,f->f) == 7);
        { BrokenFd broken(f->f);
          if (test == "write-failure") {
              const char data[] = "fail";
              assert(call(write_file,{h,0,ptr(data),sizeof data,0}) == kPathNotFound);
          }
          assert(call(save,{ptr("save")}) == kPathNotFound);
          if (test == "flush-failure") assert(call(flush_file,{h}) == kPathNotFound);
          assert(call(commit,{ptr("save")}) == kPathNotFound);
          assert(call(commit,{ptr("cache")}) == 0);
        }
        std::clearerr(f->f); call(close_file,{h}); f.reset();
        assert(call(save,{ptr("save")}) == kPathNotFound); // sticky past close
    } else if (test == "lifetime") {
        make("save:/old.bin"); auto h = opened("save:/old.bin"); auto old = open_file(h);
        call(close_file,{h}); // in-flight owner remains, weak registry must see it
        { BrokenFd broken(old->f); assert(call(save,{ptr("save")}) != 0); }
        call(unmount,{ptr("save")}); assert(call(mount_save,{ptr("save"),0}) == 0);
        assert(call(save,{ptr("save")}) == 0); // old generation cannot poison remount
        old.reset(); assert(call(write_file,{h,0,0,0,0}) == kTargetNotFound);
        auto reader = opened("save:/old.bin",1); auto r = open_file(reader);
        { BrokenFd broken(r->f); assert(call(save,{ptr("save")}) == 0); } // skip readers
        call(close_file,{reader});
    } else if (test == "concurrency") {
        make("save:/race.bin"); auto h = opened("save:/race.bin"); std::atomic<bool> begin{false};
        std::thread writer([&] { while (!begin.load()) std::this_thread::yield();
            for (int i=0;i<80;++i) { char b='x'; auto r=call(write_file,{h,0,ptr(&b),1,0}); assert(r==0 || r==kTargetNotFound); }
        });
        begin = true;
        for (int i=0;i<80;++i) assert(call(save,{ptr("save")}) == 0);
        call(close_file,{h}); writer.join(); assert(call(save,{ptr("save")}) == 0);
    } else { assert(false); }
    std::puts(("PASS " + test).c_str());
}
'''


class FsCommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        default = common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        reference = Path(os.environ.get('FS_COMMIT_REFERENCE', str(default)))
        if not reference.is_dir():
            raise AssertionError('clean pinned reference required via FS_COMMIT_REFERENCE')
        cls.out = ROOT / '.local/fs-commit-076' / ('verify-' + uuid.uuid4().hex)
        cls.out.mkdir(parents=True)
        # Existing overlays are applied first, never replaced by a naked FS source.
        patches = [ROOT / 'runtime/patches' / n for n in ('apple-memory.patch', 'astral-bootstrap.patch',
                   'astral-control-import.patch', 'astral-audio.patch', 'astral-notifications.patch',
                   'astral-apm.patch', 'astral-fs-commit.patch')]
        cls.source = cls.out / 'source'
        fingerprint = runtime.prepare_source(reference, cls.source, patches)
        fixture = cls.out / 'fixture'
        (fixture / 'nx').mkdir(parents=True)
        shutil.copyfile(cls.source / 'runtime/src/hle_fs.cpp', fixture / 'hle_fs.cpp')
        (fixture / 'nx/runtime.h').write_text('#include "host.h"\n')
        (fixture / 'platform.h').write_text('#include "host.h"\n')
        (fixture / 'host.h').write_text(HOST)
        (fixture / 'test.cpp').write_text(HARNESS)
        cls.binary = cls.out / 'fs-test'
        compiler = shutil.which('c++')
        if not compiler:
            raise AssertionError('C++20 compiler required')
        argv = [compiler, '-std=c++20', '-pthread', '-I', str(fixture), str(fixture / 'test.cpp'), '-o', str(cls.binary)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (cls.out / 'compile.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.receipt = {'pin': runtime.PIN, 'patches': {p.name: runtime.sha(p) for p in patches},
                       'source_fs_sha256': fingerprint['runtime/src/hle_fs.cpp'], 'compile': argv,
                       'binary_sha256': runtime.sha(cls.binary), 'cases': []}

    def run_case(self, name, root):
        env = dict(os.environ, FS_SCRATCH_ROOT=str(root))
        result = subprocess.run([str(self.binary), name], env=env, capture_output=True, text=True, timeout=10)
        self.receipt['cases'].append({'name': name, 'exit_code': result.returncode, 'output': result.stdout + result.stderr})
        (self.out / 'receipt.json').write_text(json.dumps(self.receipt, indent=2) + '\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_persistence_after_abrupt_exit_and_legacy_alias(self):
        for name in ('persist', 'legacy'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.out) as root:
                self.run_case(name, root)
                self.run_case('reopen', root)

    def test_buffered_data_is_really_flushed(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root:
            self.run_case('buffered', root)

    def test_invalid_mount_path_escape_and_handle(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root:
            self.run_case('invalid', root)

    def test_save_root_symlink_escape(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root, tempfile.TemporaryDirectory(dir=self.out) as outside:
            (Path(root) / 'user').symlink_to(outside, target_is_directory=True)
            self.run_case('unsafe-root', root)
            self.assertFalse((Path(outside) / 'save').exists())

    def test_other_mount_and_rom_behavior(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root:
            self.run_case('isolation', root)

    def test_host_failures_propagate_and_survive_close(self):
        for name in ('flush-failure', 'sync-failure', 'write-failure'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.out) as root:
                self.run_case(name, root)

    def test_handle_lifetime_and_mount_generations(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root:
            self.run_case('lifetime', root)

    def test_concurrent_commit_write_close(self):
        with tempfile.TemporaryDirectory(dir=self.out) as root:
            self.run_case('concurrency', root)

    @classmethod
    def tearDownClass(cls):
        print('private FS production receipt:', cls.out / 'receipt.json')


if __name__ == '__main__':
    unittest.main()
