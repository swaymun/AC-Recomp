"""GPU wait-scanner coverage; the archived simulator-only clamp is no longer shipped.

These synthetic checks test the scanner, not a desktop runtime timeout guarantee.
"""
import unittest

from test_astral_default_profile import unbounded_waits


class GpuWaitScannerTest(unittest.TestCase):
    def test_unbounded_waits_include_nested_arguments_and_all_ones_literals(self):
        for timeout in ('UINT64_MAX', '~0ull', '~uint64_t(0)', '0xffffffffffffffff'):
            for api in ('WaitForFences', 'AcquireNextImageKHR', 'AcquireNextImage2KHR',
                        'WaitSemaphores', 'WaitSemaphoresKHR'):
                with self.subTest(timeout=timeout, api=api):
                    call = f'p_vk{api}(device(), args, {timeout})'
                    self.assertEqual(unbounded_waits('\n' + call + ';'), [(2, call)])

    def test_bounded_waits_are_not_reported(self):
        self.assertEqual(unbounded_waits(
            'p_vkWaitForFences(d, 1, &f, VK_TRUE, 2000000000ull);\n'
            'p_vkAcquireNextImageKHR(d, chain, timeout_ns(), s, f, &index);'), [])


if __name__ == '__main__':
    unittest.main()
