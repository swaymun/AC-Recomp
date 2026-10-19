"""Exercise the patched production NVN query through the real HLE registry.

Only synthetic output storage and host adapters; no game launch or GPU needed.
The pinned public runtime is required (override with NVN_REFERENCE).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime

PATCHES = ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
           'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch',
           'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch',
           'astral-hid.patch', 'astral-controller-support.patch', 'astral-vi.patch',
           'astral-nvn-init.patch')

FIXTURE = r'''
#include <cassert>
#include <iostream>
#include <stdexcept>
#include "kernel.h"
#include "platform.h"
namespace nx {
bool commit(uint64_t,uint64_t) {return true;}
void vm_set(uint64_t,uint64_t,uint32_t,uint32_t) {}
void backtrace(CPU&) {}
namespace plat {
std::string data_root() {return ".";}
void log_line(const char*) {}
[[noreturn]] void exit_process(int) {throw std::runtime_error("fatal");}
}
}
#include "loader.cpp"
#include "nvn/nvn_device.cpp"
using namespace nx;
int query(uint64_t pname, uint64_t device) {
    uint32_t output[3] = {0xaabbccdd, 0xdeadbeef, 0x11223344};
    CPU c{};
    c.x[0] = device;
    c.x[1] = pname;
    c.x[2] = uint64_t(output + 1);
    c.x[19] = 0x123456789abcdef0ULL;
    c.x[30] = 0x987654321ULL;
    call(c, hle_address("nvnDeviceGetInteger"));
    assert(output[0] == 0xaabbccdd && output[2] == 0x11223344);
    assert(c.x[0] == device && c.x[1] == pname && c.x[2] == uint64_t(output + 1));
    assert(c.x[19] == 0x123456789abcdef0ULL && c.x[30] == 0x987654321ULL);
    return int32_t(output[1]);
}
int main() {
    assert(hle_lookup("nvnDeviceGetInteger"));
#if defined(NX_ASTRAL_STRICT)
    constexpr int major = 53, minor = 310;
#else
    constexpr int major = 55, minor = 15;
#endif
    // Version queries describe the API and must not dereference an NVNdevice.
    for (uint64_t device : {0ULL, 1ULL, 0x12345678ULL}) {
        assert(query(0, device) == major);
        assert(query(1, device) == minor);
        // NVNdeviceInfo is a 32-bit enum even when upper register bits are set.
        assert(query(0xfedcba9800000000ULL, device) == major);
        assert(query(0xfedcba9800000001ULL, device) == minor);
    }
    // Existing non-version capabilities and unknown-query behavior are retained.
    assert(query(2, 0) == 14);
    assert(query(3, 0) == 0x10000);
    assert(query(81, 0) == 0x10000);
    assert(query(84, 0) == 0x4000);
    assert(query(0xffffffff, 0) == 0);
    CPU c{}; c.x[1] = 1; // inherited null-output behavior
    call(c, hle_address("nvnDeviceGetInteger"));
    std::cout << "PASS production NVN registry: API " << major << "." << minor
              << ", 32-bit writes/enum, register preservation, other queries\n";
}
'''


class NvnInitTests(unittest.TestCase):
    def test_production_query_profiles(self):
        common = Path(subprocess.check_output(
            ['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'pinned runtime required via NVN_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/nvn-init-070' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / name for name in PATCHES]
        fingerprint = runtime.prepare_source(reference, output / 'source', patches)
        fixture = output / 'fixture.cpp'
        fixture.write_text(FIXTURE)
        source = output / 'source'
        results = []
        for profile, flags in (('astral', ['-DNX_ASTRAL_STRICT=1']), ('default', [])):
            binary = output / profile
            argv = [compiler, '-std=c++20', '-pthread', '-DNX_APPLE_HIGH_MEMORY=1', *flags,
                    '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'),
                    str(fixture), '-o', str(binary)]
            build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            (output / (profile + '-compile.log')).write_text(build.stdout + build.stderr)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary)], cwd=output, capture_output=True,
                                    text=True, timeout=10)
            (output / (profile + '-result.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS production NVN registry', result.stdout)
            print(result.stdout, end='')
            results.append({'profile': profile, 'compile': argv, 'exit_code': result.returncode,
                            'output': result.stdout, 'binary_sha256': runtime.sha(binary)})
        (output / 'receipt.json').write_text(json.dumps({
            'pin': runtime.PIN, 'patches': {p.name: runtime.sha(p) for p in patches},
            'source': fingerprint, 'results': results,
            'limits': 'CPU-only query/registry test; no rendering or gameplay acceptance.'
        }, indent=2) + '\n')
        print('private receipt:', output / 'receipt.json')
        shutil.rmtree(source)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
