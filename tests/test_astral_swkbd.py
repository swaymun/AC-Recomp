"""CPU regression of the Astral software-keyboard overlay (astral-swkbd.patch).

The overlay is applied after the native overlay stack and astral-shared-font.patch on a fresh copy of the pinned
public runtime. The production hle_swkbd.cpp is compiled with a fixture that builds ShowKeyboardArg/String buffers
at the offsets of Astral's SDK and checks the deterministic name in UTF-16 and UTF-8, the length limits, small
buffers, the cancel path and the strict failures. The default profile compiles the file to nothing, and only Astral
builds list it. No game, applet or device is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime
import test_astral_shared_font as font

OVERLAY = 'astral-swkbd.patch'

FIXTURE = r'''
#include <cassert>
#include <cstdarg>
#include <cstdlib>
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
namespace plat {
std::string setting(const std::string& k) { auto v = std::getenv(("NX_" + k).c_str()); return v ? v : ""; }
}
}  // namespace nx
#include "hle_swkbd.cpp"
using namespace nx;
const char* SHOW = "_ZN2nn5swkbd12ShowKeyboardEPNS0_6StringERKNS0_15ShowKeyboardArgE";
#if defined(NX_ASTRAL_STRICT)
struct Call {
    std::vector<uint8_t> arg = std::vector<uint8_t>(0x500, 0), text = std::vector<uint8_t>(0x7d4, 0xcc);
    uint64_t str[2];
    Call(uint32_t max_len, uint32_t min_len, bool utf8) {
        std::memcpy(&arg[0x3ac], &max_len, 4); std::memcpy(&arg[0x3b0], &min_len, 4); arg[0x3bd] = utf8;
        uint64_t work = 0x1234000; std::memcpy(&arg[0x4d0], &work, 8);  // never dereferenced
        str[0] = uint64_t(text.data()); str[1] = text.size();
    }
    uint32_t run() { CPU c{}; c.x[0] = uint64_t(str); c.x[1] = uint64_t(arg.data()); hooks.at(SHOW)(c); return uint32_t(c.x[0]); }
    std::u16string utf16() const {
        std::u16string s; for (size_t i = 0; i + 1 < text.size(); i += 2) { char16_t u = char16_t(text[i] | text[i + 1] << 8); if (!u) break; s += u; }
        return s;
    }
    std::string utf8() const { return std::string(reinterpret_cast<const char*>(text.data())); }
    bool zero_after(size_t n) const { for (size_t i = n; i < text.size(); i++) if (text[i]) return false; return true; }
};
std::string error_of(Call& c) { try { c.run(); } catch (const std::runtime_error& e) { return e.what(); } return ""; }
#endif
int main() {
#if defined(NX_ASTRAL_STRICT)
    assert(hooks.size() == 1 && hooks.count(SHOW));
    unsetenv("NX_PLAYER_NAME"); unsetenv("NX_SWKBD_CANCEL");
    { Call c(9, 0, false); assert(c.run() == 0 && c.utf16() == u"Player" && c.zero_after(12)); }  // default, UTF-16
    { Call c(9, 0, true); assert(c.run() == 0 && c.utf8() == "Player" && c.zero_after(6)); }       // UTF-8 flag
    { Call c(3, 0, false); assert(c.run() == 0 && c.utf16() == u"Pla"); }                          // maximum
    { Call c(0, 0, false); assert(c.run() == 0 && c.utf16() == u"Player"); }                       // 0 = 500
    { Call c(10, 8, false); assert(c.run() == 0 && c.utf16() == u"PlayerPl"); }                    // minimum: repeat
    { Call c(4, 9, true); assert(c.run() == 0 && c.utf8() == "Play"); }                            // min clamped to max
    setenv("NX_PLAYER_NAME", "R\xc3\xa9x\xf0\x9f\x98\x80", 1);                                       // U+00E9, U+1F600
    { Call c(16, 0, false); assert(c.run() == 0 && c.utf16() == u"Réx\U0001F600" && c.zero_after(10)); }
    { Call c(16, 0, true); assert(c.run() == 0 && c.utf8() == "R\xc3\xa9x\xf0\x9f\x98\x80" && c.zero_after(8)); }
    { Call c(4, 0, false); assert(c.run() == 0 && c.utf16() == u"Réx"); }  // a surrogate pair is never split
    { Call c(16, 0, true); c.str[1] = 5; assert(c.run() == 0 && c.utf8() == "R\xc3\xa9x" && c.text[4] == 0 && c.text[5] == 0xcc); }
    { Call c(16, 0, false); c.str[1] = 7; assert(c.run() == 0 && c.text[0] == 'R' && c.text[2] == 0xe9 && c.text[4] == 0 && c.text[6] == 0 && c.text[7] == 0xcc); }
    { Call c(16, 0, false); c.str[0] = 0; assert(c.run() == 0 && c.text[0] == 0xcc); }               // no buffer: nothing written
    { Call c(16, 0, false); c.str[1] = 0; assert(c.run() == 0 && c.text[0] == 0xcc); }
    setenv("NX_SWKBD_CANCEL", "1", 1);
    { Call c(16, 0, false); assert(c.run() == 0x29f && c.zero_after(0)); }                        // ResultCanceled, empty
    unsetenv("NX_SWKBD_CANCEL");
    setenv("NX_PLAYER_NAME", "", 1);
    { Call c(16, 0, false); assert(c.run() == 0 && c.utf16() == u"Player"); }
    for (const char* bad : {"\xc0\xaf", "a\xed\xa0\x80", "\xf4\x90\x80\x80", "ab\xe2\x82"}) {
        setenv("NX_PLAYER_NAME", bad, 1);
        Call c(16, 0, false); assert(error_of(c).find("NX_PLAYER_NAME is not valid UTF-8") != std::string::npos);
    }
    unsetenv("NX_PLAYER_NAME");
    { Call c(16, 0, false); c.arg[0x3d0] = 1; assert(error_of(c).find("text check callbacks are not supported") != std::string::npos); }
    { Call c(16, 0, false); CPU cpu{}; cpu.x[1] = uint64_t(c.arg.data());
      try { hooks.at(SHOW)(cpu); assert(false); } catch (const std::runtime_error& e) { assert(std::string(e.what()).find("null String") != std::string::npos); } }
    std::cout << "PASS strict swkbd: deterministic name, UTF-16/UTF-8, limits, small buffers, cancel, strict failures\n";
#else
    assert(hooks.empty());
    std::cout << "PASS default: hle_swkbd.cpp registers nothing\n";
#endif
    return 0;
}
'''


class AstralSwkbdTests(unittest.TestCase):
    def test_overlay_strict_output_and_default_profile(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out, source, _ = font.stack_source(self, 'astral-swkbd-137')
        font.apply(self, source, font.OVERLAY)
        stacked = runtime.source_fingerprint(source)
        self.assertFalse((source / 'runtime/src/hle_swkbd.cpp').exists())
        self.assertNotIn('hle_swkbd', (source / 'CMakeLists.txt').read_text())
        font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         ['CMakeLists.txt', 'runtime/src/hle_swkbd.cpp'])
        cmake = (source / 'CMakeLists.txt').read_text()
        self.assertIn('if(NX_GAME STREQUAL "astral")\n    list(APPEND NX_RUNTIME_SOURCES runtime/src/hle_swkbd.cpp)\nendif()',
                      cmake)
        self.assertGreater(cmake.index('runtime/src/hle_swkbd.cpp'), cmake.index('set(NX_RUNTIME_SOURCES'))
        includes = ['-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src')]
        for name, flags in (('strict', ['-DNX_ASTRAL_STRICT=1']), ('default', [])):
            work = out / name
            work.mkdir()
            (work / 'fixture.cpp').write_text(FIXTURE)
            build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Wno-unused-function', *flags,
                                    *includes, str(work / 'fixture.cpp'), '-o', str(work / 'run')],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(work / 'run')], cwd=work, capture_output=True, text=True, timeout=60,
                                    env={k: v for k, v in os.environ.items() if not k.startswith('NX_')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS', result.stdout)
            print(result.stdout, end='')
        default = subprocess.run([compiler, '-std=c++20', '-E', '-P', *includes,
                                  str(source / 'runtime/src/hle_swkbd.cpp')],
                                 capture_output=True, text=True, timeout=60, check=True).stdout
        self.assertEqual(default.strip(), '', 'default profile must compile hle_swkbd.cpp to nothing')
        print('PASS default profile: hle_swkbd.cpp preprocesses to nothing; only Astral builds list it')
        shutil.rmtree(out)


if __name__ == '__main__':
    unittest.main()
