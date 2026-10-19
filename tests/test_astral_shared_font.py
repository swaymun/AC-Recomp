"""CPU regression of the Astral shared-font overlay (astral-shared-font.patch).

The overlay is applied after the native overlay stack on a fresh copy of the pinned public runtime, and the production
hle_pl.cpp is compiled with a fixture: synthetic BFTTF fonts (made-up bytes, both SDK keys, odd sizes) are encoded by
an encoder written here, and the hooks must decode them into the pl shared-memory layout, return the TrueType address
and size as the SDK's GetSharedFontAddress/Size do, fill nn::pl::GetSharedFont's SharedFontData records, and fail
clearly on missing or invalid fonts. Before the overlay, GetSharedFont is unhooked and the address is the header's.
The default profile's preprocessed source must be identical to the unpatched one. No game, font or device is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime
from test_nvn_cube_storage import ORDER as CUBE_ORDER, OVERLAY as CUBE
from test_nvn_window_depth import preprocessed

ORDER = (*CUBE_ORDER, CUBE)
OVERLAY = 'astral-shared-font.patch'

FIXTURE = r'''
#include <cassert>
#include <cstdarg>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <vector>
#include <nx/runtime.h>
#include "platform.h"
namespace nx {
std::map<std::string, HleFn> hooks;
HleRegistrar::HleRegistrar(const char* n, HleFn f) { hooks[n] = f; }
void log(const char*, ...) {}
[[noreturn]] void fatal(const char* f, ...) {
    char b[1024]; va_list a; va_start(a, f); vsnprintf(b, sizeof b, f, a); va_end(a); throw std::runtime_error(b);
}
std::vector<std::pair<uint64_t, uint64_t>> allocs;
uint64_t kernel_alloc(uint64_t size, uint64_t) {
    void* p = std::calloc(1, size); allocs.push_back({uint64_t(p), size}); return uint64_t(p);
}
namespace plat {
FILE* fopen_utf8(const std::string& p, const char* m) { return std::fopen(p.c_str(), m); }
int64_t ftell64(FILE* f) { return ftello(f); }
int fseek64(FILE* f, int64_t o, int w) { return fseeko(f, o, w); }
std::string data_root() { return "data"; }
std::string setting(const std::string& k) { auto v = std::getenv(("NX_" + k).c_str()); return v ? v : ""; }
}  // namespace plat
}  // namespace nx
#include "hle_pl.cpp"
using namespace nx;
using Bytes = std::vector<uint8_t>;
const char* kFiles[6] = {"nintendo_udsg-r_std_003.bfttf", "nintendo_udsg-r_org_zh-cn_003.bfttf",
    "nintendo_udsg-r_ext_zh-cn_003.bfttf", "nintendo_udjxh-db_zh-tw_003.bfttf", "nintendo_udsg-r_ko_003.bfttf",
    "nintendo_ext_003.bfttf"};
uint32_t swap(uint32_t v) { return __builtin_bswap32(v); }
Bytes ttf(int type, size_t n, const char* tag = "\x00\x01\x00\x00") {
    Bytes b(n); std::memcpy(b.data(), tag, 4);
    for (size_t i = 4; i < n; i++) b[i] = uint8_t(type * 37 + i * 11 + (i >> 9));
    return b;
}
// Independent encoder: word 0 is the magic and word 1 the size, both big-endian XOR key, stored little-endian; the
// data words are little-endian XOR the byte-swapped key; the tail is zero-padded.
Bytes encode(const Bytes& t, uint32_t key) {
    Bytes o(8 + (t.size() + 3) / 4 * 4, 0);
    uint32_t w0 = swap(swap(0x18029A7F) ^ key), w1 = swap(uint32_t(t.size()) ^ key);
    std::memcpy(o.data(), &w0, 4); std::memcpy(o.data() + 4, &w1, 4);
    std::memcpy(o.data() + 8, t.data(), t.size());
    for (size_t i = 8; i < o.size(); i += 4) { uint32_t w; std::memcpy(&w, &o[i], 4); w ^= swap(key); std::memcpy(&o[i], &w, 4); }
    return o;
}
void put(const std::string& path, const Bytes& b) {
    std::filesystem::create_directories(std::filesystem::path(path).parent_path());
    std::ofstream(path, std::ios::binary).write(reinterpret_cast<const char*>(b.data()), b.size());
}
uint64_t call(const char* sym, uint64_t a = 0, uint64_t b = 0, uint64_t c2 = 0, uint64_t d = 0) {
    CPU c{}; c.x[0] = a; c.x[1] = b; c.x[2] = c2; c.x[3] = d; hooks.at(sym)(c); return c.x[0];
}
const char* ADDR = "_ZN2nn2pl20GetSharedFontAddressENS0_14SharedFontTypeE";
const char* SIZE = "_ZN2nn2pl17GetSharedFontSizeENS0_14SharedFontTypeE";
const char* STATE = "_ZN2nn2pl22GetSharedFontLoadStateENS0_14SharedFontTypeE";
const char* GET = "_ZN2nn2pl13GetSharedFontEPiPNS0_14SharedFontDataEiNS_8settings12LanguageCodeE";
std::string error_of(const char* sym, uint64_t a = 0) {
    try { call(sym, a); } catch (const std::runtime_error& e) { return e.what(); }
    return "";
}
bool has(const std::string& s, const std::string& part) { return s.find(part) != std::string::npos; }
int main() {
#if defined(NX_ASTRAL_STRICT) && !defined(BEFORE)
    assert(hooks.size() == 4 && hooks.count(GET));
    Bytes fonts[6];
    const size_t sizes[6] = {4097, 30001, 1234, 9999, 20002, 515};  // odd sizes: partial last words
    for (int t = 0; t < 6; t++) fonts[t] = ttf(t, sizes[t], t == 4 ? "OTTO" : "\x00\x01\x00\x00");
    auto write_all = [&](const std::string& dir) {
        for (int t = 0; t < 6; t++) put(dir + "/" + kFiles[t], encode(fonts[t], t == 5 ? 0xA6018502 : 0x49621806));
    };
    // Missing: the data root's shared-fonts/ is the default, NX_SHARED_FONT_DIR overrides it.
    unsetenv("NX_SHARED_FONT_DIR");
    assert(has(error_of(ADDR), "missing shared font data/shared-fonts/nintendo_udsg-r_std_003.bfttf"));
    setenv("NX_SHARED_FONT_DIR", "override", 1);
    write_all("override");
    std::filesystem::remove(std::string("override/") + kFiles[4]);
    assert(has(error_of(SIZE, 1), "missing shared font override/nintendo_udsg-r_ko_003.bfttf"));
    put(std::string("override/") + kFiles[4], Bytes(64, 0x41));
    assert(has(error_of(GET), "nintendo_udsg-r_ko_003.bfttf is not a BFTTF font"));
    put(std::string("override/") + kFiles[4], encode(ttf(4, 100, "XXXX"), 0x49621806));
    assert(has(error_of(STATE), "does not decode to TrueType/OpenType"));
    Bytes cut = encode(fonts[4], 0x49621806); cut.resize(cut.size() - 8);
    put(std::string("override/") + kFiles[4], cut);
    assert(has(error_of(ADDR), "nintendo_udsg-r_ko_003.bfttf has an invalid size"));
    Bytes big = ttf(0, 3000000);
    for (int t = 0; t < 6; t++) put(std::string("big/") + kFiles[t], encode(big, 0x49621806));
    setenv("NX_SHARED_FONT_DIR", "big", 1);
    assert(has(error_of(ADDR), "exceed the 0x1100000-byte region"));
    assert(allocs.empty());  // nothing is mapped until every font is valid
    // Valid fonts in the data root.
    unsetenv("NX_SHARED_FONT_DIR");
    write_all("data/shared-fonts");
    const uint64_t a0 = call(ADDR, 0);
    assert(allocs.size() == 1 && allocs[0].second == 0x1100000);
    const uint64_t base = allocs[0].first;
    uint64_t at = 0;
    for (int t = 0; t < 6; t++) {
        const uint64_t addr = call(ADDR, t), size = call(SIZE, t);
        assert(addr == base + at + 8 && size == fonts[t].size());           // TrueType data, back to back from 0
        assert(ld<uint32_t>(addr - 8) == 0x18029A7F);                        // plain magic
        assert(ld<uint32_t>(addr - 4) == swap(uint32_t(size) ^ 0x49621806)); // encoded size, as pl:u
        assert(std::memcmp(reinterpret_cast<void*>(addr), fonts[t].data(), size) == 0);
        assert(call(STATE, t) == 1);
        at += 8 + size;
    }
    assert(a0 == base + 8 && allocs.size() == 1);
    // GetSharedFont: *outCount = 6 whatever count is; min(count, 6) records {type, address, size}, stride 0x18.
    std::vector<uint8_t> out(6 * 0x18, 0xee);
    int32_t n = -1;
    assert(call(GET, uint64_t(&n), uint64_t(out.data()), 3, 0x53552d6e65ull) == 1 && n == 6);
    for (int i = 0; i < 6; i++) {
        const uint64_t e = uint64_t(out.data()) + 0x18 * i;
        if (i < 3) {
            assert(ld<uint32_t>(e) == uint32_t(i) && ld<uint64_t>(e + 8) == call(ADDR, i) &&
                   ld<uint64_t>(e + 0x10) == fonts[i].size() && ld<uint32_t>(e + 4) == 0xeeeeeeee);
        } else {
            assert(ld<uint64_t>(e) == 0xeeeeeeeeeeeeeeeeull && ld<uint64_t>(e + 0x10) == 0xeeeeeeeeeeeeeeeeull);
        }
    }
    assert(call(GET, uint64_t(&n), uint64_t(out.data()), 9, 0) == 1 && n == 6);
    assert(ld<uint32_t>(uint64_t(out.data()) + 0x18 * 5) == 5 && ld<uint64_t>(uint64_t(out.data()) + 0x18 * 5 + 8) == call(ADDR, 5));
    n = -1;
    assert(call(GET, uint64_t(&n), 0, 0, 0) == 1 && n == 6);
    assert(has(error_of(GET), "GetSharedFont with a null output"));
    assert(has(error_of(ADDR, 6), "invalid SharedFontType 6") && has(error_of(SIZE, 0xffffffff), "invalid SharedFontType"));
    std::cout << "PASS strict shared fonts: firmware BFTTF only, pl layout, TrueType address/size, GetSharedFont records, clear failures\n";
#else
    // Before the overlay (and in the default profile): GetSharedFont falls through to the SDK's pl:u, and the address
    // is the 8-byte header's, which Astral's LoadFont (no Decode) would take as TrueType.
    assert(hooks.size() == 3 && !hooks.count(GET));
    Bytes t = ttf(0, 333);
    put("data/fonts/shared_0.ttf", t);
    const uint64_t addr = call(ADDR, 0);
    assert(ld<uint32_t>(addr) == 0x18029A7F && call(SIZE, 0) == t.size() + 8);
    assert(std::memcmp(reinterpret_cast<void*>(addr + 8), t.data(), t.size()) == 0);
    std::cout << "PASS before/default: GetSharedFont unhooked; address is the header, size includes it\n";
#endif
    return 0;
}
'''


def stack_source(test, tag):
    common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
    if not common.is_absolute():
        common = (ROOT / common).resolve()
    reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
        '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
    out = ROOT / '.local' / tag / ('verify-' + uuid.uuid4().hex)
    out.mkdir(parents=True)
    source = out / 'source'
    stacked = runtime.prepare_source(reference, source, [ROOT / 'runtime/patches' / n for n in ORDER])
    return out, source, stacked


def apply(test, source, name):
    patch = ROOT / 'runtime/patches' / name
    subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, capture_output=True)
    test.assertNotRegex(patch.read_text(), r'/(?:Users|home)/')
    return patch


class AstralSharedFontTests(unittest.TestCase):
    def test_overlay_strict_layout_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out, source, stacked = stack_source(self, 'astral-shared-font-137')
        includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src')]

        def run(name, flags):
            work = out / name
            work.mkdir()
            fixture = work / 'fixture.cpp'
            fixture.write_text(FIXTURE)
            build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wno-unused-function', *flags, *includes,
                                    str(fixture), '-o', str(work / 'run')], capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(work / 'run')], cwd=work, capture_output=True, text=True, timeout=120,
                                    env={k: v for k, v in os.environ.items() if not k.startswith('NX_')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS', result.stdout)
            print(result.stdout, end='')

        run('before', ['-DNX_ASTRAL_STRICT=1', '-DBEFORE=1'])
        apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in applied if applied.get(k) != stacked.get(k)), ['runtime/src/hle_pl.cpp'])
        run('strict', ['-DNX_ASTRAL_STRICT=1'])
        run('default', [])

        name = source / 'runtime/src/hle_pl.cpp'
        for flags in (['-DNX_ASTRAL_STRICT=1'], []):
            check = subprocess.run([compiler, '-std=c++20', '-Wall', *flags, *includes, '-fsyntax-only', str(name)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        patched = preprocessed(compiler, includes, name)
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(ROOT / 'runtime/patches' / OVERLAY)],
                       check=True, capture_output=True)
        self.assertEqual(patched, preprocessed(compiler, includes, name), 'default profile differs')
        print('PASS changed TU: strict/default syntax; default profile preprocesses identically')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
