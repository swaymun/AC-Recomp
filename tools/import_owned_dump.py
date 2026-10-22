#!/usr/bin/env python3
"""Local-only, standard-library boundary around the pinned Wonder importer.

Never opens key files in Python. Child diagnostics are deliberately discarded.
Game-derived inventories and receipts are confined to ignored .local/game-private.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zlib

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
SOURCE = 'android/wonder/importer'
SOURCES = ('nximport.cpp', 'nxcrypto.cpp', 'nximport_cli.cpp', 'nximport.h', 'nxcrypto.h')


class ImportFailure(Exception):
    """Only fixed, nonsecret error codes may cross the CLI boundary."""


def require(condition, code):
    if not condition:
        raise ImportFailure(code)


WINDOWS = sys.platform == 'win32'
# The source-only release includes this tool through its fixed allowlist. Keep
# original host adapters here so checkout and zip builds use identical bytes;
# generated C++/headers are written only to the private importer source tree.
WINDOWS_IMPORT_COMPAT = r'''// Original Windows host adapter for the pinned MIT-licensed Wonder importer.
// Only host I/O changes: encrypted formats and verification stay upstream.
#pragma once
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <direct.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <algorithm>
#include <cerrno>
#include <climits>
#include <cstring>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

using ssize_t = intptr_t;
constexpr int O_CLOEXEC = _O_NOINHERIT;
#ifndef S_ISREG
#define S_ISREG(mode) (((mode) & _S_IFMT) == _S_IFREG)
#endif

// All native paths arrive as UTF-8. Wide extended paths preserve Unicode and
// paths beyond MAX_PATH without requiring a machine-wide registry change.
inline std::wstring acr_path(const std::string& text) {
    auto p = std::filesystem::absolute(std::filesystem::u8path(text)).lexically_normal().wstring();
    std::replace(p.begin(), p.end(), L'/', L'\\');
    if (p.rfind(L"\\\\?\\", 0) == 0) return p;
    return p.rfind(L"\\\\", 0) == 0 ? L"\\\\?\\UNC\\" + p.substr(2) : L"\\\\?\\" + p;
}
inline int acr_open(const char* p, int flags, int mode = 0) {
    return _wopen(acr_path(p).c_str(), flags | _O_BINARY, mode);
}
inline int acr_stat(const char* p, struct _stat64* st) { return _wstat64(acr_path(p).c_str(), st); }
inline int acr_mkdir(const char* p, int) { return _wmkdir(acr_path(p).c_str()); }
inline int acr_unlink(const char* p) { return _wunlink(acr_path(p).c_str()); }
inline int acr_rename(const char* from, const char* to) {
    // POSIX rename replaces a finished file atomically; CRT rename does not.
    if (MoveFileExW(acr_path(from).c_str(), acr_path(to).c_str(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return 0;
    errno = EIO;
    return -1;
}
inline FILE* acr_fopen(const char* p, const char* mode) {
    std::wstring wide_mode(mode, mode + strlen(mode));
    // Receipts/journals use LF on every host; binary game I/O is always binary.
    wide_mode += L"b";
    return _wfopen(acr_path(p).c_str(), wide_mode.c_str());
}
inline ssize_t acr_pread(int fd, void* data, size_t count, int64_t offset) {
    // The importer reads on a single thread. Always seek explicitly, including
    // >4 GiB offsets; Windows long/off_t and plain fstat truncate large NSPs.
    if (_lseeki64(fd, offset, SEEK_SET) < 0) return -1;
    return _read(fd, data, unsigned(std::min<size_t>(count, INT_MAX)));
}
struct acr_statvfs { uint64_t f_bavail = 0, f_frsize = 1; };
inline int acr_space(const char* p, acr_statvfs* st) {
    ULARGE_INTEGER available;
    if (!GetDiskFreeSpaceExW(acr_path(p).c_str(), &available, nullptr, nullptr)) return -1;
    st->f_bavail = available.QuadPart;
    return 0;
}

inline bool acr_safe_name(const std::string& name) {
    if (name.empty() || name == "." || name == ".." || name.back() == '.' || name.back() == ' ') return false;
    for (unsigned char c : name) if (c < 32 || strchr("\\/:<>\"|?*", c)) return false;
    auto base = name.substr(0, name.find('.'));
    for (auto& c : base) if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    if (base == "CON" || base == "PRN" || base == "AUX" || base == "NUL") return false;
    return !(base.size() == 4 && (base.substr(0,3) == "COM" || base.substr(0,3) == "LPT") &&
             base[3] >= '1' && base[3] <= '9');
}
'''

WINDOWS_IMPORT_PATCH = r'''--- a/android/wonder/importer/nximport.cpp
+++ b/android/wonder/importer/nximport.cpp
@@ -21,10 +21,7 @@
 //   NSO     "NSO0", three LZ4 segments (text, ro, data) with SHA-256 of each decompressed segment.
 #include "nximport.h"

-#include <fcntl.h>
-#include <sys/stat.h>
-#include <sys/statvfs.h>
-#include <unistd.h>
+#include "import_compat.h"

 #include <algorithm>
 #include <array>
@@ -106,15 +103,15 @@
     int fd;
     std::string name;
     FdStorage(int f, std::string n) : fd(f), name(std::move(n)) {
-        struct stat st{};
-        if (fstat(fd, &st) != 0) fail("%s: cannot stat (%s)", name.c_str(), strerror(errno));
+        struct _stat64 st{};
+        if (_fstat64(fd, &st) != 0) fail("%s: cannot stat (%s)", name.c_str(), strerror(errno));
         size = uint64_t(st.st_size);
     }
     void read(uint64_t off, void* dst, size_t n) override {
         if (off + n > size) fail("%s: read past the end (offset %llu)", name.c_str(), (unsigned long long)off);
         uint8_t* p = static_cast<uint8_t*>(dst);
         while (n) {
-            ssize_t r = pread(fd, p, n, off_t(off));
+            ssize_t r = acr_pread(fd, p, n, int64_t(off));
             if (r < 0 && errno == EINTR) continue;
             if (r <= 0) fail("%s: read error at %llu (%s)", name.c_str(), (unsigned long long)off, r < 0 ? strerror(errno) : "end of file");
             p += r, off += uint64_t(r), n -= size_t(r);
@@ -871,15 +868,11 @@
 // ---- output ----

 void mkdirs(const std::string& path) {
-    std::string cur;
-    size_t pos = 0;
-    while (pos != std::string::npos) {
-        pos = path.find('/', pos + 1);
-        cur = path.substr(0, pos);
-        if (cur.empty()) continue;
-        if (mkdir(cur.c_str(), 0775) != 0 && errno != EEXIST) fail("cannot create folder %s (%s)", cur.c_str(), strerror(errno));
-    }
-}
+    std::error_code error;
+    std::filesystem::create_directories(std::filesystem::path(acr_path(path)), error);
+    if (error) fail("cannot create output folder");
+}
+

 struct Writer {
     std::string final_path, part;
@@ -887,36 +880,36 @@
     uint32_t crc = 0;
     uint64_t written = 0;
     explicit Writer(const std::string& path) : final_path(path), part(path + ".part") {
-        fd = ::open(part.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0664);
+        fd = ::acr_open(part.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0664);
         if (fd < 0) fail("cannot write %s (%s)", part.c_str(), strerror(errno));
     }
     void write(const void* data, size_t n) {
         crc = crc32_update(crc, data, n);
         const uint8_t* p = static_cast<const uint8_t*>(data);
         while (n) {
-            ssize_t w = ::write(fd, p, n);
+            ssize_t w = ::_write(fd, p, unsigned(std::min<size_t>(n, INT_MAX)));
             if (w < 0 && errno == EINTR) continue;
             if (w <= 0) fail("write error on %s (%s)", final_path.c_str(), w < 0 ? strerror(errno) : "disk full?");
             p += w, n -= size_t(w), written += uint64_t(w);
         }
     }
     void commit() {
-        if (fdatasync(fd) != 0 && errno != EINVAL && errno != EROFS) fail("sync of %s failed (%s)", final_path.c_str(), strerror(errno));
-        ::close(fd);
+        if (_commit(fd) != 0 && errno != EINVAL && errno != EROFS) fail("sync of %s failed (%s)", final_path.c_str(), strerror(errno));
+        ::_close(fd);
         fd = -1;
-        if (rename(part.c_str(), final_path.c_str()) != 0) fail("cannot rename %s (%s)", part.c_str(), strerror(errno));
+        if (acr_rename(part.c_str(), final_path.c_str()) != 0) fail("cannot rename %s (%s)", part.c_str(), strerror(errno));
     }
     ~Writer() {
         if (fd >= 0) {
-            ::close(fd);
-            unlink(part.c_str());
+            ::_close(fd);
+            acr_unlink(part.c_str());
         }
     }
 };

 uint64_t file_size(const std::string& p) {
-    struct stat st{};
-    return stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode) ? uint64_t(st.st_size) : ~0ull;
+    struct _stat64 st{};
+    return acr_stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode) ? uint64_t(st.st_size) : ~0ull;
 }

 std::string read_small(Storage& s, uint64_t max) {
@@ -933,7 +926,7 @@
     void open(const std::string& p, bool reset) {
         path = p;
         if (!reset) {
-            std::ifstream in(p);
+            std::ifstream in(std::filesystem::path(acr_path(p)), std::ios::binary);
             std::string line;
             while (std::getline(in, line)) {
                 std::istringstream ls(line);
@@ -942,7 +935,7 @@
                     done[rel] = {strtoull(size.c_str(), nullptr, 10), uint32_t(strtoul(crc.c_str(), nullptr, 16))};
             }
         }
-        f = fopen(p.c_str(), reset ? "w" : "a");
+        f = acr_fopen(p.c_str(), reset ? "w" : "a");
         if (!f) fail("cannot write %s (%s)", p.c_str(), strerror(errno));
     }
     void add(const char* kind, const std::string& rel, uint64_t size, uint32_t crc) {
@@ -972,7 +965,7 @@
         uint32_t nlen = rd32(f + 0x1C);
         if (size_t(file) + 0x20 + nlen > files.size()) fail("RomFS: bad file name");
         std::string name(reinterpret_cast<const char*>(f + 0x20), nlen);
-        if (name.empty() || name == "." || name == ".." || name.find('/') != std::string::npos) fail("RomFS: unsafe file name");
+        if (name.empty() || name == "." || name == ".." || name.find('/') != std::string::npos || !acr_safe_name(name)) fail("RomFS: unsafe file name");
         out.push_back({prefix + name, rd64(f + 8), rd64(f + 16)});
         file = rd32(f + 4);
     }
@@ -982,7 +975,7 @@
         uint32_t nlen = rd32(c + 0x14);
         if (size_t(child) + 0x18 + nlen > dirs.size()) fail("RomFS: bad directory name");
         std::string name(reinterpret_cast<const char*>(c + 0x18), nlen);
-        if (name.empty() || name == "." || name == ".." || name.find('/') != std::string::npos) fail("RomFS: unsafe folder name");
+        if (name.empty() || name == "." || name == ".." || name.find('/') != std::string::npos || !acr_safe_name(name)) fail("RomFS: unsafe folder name");
         out_dirs.push_back(prefix + name);
         walk_romfs(dirs, files, child, prefix + name + "/", out, out_dirs, depth + 1);
         child = rd32(c + 4);
@@ -1017,8 +1010,8 @@
 };

 void check_space(const std::string& dir, uint64_t need) {
-    struct statvfs vs{};
-    if (statvfs(dir.c_str(), &vs) != 0) return;
+    struct acr_statvfs vs{};
+    if (acr_space(dir.c_str(), &vs) != 0) return;
     uint64_t free_b = uint64_t(vs.f_bavail) * vs.f_frsize;
     uint64_t margin = 64ull << 20;
     if (free_b < need + margin)
@@ -1027,7 +1020,7 @@
 }

 int verify_outputs(Run& run, const std::string& out, std::string& error) {
-    std::ifstream in(out + "/.import/index.tsv");
+    std::ifstream in(std::filesystem::path(acr_path(out + "/.import/index.tsv")), std::ios::binary);
     if (!in) {
         error = "nothing to verify: no finished import in " + out;
         return 2;
@@ -1056,18 +1049,18 @@
         run.pr.item = e.rel;
         run.report();
         std::string p = out + "/" + e.rel;
-        int fd = ::open(p.c_str(), O_RDONLY | O_CLOEXEC);
+        int fd = ::acr_open(p.c_str(), O_RDONLY | O_CLOEXEC);
         uint32_t crc = 0;
         uint64_t got = 0;
         if (fd >= 0) {
             ssize_t r;
-            while ((r = ::read(fd, buf.data(), buf.size())) > 0) {
+            while ((r = ::_read(fd, buf.data(), unsigned(buf.size()))) > 0) {
                 crc = crc32_update(crc, buf.data(), size_t(r));
                 got += uint64_t(r);
                 run.pr.done += uint64_t(r);
                 run.report();
             }
-            ::close(fd);
+            ::_close(fd);
         }
         if (fd < 0 || got != e.size || crc != e.crc) {
             if (!bad++) first_bad = e.rel;
@@ -1252,14 +1245,14 @@
     std::string root = opt.out_dir;
     std::string old_ident;
     {
-        std::ifstream f(root + "/.import/source.txt");
+        std::ifstream f(std::filesystem::path(acr_path(root + "/.import/source.txt")), std::ios::binary);
         std::getline(f, old_ident);
     }
     bool reset = old_ident != ident;
     if (reset) {
-        unlink((root + "/.import/index.tsv").c_str());
-        unlink((root + "/.import/complete").c_str());
-        std::ofstream f(root + "/.import/source.txt", std::ios::trunc);
+        acr_unlink((root + "/.import/index.tsv").c_str());
+        acr_unlink((root + "/.import/complete").c_str());
+        std::ofstream f(std::filesystem::path(acr_path(root + "/.import/source.txt")), std::ios::binary | std::ios::trunc);
         f << ident << "\n";
     }
     Journal journal;
@@ -1316,7 +1309,7 @@
             if (off + size > pfs.size() || so >= strsz) fail("ExeFS entry %u out of range", i);
             const char* nm = reinterpret_cast<const char*>(pfs.data() + 16 + count * 0x18 + so);
             std::string name(nm, strnlen(nm, strsz - so));
-            if (name.empty() || name.find('/') != std::string::npos || name[0] == '.') fail("ExeFS: unsafe file name");
+            if (name.empty() || name.find('/') != std::string::npos || !acr_safe_name(name) || name[0] == '.') fail("ExeFS: unsafe file name");
             run.pr.item = name;
             run.report(true);
             std::vector<uint8_t> blob(pfs.begin() + long(off), pfs.begin() + long(off + size));
@@ -1421,7 +1414,7 @@

     // ---- index + completion marker ----
     {
-        std::ofstream idx(root + "/.import/index.tsv.part", std::ios::trunc);
+        std::ofstream idx(std::filesystem::path(acr_path(root + "/.import/index.tsv.part")), std::ios::binary | std::ios::trunc);
         for (auto& [rel, sc] : journal.done) {
             bool keep = rel.rfind("analysis/", 0) == 0;
             idx << (keep ? "exefs" : "romfs") << "\t" << sc.first << "\t" << std::hex;
@@ -1430,9 +1423,9 @@
             idx << c << std::dec << "\t" << rel << "\n";
         }
         idx.close();
-        if (!idx || rename((root + "/.import/index.tsv.part").c_str(), (root + "/.import/index.tsv").c_str()) != 0)
+        if (!idx || acr_rename((root + "/.import/index.tsv.part").c_str(), (root + "/.import/index.tsv").c_str()) != 0)
             fail("cannot write the import index");
-        std::ofstream mark(root + "/.import/complete", std::ios::trunc);
+        std::ofstream mark(std::filesystem::path(acr_path(root + "/.import/complete")), std::ios::binary | std::ios::trunc);
         mark << ident << "\n" << list.size() << " romfs files, " << total << " bytes\n";
     }
     run.pr.phase = "done";
--- a/android/wonder/importer/nximport_cli.cpp
+++ b/android/wonder/importer/nximport_cli.cpp
@@ -1,8 +1,7 @@
 // PC test harness of the on-device importer: the same code the APK runs, fed with files from the command line.
 //   nximport --out <data folder> [--title 010015100B514000] [--verify] [--exefs] <prod.keys> [title.keys] <x.nsp|x.xci> ...
 // Prints progress and log lines (never key values).
-#include <fcntl.h>
-#include <unistd.h>
+#include "import_compat.h"

 #include <atomic>
 #include <chrono>
@@ -14,7 +13,20 @@

 #include "nximport.h"

-int main(int argc, char** argv) {
+int wmain(int argc, wchar_t** wide_argv) {
+    std::vector<std::string> utf8;
+    for (int i = 0; i < argc; ++i) {
+        int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, nullptr, 0, nullptr, nullptr);
+        if (!n) return 2;
+        std::string s(n, '\0');
+        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, s.data(), n, nullptr, nullptr);
+        s.pop_back();
+        std::replace(s.begin(), s.end(), '\\', '/');
+        utf8.push_back(std::move(s));
+    }
+    std::vector<char*> args;
+    for (auto& s : utf8) args.push_back(s.data());
+    char** argv = args.data();
     nxi::Options opt;
     std::vector<nxi::InputFile> inputs;
     for (int i = 1; i < argc; i++) {
@@ -28,7 +40,7 @@
         } else if (a == "--verify") {
             opt.verify_only = true;
         } else {
-            int fd = open(argv[i], O_RDONLY | O_CLOEXEC);
+            int fd = acr_open(argv[i], O_RDONLY | O_CLOEXEC);
             if (fd < 0) {
                 fprintf(stderr, "cannot open %s\n", argv[i]);
                 return 2;
@@ -54,6 +66,6 @@
     int rc = nxi::run_import(inputs, opt, err);
     double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
     fprintf(stderr, "\n%s after %.1f s%s%s\n", rc ? "FAILED" : "OK", s, rc ? ": " : "", err.c_str());
-    for (auto& in : inputs) close(in.fd);
+    for (auto& in : inputs) _close(in.fd);
     return rc;
 }
'''

WINDOWS_CONTROL_PATCH = r'''--- a/android/wonder/importer/nximport.cpp
+++ b/android/wonder/importer/nximport.cpp
@@ -1274,7 +1274,7 @@

     if (opt.control_metadata) {
         if(ncas.size()>64) fail("metadata: too many contents");
-        std::ofstream report(opt.out_dir+"/native.json");
+        std::ofstream report(std::filesystem::path(acr_path(opt.out_dir+"/native.json")), std::ios::binary);
         report << "{\"schema\":1,\"contents\":[";
         for(size_t i=0;i<ncas.size();++i) {if(i) report << ",";control_extract(*ncas[i],opt.out_dir,unsigned(i),report);}
         report << "]}\n";report.close();if(!report) fail("metadata: receipt write failed");return 0;
'''


# Unified-diff context lines for blank source lines need one leading space.
# Add them at runtime so the Python source itself has no trailing whitespace.
WINDOWS_IMPORT_PATCH = ''.join(' \n' if line == '\n' else line
                               for line in WINDOWS_IMPORT_PATCH.splitlines(keepends=True))
WINDOWS_CONTROL_PATCH = ''.join(' \n' if line == '\n' else line
                                for line in WINDOWS_CONTROL_PATCH.splitlines(keepends=True))


def long_path(path):
    """Use extended Win32 paths for deep extracted trees, without global settings."""
    if not WINDOWS:
        return Path(path)
    value = os.path.abspath(path)
    if value.startswith('\\\\?\\'):
        return Path(value)
    return Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)


def is_link(path):
    # Windows directory junctions and other reparse points must not bypass the
    # private-output boundary. is_symlink alone does not detect junctions.
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


@contextmanager
def import_lock(path):
    # A persistent inode/first byte avoids the unlink/recreate lock race.
    with path.open('a+b') as lock:
        if WINDOWS:
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b'\0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ImportFailure('wrapper_already_running') from None
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ImportFailure('wrapper_already_running') from None
            yield


def native_compile_command(source, tool, control=False):
    """Compile only verified/copied upstream sources; never mutate the reference.

    Windows host adapters are original source, applied after the control patch
    when requested. Source provenance still records the unmodified pinned files.
    """
    if WINDOWS:
        for patch in (WINDOWS_IMPORT_PATCH, *([WINDOWS_CONTROL_PATCH] if control else [])):
            result = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(source),
                                     'apply', '-'], input=patch.encode('utf-8'),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            require(result.returncode == 0, 'windows_adapter_failed')
        (source / SOURCE / 'import_compat.h').write_text(WINDOWS_IMPORT_COMPAT, encoding='utf-8', newline='\n')
    return ['clang++', '-std=c++17', '-O2'] + [str(source / SOURCE / n) for n in SOURCES[:3]] + ['-o', str(tool)]


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    require(p.returncode == 0, 'git_check_failed')
    return p.stdout


def regular(path):
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'not_single_regular_file')
    return s


def private_path(repo, path):
    repo = repo.resolve()
    path = Path(os.path.abspath(path))
    allowed = repo / '.local/game-private'
    require(path != allowed and path.is_relative_to(allowed), 'output_not_private')
    current = repo
    for part in path.relative_to(repo).parts:
        current /= part
        require(not is_link(current), 'private_symlink')
    rel = path.relative_to(repo).as_posix()
    require(not git(repo, 'ls-files', '--', rel), 'output_tracked')
    p = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--no-index', '-q', rel], stderr=subprocess.DEVNULL)
    require(p.returncode == 0, 'output_not_ignored')
    return path


def secure_tree(root):
    root = long_path(root)
    require(not is_link(root), 'private_symlink')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory, dirs, files in os.walk(root, followlinks=False):
        os.chmod(directory, 0o700)
        for name in dirs:
            require(not is_link(Path(directory) / name), 'private_symlink')
        for name in files:
            path = Path(directory) / name
            regular(path)
            os.chmod(path, 0o600)


def atomic_json(path, obj):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    tmp = Path(name)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        os.chmod(tmp, 0o600)
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def event(log, phase, **fields):
    with log.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'time_unix': time.time(), 'phase': phase, **fields}, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())


def run_child(command, log, phase, env=None):
    start = time.monotonic()
    event(log, phase, state='started')
    with subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as p:
        try:
            while True:
                try:
                    rc = p.wait(timeout=10)
                    break
                except subprocess.TimeoutExpired:
                    event(log, phase, state='running', elapsed_seconds=round(time.monotonic() - start, 3))
        except BaseException:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            event(log, phase, state='interrupted', elapsed_seconds=round(time.monotonic() - start, 3))
            raise
    event(log, phase, state='finished', elapsed_seconds=round(time.monotonic() - start, 3), exit_code=rc)
    return rc


def digest(path):
    before = regular(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 << 20), b''):
            h.update(chunk)
    after = regular(path)
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), 'file_changed_during_hash')
    return {'size': after.st_size, 'sha256': h.hexdigest()}


def validate_dump(path):
    size = regular(path).st_size
    require(path.suffix.lower() == '.nsp', 'only_nsp_supported')
    with path.open('rb') as f:
        head = f.read(16)
        require(len(head) == 16 and head[:4] == b'PFS0', 'invalid_nsp_header')
        count, strings, _ = struct.unpack_from('<III', head, 4)
        require(0 < count <= 100000 and 0 < strings <= 16 << 20, 'invalid_nsp_table')
        data = 16 + count * 24 + strings
        require(data <= size, 'truncated_nsp_table')
        entries = f.read(count * 24)
        names = f.read(strings)
        for i in range(count):
            off, length, name, _ = struct.unpack_from('<QQII', entries, i * 24)
            require(off + length <= size - data and name < strings and b'\0' in names[name:], 'invalid_nsp_entry')
    return size


def validate_reference(ref):
    require(git(ref, 'rev-parse', 'HEAD').decode().strip() == PIN, 'reference_revision_mismatch')
    hashes = {}
    for name in SOURCES:
        rel = SOURCE + '/' + name
        raw = (ref / rel).read_bytes()
        require(raw == git(ref, 'show', PIN + ':' + rel), 'reference_source_modified')
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return hashes


def check_identity(old, new):
    require(old.get('sha256') == new.get('sha256') and old.get('size') == new.get('size'), 'dump_identity_mismatch')


def check_title(actual, expected):
    require(bool(re.fullmatch('[0-9A-F]{16}', actual)), 'invalid_title_id')
    require(expected is None or actual == expected.upper(), 'title_id_mismatch')


def parse_index(text, allow_revisions=False):
    rows = {}
    for line in text.splitlines():
        cols = line.split('\t')
        require(len(cols) == 4, 'malformed_index')
        kind, size, crc, rel = cols
        require(kind in ('exefs', 'romfs') and bool(re.fullmatch('[0-9]+', size)) and
                bool(re.fullmatch('[0-9a-fA-F]{8}', crc)), 'malformed_index')
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in rel and
                path.as_posix() == rel and ':' not in rel and '\x00' not in rel and len(path.parts) > 1 and
                ((kind == 'exefs' and rel.startswith('analysis/')) or
                 (kind == 'romfs' and rel.startswith('extract/romfs/'))), 'unsafe_index_path')
        if WINDOWS:
            require(all(part and part[-1] not in ' .' and
                        not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)
                        for part in path.parts), 'unsafe_index_path')
            require(not any(p.casefold() == rel.casefold() and p != rel for p in rows), 'duplicate_index_path')
        require(allow_revisions or rel not in rows, 'duplicate_index_path')
        rows[rel] = {'kind': kind, 'size': int(size), 'crc32': crc.lower()}
    require(bool(rows), 'empty_index')
    return rows


def verify_index(out, rows, log=None):
    out = long_path(out)
    start = time.monotonic()
    last = start
    for rel, record in rows.items():
        p = out / rel
        require(p.resolve().is_relative_to(out.resolve()), 'index_symlink_escape')
        require(regular(p).st_size == record['size'], 'output_size_mismatch')
        crc = 0
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(8 << 20), b''):
                crc = zlib.crc32(chunk, crc)
        require('%08x' % crc == record['crc32'], 'output_crc_mismatch')
        if log and time.monotonic() - last > 10:
            event(log, 'crc_validation', elapsed_seconds=round(time.monotonic() - start, 3))
            last = time.monotonic()
    return {'files': len(rows), 'bytes': sum(r['size'] for r in rows.values()),
            'elapsed_seconds': round(time.monotonic() - start, 3)}


def lz4_block(raw, size):
    require(0 <= size <= 512 << 20, 'segment_too_large')
    output = bytearray()
    i = 0
    def length(n):
        nonlocal i
        if n == 15:
            while True:
                require(i < len(raw), 'truncated_lz4')
                v = raw[i]
                i += 1
                n += v
                if v != 255:
                    break
        return n
    while i < len(raw):
        token = raw[i]
        i += 1
        n = length(token >> 4)
        require(i + n <= len(raw) and len(output) + n <= size, 'lz4_literal_bounds')
        output.extend(raw[i:i + n])
        i += n
        if i == len(raw):
            break
        require(i + 2 <= len(raw), 'truncated_lz4')
        distance = int.from_bytes(raw[i:i + 2], 'little')
        i += 2
        n = length(token & 15) + 4
        require(0 < distance <= len(output) and len(output) + n <= size, 'lz4_match_bounds')
        # Expand overlap in bulk; a one-byte distance must not cause a huge Python loop.
        pattern = bytes(output[-distance:])
        output.extend((pattern * ((n + distance - 1) // distance))[:n])
    require(len(output) == size, 'lz4_size_mismatch')
    return bytes(output)


def imports_inventory(image, nso):
    require(len(nso) >= 0xa0, 'invalid_nso_header')
    # NSO stores ro-relative dynstr at 0x90 and dynsym at 0x98.
    # Validate present extents before any unavailable/fallback path.
    symrel, symsize = struct.unpack_from('<II', nso, 0x98)
    strrel, strsize_header = struct.unpack_from('<II', nso, 0x90)
    robase, rosize = struct.unpack_from('<II', nso, 0x24)
    require(symsize % 24 == 0, 'invalid_symbol_size')
    require(not symrel or symsize, 'invalid_symbol_extent')
    require(not strrel or strsize_header, 'invalid_string_extent')
    if symsize:
        require(symrel + symsize <= rosize and robase + symrel + symsize <= len(image),
                'symbol_extent_bounds')
    if strsize_header:
        require(strrel + strsize_header <= rosize and robase + strrel + strsize_header <= len(image),
                'string_extent_bounds')
    if len(image) < 8:
        require(not symsize and not strsize_header, 'symbol_metadata_without_MOD0')
        return None, 'flat_image_has_no_MOD0_pointer'
    mod = struct.unpack_from('<I', image, 4)[0]
    if mod + 28 > len(image) or image[mod:mod + 4] != b'MOD0':
        require(not symsize and not strsize_header, 'symbol_metadata_without_MOD0')
        return None, 'MOD0_unavailable'
    dynamic = mod + struct.unpack_from('<i', image, mod + 4)[0]
    require(0 <= dynamic < len(image), 'invalid_dynamic_offset')
    tags = {}
    for off in range(dynamic, len(image) - 15, 16):
        tag, value = struct.unpack_from('<qQ', image, off)
        if tag == 0:
            break
        if tag in (4, 5, 6, 10, 11):
            require(tag not in tags or tags[tag] == value, 'conflicting_dynamic_metadata')
        tags.setdefault(tag, value)
    else:
        raise ImportFailure('unterminated_dynamic_table')
    if not any(t in tags for t in (4, 5, 6, 10, 11)):
        require(not symsize and not strsize_header, 'missing_dynamic_symbol_metadata')
        return None, 'dynamic_symbol_metadata_unavailable'
    require(all(t in tags for t in (5, 6, 10)), 'incomplete_dynamic_symbol_metadata')
    strings, symbols, strsize = tags[5], tags[6], tags[10]
    require(tags.get(11, 24) == 24 and strsize > 0 and
            strings + strsize <= len(image) and symbols < len(image), 'invalid_dynamic_tables')
    if strsize_header:
        require((robase + strrel, strsize_header) == (strings, strsize), 'string_extent_mismatch')
    if symsize:
        require(robase + symrel == symbols, 'symbol_extent_mismatch')
    hash_count = None
    if 4 in tags:
        h = tags[4]
        require(h + 8 <= len(image), 'invalid_symbol_hash')
        buckets, hash_count = struct.unpack_from('<II', image, h)
        require(buckets > 0 and hash_count > 0 and h + 8 + 4 * (buckets + hash_count) <= len(image),
                'invalid_symbol_hash')
    # Only a completely absent NSO dynsym extent permits the SysV-hash fallback.
    if symsize:
        count = symsize // 24
        require(hash_count is None or hash_count == count, 'symbol_count_mismatch')
    elif hash_count is not None:
        count = hash_count
    else:
        return None, 'symbol_count_unavailable'
    require(count <= 1000000 and symbols + count * 24 <= len(image), 'symbol_table_bounds')
    imports = []
    for i in range(count):
        name, info, _, section, value, size = struct.unpack_from('<IBBHQQ', image, symbols + i * 24)
        require(name < strsize, 'symbol_string_bounds')
        end = image.find(b'\0', strings + name, strings + strsize)
        require(end >= 0, 'unterminated_symbol')
        if section == 0 and name:
            imports.append({'name': image[strings + name:end].decode('utf-8', 'replace'),
                            'binding': info >> 4, 'type': info & 15})
    return imports, None


def nso_inventory(raw, flat, name):
    require(len(raw) >= 0x100 and raw[:4] == b'NSO0', 'invalid_nso_header')
    flags = struct.unpack_from('<I', raw, 0xc)[0]
    segments = []
    previous = 0
    for i, label in enumerate(('text', 'ro', 'data')):
        offset, memory, size = struct.unpack_from('<III', raw, 0x10 + i * 16)
        stored = struct.unpack_from('<I', raw, 0x60 + i * 4)[0] if flags & (1 << i) else size
        require(offset + stored <= len(raw) and memory + size <= len(flat) and memory >= previous, 'nso_segment_bounds')
        previous = memory + size
        blob = raw[offset:offset + stored]
        if flags & (1 << i):
            blob = lz4_block(blob, size)
        require(blob == flat[memory:memory + size], 'nso_flat_mismatch')
        sha = hashlib.sha256(blob).hexdigest()
        if flags & (1 << (i + 3)):
            require(sha == raw[0xa0 + i * 32:0xc0 + i * 32].hex(), 'nso_segment_hash_mismatch')
        segments.append({'name': label, 'file_offset': offset, 'memory_offset': memory,
                         'size': size, 'stored_size': stored, 'compressed': bool(flags & (1 << i)), 'sha256': sha})
    imports, reason = imports_inventory(flat, raw)
    return {'name': name, 'build_id': raw[0x40:0x60].hex(), 'segments': segments,
            'bss_size': struct.unpack_from('<I', raw, 0x3c)[0], 'imports': imports,
            'imports_unavailable_reason': reason}


def npdm_inventory(raw):
    require(len(raw) >= 0x80 and raw[:4] == b'META', 'invalid_npdm')
    offset, size = struct.unpack_from('<II', raw, 0x70)
    require(size >= 0x40 and offset >= 0x80 and offset + size <= len(raw) and
            raw[offset:offset + 4] == b'ACI0', 'invalid_npdm_aci0')
    return {'title_id': '%016X' % struct.unpack_from('<Q', raw, offset + 0x10)[0],
            'system_resource_size': struct.unpack_from('<I', raw, 0x14)[0],
            'main_thread_stack_size': struct.unpack_from('<I', raw, 0x1c)[0]}


def build_importer(ref, out, log):
    hashes = validate_reference(ref)
    tool = out / ('.wrapper/nximport.exe' if WINDOWS else '.wrapper/nximport')
    source = ref
    if WINDOWS:
        import windows_native
        # Standalone import also works outside a VS developer prompt.
        env = windows_native.developer_environment()
        source = out / '.wrapper/source'
        if source.exists():
            shutil.rmtree(source)
        (source / SOURCE).mkdir(parents=True)
        for name in SOURCES:
            shutil.copyfile(ref / SOURCE / name, source / SOURCE / name)
        require(subprocess.run(['git', 'init', '-q', str(source)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL).returncode == 0, 'git_check_failed')
    else:
        env = None
    command = native_compile_command(source, tool)
    require(run_child(command, log, 'compile_importer', env=env) == 0, 'importer_compile_failed')
    os.chmod(tool, 0o700)
    provenance = {'revision': PIN, 'sources_sha256': hashes, 'binary': digest(tool),
                  'compiler': 'clang++ -std=c++17 -O2'}
    if WINDOWS:
        provenance['host'] = 'windows-x64'
        provenance['adapters_sha256'] = {n: hashlib.sha256(raw.encode('utf-8')).hexdigest()
                                        for n, raw in (('native-import.patch', WINDOWS_IMPORT_PATCH),
                                                       ('import_compat.h', WINDOWS_IMPORT_COMPAT))}
        provenance['compiled_sources_sha256'] = {n: digest(source / SOURCE / n)['sha256'] for n in SOURCES}
    return tool, provenance


def make_inventory(out, rows):
    out = long_path(out)
    source = (out / '.import/source.txt').read_text(encoding='utf-8').strip()
    require(bool(re.match(r'^[0-9A-F]{16} ', source)), 'invalid_source_identity')
    title = source.split(' ', 1)[0]
    complete = (out / '.import/complete').read_text(encoding='utf-8').splitlines()
    require(len(complete) == 2 and complete[0] == source, 'completion_identity_mismatch')
    match = re.fullmatch(r'(\d+) romfs files, (\d+) bytes', complete[1])
    romrows = {k: v for k, v in rows.items() if v['kind'] == 'romfs'}
    require(match is not None and int(match[1]) == len(romrows) and
            int(match[2]) == sum(v['size'] for v in romrows.values()), 'completion_count_mismatch')
    actual = {p.relative_to(out).as_posix() for base in ('analysis', 'extract/romfs') for p in (out / base).rglob('*') if p.is_file()}
    require(actual == set(rows), 'unjournaled_or_missing_output')
    npdm = npdm_inventory((out / 'analysis/main.npdm').read_bytes())
    check_title(npdm['title_id'], title)
    npdm.update({'path': 'analysis/main.npdm', **digest(out / 'analysis/main.npdm')})
    modules = []
    raw_names = set()
    for path in sorted((out / 'exefs').iterdir()):
        require(path.is_file(), 'unexpected_exefs_directory')
        regular(path)
        raw_names.add(path.name)
        flat = out / 'analysis' / (path.name + '.bin')
        require(flat.is_file(), 'module_flat_missing')
        item = nso_inventory(path.read_bytes(), flat.read_bytes(), path.name)
        item.update({'nso': {'path': path.relative_to(out).as_posix(), **digest(path)},
                     'flat': {'path': flat.relative_to(out).as_posix(), **digest(flat)}})
        modules.append(item)
    expected = {Path(p).stem for p in rows if p.startswith('analysis/') and p.endswith('.bin')}
    require(raw_names == expected and 'main' in raw_names, 'module_inventory_mismatch')
    groups = defaultdict(lambda: {'files': 0, 'bytes': 0, 'extensions': Counter()})
    for rel, info in romrows.items():
        path = PurePosixPath(rel).relative_to('extract/romfs')
        group = groups[path.parts[0] if len(path.parts) > 1 else '.']
        group['files'] += 1
        group['bytes'] += info['size']
        group['extensions'][path.suffix.lower() or '<none>'] += 1
    return {'title_id': title, 'version': None,
            'version_unavailable_reason': 'Pinned importer does not extract CNMT or control metadata; base-only is not a version number.',
            'update': 'none' if source.endswith(' -') else 'present', 'source_identity': source,
            'npdm': npdm, 'modules': modules,
            'analysis_files': [{'path': rel, **digest(out / rel)} for rel in sorted(rows)
                               if rows[rel]['kind'] == 'exefs' and not rel.endswith('.bin')],
            'omitted_modules': [{'name': 'rtld', 'presence': 'not_retained_by_pinned_importer',
                                 'build_id': None, 'segments': None, 'imports': None,
                                 'reason': 'Importer unconditionally skips NSO named rtld before keep_exefs; source audit only, presence needs import log.'}],
            'romfs': {'files': len(romrows), 'bytes': sum(v['size'] for v in romrows.values()),
                      'top_level': dict(groups), 'shader_discovery': 'Extension inventory only; no containers decoded.'}}


def plan_next_actions(reference, repo, out, inventory):
    """Commands are handoff data only, never executed by this unit."""
    work = out.with_name(out.name + '-work')
    original_reference = reference
    reference = work / 'reference'
    venv = work / 'venv'
    gen = work / 'gen'
    actions = [{'cwd': str(repo), 'argv': ['mkdir', '-p', '-m', '700', str(work)],
                'gate': 'Task-owned sibling workspace; run commands with umask 077.'},
               {'cwd': str(repo), 'argv': ['git', 'clone', '--no-hardlinks', '--no-checkout', str(original_reference), str(reference)],
                'gate': 'Local original-source clone only; skip when this exact task-owned clone already exists.'},
               {'cwd': str(repo), 'argv': ['git', '-C', str(reference), 'checkout', '--detach', PIN],
                'gate': 'Require clean task-owned reference; never mutate another worker checkout.'},
               {'cwd': str(reference), 'argv': ['python3', '-m', 'venv', str(venv)],
                'gate': 'Prepare local dependencies only after approval of inventory.'},
               {'cwd': str(reference), 'argv': [str(venv / 'bin/python'), '-m', 'pip', 'install',
                                              'capstone==5.0.6', 'lz4==4.4.4', 'zstandard==0.24.0'],
                'gate': 'Check source hashes from dependencies.lock; package installation not run here.'}]
    for module in inventory['modules']:
        # Use the existing main/sdk runtime layout only when the observed set fits it.
        if {m['name'] for m in inventory['modules']} != {'main', 'sdk'}:
            return {'commands': actions, 'blocked': 'Additional modules require a reviewed address and loader plan.'}
        require(max(s['memory_offset'] + s['size'] for s in module['segments']) + module['bss_size'] < 0x10000000,
                'module_exceeds_runtime_spacing')
        base = '0x4000000000' if module['name'] == 'main' else '0x4010000000'
        actions.append({'cwd': str(reference), 'argv': [str(venv / 'bin/python'), '-m', 'recomp',
                         str(out / module['nso']['path']), str(gen / module['name']),
                         '--name', module['name'], '--base', base],
                        'gate': 'Requires approved inventory and local dependency environment; lifting not run here.'})
    patch = str(repo / 'runtime/patches/astral-bootstrap.patch')
    actions += [{'cwd': str(repo), 'argv': ['git', '-C', str(reference), 'apply', '--check', patch],
                 'gate': 'Blocked until independently reviewed adapter patch exists; no adapter implemented by this unit.'},
                {'cwd': str(repo), 'argv': ['git', '-C', str(reference), 'apply', patch],
                 'gate': 'Only after adapter patch review and successful apply --check.'}]
    return {'commands': actions, 'adapter_inputs': {'manifest': str(out / '.wrapper/manifest.json'),
            'data_root': str(out), 'romfs': str(out / 'extract/romfs'),
            'title_id': inventory['title_id'], 'system_resource_size': inventory['npdm']['system_resource_size']},
            'unresolved': ['CNMT/display version unavailable', 'rtld bytes and metadata omitted by pinned importer',
                           'Strict runtime adapter/loader patch pending', 'PKZ shader containers require format investigation']}


def execute(args):
    os.umask(0o077)
    repo = args.repo.resolve()
    out = private_path(repo, args.out)
    secure_tree(out)
    control = out / '.wrapper'
    control.mkdir(mode=0o700, exist_ok=True)
    lock_path = control / 'lock'
    with import_lock(lock_path):
        log = control / 'progress.jsonl'
        start = time.monotonic()
        try:
            event(log, 'preflight', state='started')
            validate_dump(args.dump)
            dump_stamp = args.dump.stat()
            identity = digest(args.dump)
            if args.expected_size is not None:
                require(identity['size'] == args.expected_size, 'dump_size_mismatch')
            if args.expected_sha256:
                require(identity['sha256'] == args.expected_sha256.lower(), 'dump_hash_mismatch')
            event(log, 'dump_hashed', size=identity['size'], sha256=identity['sha256'])
            receipt = control / 'input.json'
            owned = receipt.exists()
            if owned:
                check_identity(json.loads(receipt.read_text(encoding='utf-8')), identity)
            if not owned and not (out / '.import').exists():
                require(all(p.name == '.wrapper' for p in out.iterdir()), 'unowned_outputs_refused')
            completed = (out / '.import/complete').is_file()
            adoption = control / 'adoption.json'
            saved_adoption = json.loads(adoption.read_text(encoding='utf-8')) if adoption.exists() else None
            provenance = saved_adoption['provenance'] if saved_adoption else 'wrapper_import'
            parent = saved_adoption['parent'] if saved_adoption else None
            prior_manifest = control / 'manifest.json'
            if owned and not saved_adoption and prior_manifest.exists():
                previous = json.loads(prior_manifest.read_text(encoding='utf-8'))
                check_identity(previous['dump'], identity)
                provenance, parent = previous['provenance'], previous.get('parent')
                if parent:
                    atomic_json(adoption, {'provenance': provenance, 'parent': parent})
            if not owned and (out / '.import').exists():
                require(completed and args.adopt_state and args.adopt_tool and args.adopt_log, 'unowned_partial_import_refused')
                state = json.loads(args.adopt_state.read_text(encoding='utf-8'))
                require(state.get('state') == 'complete' and state.get('exit_code') == 0 and
                        state.get('reference_revision') == PIN and state.get('output') == str(out) and
                        state.get('tool_sha256') == digest(args.adopt_tool)['sha256'], 'adoption_receipt_mismatch')
                source = (out / '.import/source.txt').read_text(encoding='utf-8').strip()
                require((' ' + args.dump.name + '/') in source, 'adoption_dump_name_mismatch')
                provenance = 'adopted_parent_import_filename_and_size_then_current_hash_bound'
                # Only extract a fixed allowlisted observation from parent diagnostics.
                parent_log = args.adopt_log.read_text(encoding='utf-8')
                require('import complete:' in parent_log and 'OK after ' in parent_log, 'parent_log_not_complete')
                rtld_observed = bool(re.search(r'\bexefs\s+[^\r\n]*\brtld\b', parent_log))
                parent = {'state_sha256': digest(args.adopt_state)['sha256'],
                          'log_sha256': digest(args.adopt_log)['sha256'], 'tool_sha256': state['tool_sha256'],
                          'elapsed_seconds': state.get('elapsed_seconds'), 'rtld_observed': rtld_observed,
                          'binding_limit': 'Parent did not hash NSP before extraction. Filename/container size, title and output CRCs are corroborated; byte identity at original extraction is not independently provable.'}
                atomic_json(adoption, {'provenance': provenance, 'parent': parent})
            if not owned:
                atomic_json(receipt, identity)
            tool, importer = build_importer(args.reference.resolve(), out, log)
            if not completed:
                # File paths only; Python never reads or copies key contents.
                regular(args.prod_keys)
                keypaths = [str(args.prod_keys.resolve())]
                if args.title_keys:
                    regular(args.title_keys)
                    keypaths.append(str(args.title_keys.resolve()))
                command = [str(tool), '--exefs', '--out', str(out)]
                if args.expected_title:
                    check_title(args.expected_title.upper(), None)
                    command += ['--title', args.expected_title.upper()]
                command += keypaths + [str(args.dump.resolve())]
                require(run_child(command, log, 'import') == 0, 'importer_failed_resume_same_command')
            # Check safe paths before invoking upstream verification, which trusts its index.
            secure_tree(out)
            rows = parse_index((out / '.import/index.tsv').read_text(encoding='utf-8'))
            journal = parse_index((out / '.import/journal.tsv').read_text(encoding='utf-8'), allow_revisions=True)
            require(rows == journal, 'journal_index_mismatch')
            verification = verify_index(out, rows, log)
            os.chmod(tool, 0o700)
            require(run_child([str(tool), '--verify', '--out', str(out)], log, 'upstream_verify') == 0, 'upstream_verify_failed')
            inventory = make_inventory(out, rows)
            check_title(inventory['title_id'], args.expected_title)
            # Source identity records the program NCA length, not total NSP size.
            source_match = re.fullmatch(r'[0-9A-F]{16} (.+)/(\w+\.nca) (\d+) -', inventory['source_identity'])
            if parent:
                require(source_match is not None and source_match[1] == args.dump.name, 'adoption_source_mismatch')
                with args.dump.open('rb') as f:
                    head = f.read(16)
                    count, strings, _ = struct.unpack_from('<III', head, 4)
                    entries, names = f.read(count * 24), f.read(strings)
                    matches = []
                    for i in range(count):
                        off, size, name, _ = struct.unpack_from('<QQII', entries, i * 24)
                        nm = names[name:names.index(b'\0', name)].decode('utf-8', 'replace')
                        if nm == source_match[2]:
                            matches.append(size)
                    require(matches == [int(source_match[3])], 'adoption_nca_size_mismatch')
                inventory['omitted_modules'][0]['presence'] = 'observed_in_parent_import_log' if parent['rtld_observed'] else 'unverified'
            next_actions = plan_next_actions(args.reference.resolve(), repo, out, inventory)
            manifest = {'schema': 1, 'dump': {'path': str(args.dump.resolve()), **identity},
                        'importer': importer, 'provenance': provenance, 'parent': parent,
                        'validation': verification, 'next_actions': next_actions, **inventory,
                        'elapsed_seconds': round(time.monotonic() - start, 3),
                        'acceptance': 'Local extraction and static inventory only; no gameplay or platform acceptance.'}
            # Ensure input remained unchanged, including its content, through validation.
            check_identity(identity, digest(args.dump))
            final_stamp = args.dump.stat()
            require((dump_stamp.st_ino, dump_stamp.st_size, dump_stamp.st_mtime_ns) ==
                    (final_stamp.st_ino, final_stamp.st_size, final_stamp.st_mtime_ns), 'input_changed_during_run')
            manifest['dump']['mtime_ns'] = final_stamp.st_mtime_ns
            atomic_json(control / 'manifest.json', manifest)
            event(log, 'complete', elapsed_seconds=manifest['elapsed_seconds'], manifest_sha256=digest(control / 'manifest.json')['sha256'])
            print(json.dumps({'state': 'complete', 'manifest': str(control / 'manifest.json'),
                              'manifest_sha256': digest(control / 'manifest.json')['sha256']}))
        except BaseException as exc:
            code = str(exc) if isinstance(exc, ImportFailure) else 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'local_io_or_format_error'
            event(log, 'error', code=code, elapsed_seconds=round(time.monotonic() - start, 3))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--prod-keys', type=Path, required=True)
    parser.add_argument('--title-keys', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expected-title')
    parser.add_argument('--expected-size', type=int)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--adopt-state', type=Path)
    parser.add_argument('--adopt-tool', type=Path)
    parser.add_argument('--adopt-log', type=Path)
    args = parser.parse_args()
    try:
        execute(args)
        return 0
    except ImportFailure as exc:
        print(json.dumps({'state': 'blocked', 'error': str(exc)}))
    except (OSError, ValueError, KeyError, struct.error):
        print(json.dumps({'state': 'blocked', 'error': 'local_io_or_format_error'}))
    except KeyboardInterrupt:
        print(json.dumps({'state': 'interrupted', 'error': 'resume_same_command'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
