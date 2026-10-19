"""NX_GPU_TIMEOUT_S clamp (ios-astral-parity.patch, nvn_vk.cpp): 2 s default, at most 5 s. Compiled from the patch."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / 'runtime/patches/ios-astral-parity.patch'

FIXTURE = r'''
#include <cassert>
#include <cmath>
#include <cstdlib>
BLOCK
int main() {
    bool c = true;
    assert(gpu_timeout_seconds(nullptr, &c) == 2 && !c);
    assert(gpu_timeout_seconds("", &c) == 2 && !c);
    assert(gpu_timeout_seconds("abc", &c) == 2 && !c);
    assert(gpu_timeout_seconds("0", &c) == 2 && !c);
    assert(gpu_timeout_seconds("-3", &c) == 2 && !c);
    assert(gpu_timeout_seconds("nan", &c) == 2 && !c);
    assert(gpu_timeout_seconds("1.5", &c) == 1.5 && !c);
    assert(gpu_timeout_seconds("5", &c) == 5 && !c);
    assert(gpu_timeout_seconds("5.01", &c) == 5 && c);
    assert(gpu_timeout_seconds("20", &c) == 5 && c);
    assert(gpu_timeout_seconds("120", &c) == 5 && c);
    assert(gpu_timeout_seconds("inf", &c) == 5 && c);
    return 0;
}
'''


def new_side(path: str) -> str:
    part = PARITY.read_text().split(f'+++ b/{path}\n', 1)[1].split('\ndiff --git ', 1)[0]
    return '\n'.join(l[1:] for l in part.splitlines() if l[:1] in ('+', ' ', '')) + '\n'


class GpuTimeoutClampTest(unittest.TestCase):
    def test_clamp_and_default(self):
        cxx = shutil.which('clang++')
        if not cxx:
            self.skipTest('C++ compiler unavailable')
        src = new_side('runtime/src/nvn/nvn_vk.cpp')
        block = src.split('// BEGIN GPU TIMEOUT\n', 1)[1].split('// END GPU TIMEOUT', 1)[0]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'clamp.cpp'
            f.write_text(FIXTURE.replace('BLOCK', block))
            subprocess.run([cxx, '-std=c++20', str(f), '-o', str(Path(d) / 'clamp')], check=True, timeout=120,
                           capture_output=True)
            subprocess.run([str(Path(d) / 'clamp')], check=True, timeout=30)

    def test_astral_waits_use_the_bounded_helper_and_the_clamp_is_logged(self):
        vk = new_side('runtime/src/nvn/nvn_vk.cpp')
        self.assertIn('kGpuTimeoutDefaultS = 2, kGpuTimeoutMaxS = 5', vk)
        self.assertIn('can freeze or restart the', vk)
        self.assertIn('p_vkWaitForFences(device, count, fences, VK_TRUE, gpu_fence_timeout_ns())', vk)
        self.assertIn('p_vkAcquireNextImageKHR(g_device, g_swapchain, gpu_fence_timeout_ns()', vk)
        self.assertIn('if (r == VK_TIMEOUT || r == VK_NOT_READY) gpu_hung(', vk)
        for path in ('runtime/src/nvn/nvn_vk.cpp', 'runtime/src/nvn/nvn_frames.cpp', 'runtime/src/nvn/nvn_debug.cpp'):
            self.assertIn('gpu_wait_fences(', new_side(path), path)
        # The whole tree is scanned for unbounded waits in test_astral_default_profile.py.

if __name__ == '__main__':
    unittest.main()
