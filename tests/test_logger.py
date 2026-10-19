"""Compile the shipped logger, IPC and kernel dispatch against synthetic host memory."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime


class LoggerTests(unittest.TestCase):
    def test_actual_compiled_logger(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++ compiler required')
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            (d / 'nx').mkdir()
            for name in ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp',
                         'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp'):
                (d / name).write_text(runtime.patched_source(
                    ROOT / 'runtime/patches/astral-bootstrap.patch', 'runtime/src/' + name))
            for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
                (d / name).write_text('// Host declarations supplied by synthetic fixture.\n')
            host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
            host = host.replace('VmInfo vm_query(uint64_t) { unexpected(); }',
                                'std::vector<VmInfo> fixture_regions;\n'
                                'VmInfo vm_query(uint64_t at) {\n'
                                ' for (auto v : fixture_regions) if (at >= v.addr && at-v.addr < v.size) return v;\n'
                                ' return {at, 4096, 0, 0};\n}\n')
            host = host.replace('void log(const char*, ...) {}',
                                'std::vector<std::string> fixture_logs;\n'
                                'void log(const char* format, ...) { char text[512]; va_list args;\n'
                                ' va_start(args,format); vsnprintf(text,sizeof text,format,args); va_end(args);\n'
                                ' fixture_logs.emplace_back(text); }')
            (d / 'kernel-host.h').write_text(host)
            (d / 'astral_control_context.h').write_text(
                '#pragma once\n#define NX_CONTROL_CONTEXT {1,1,0,{0},"' + 'a' * 64 + '"}\n')
            (d / 'test_logger.cpp').write_text((ROOT / 'tests/test_logger.cpp').read_text())
            command = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1',
                       '-I', str(d), str(d / 'test_logger.cpp'), '-o', str(d / 'fixture')]
            build = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(d / 'fixture')], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for expected in ('serialized factory and Log', 'chunking and interleaving',
                             'malformed requests atomic', 'bounded sink and streams',
                             'strict unsupported commands and ownership'):
                self.assertIn('PASS ' + expected, result.stdout)
            print(result.stdout, end='')


if __name__ == '__main__':
    unittest.main()
