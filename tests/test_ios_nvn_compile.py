"""Compile the shipped diagnostic conditional and execute real synthetic tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'runtime/patches/ios-nvn-compile.patch'


def diagnostic_source():
    # The overlay's context contains the entire unchanged external-tool block.
    # Extract the resulting source, never a test reimplementation of the guard.
    lines = PATCH.read_text().splitlines()
    source = '\n'.join(line[1:] for line in lines
                       if line.startswith((' ', '+')) and not line.startswith('+++'))
    start = source.index('        if (const char* opt =')
    end = source.index('        VkShaderModuleCreateInfo ci', start)
    return source[start:end]


class IOSNVNCompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.compiler = shutil.which('clang++')
        if not self.compiler:
            self.skipTest('C++ compiler unavailable')
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('NX_SPIRV_OPT', 'NX_SPIRV_TOOL')}
        self.env['FIXTURE_LOG'] = str(self.d / 'tool.log')
        self.env['PATH'] = str(self.d) + os.pathsep + self.env['PATH']

    def compile(self, simulator):
        source = self.d / 'fixture.cpp'
        source.write_text('''#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <unistd.h>
#if defined(NX_IOS_RUNTIME)
// Emulate the SDK restriction: even a dormant reference must fail compilation.
namespace std { int system(const char*) __attribute__((unavailable("iOS system unavailable"))); }
#endif
namespace nx { [[noreturn]] void fatal(const char* text) { throw std::runtime_error(text); } }
int process_id() { std::puts("process-id-called"); return getpid(); }
struct Shader { std::string hash = "synthetic-hash"; };
int main() {
 Shader shader; auto* s = &shader; std::vector<uint32_t> code(6, 7);
 try {
''' + diagnostic_source() + '''
 } catch (const std::runtime_error& e) { std::puts(e.what()); return 73; }
 std::printf("words=%zu first=%u\\n", code.size(), code[0]);
 return 0;
}
''')
        binary = self.d / ('simulator' if simulator else 'host')
        subprocess.run([self.compiler, '-std=c++20', *(['-DNX_IOS_RUNTIME=1'] if simulator else []),
                        str(source), '-o', str(binary)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return binary

    def run_fixture(self, binary, **env):
        return subprocess.run([str(binary)], cwd=self.d, env=dict(self.env, **env),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)

    def tool(self):
        script = self.d / 'spirv-opt'
        script.write_text('''#!/usr/bin/env python3
import json, os, pathlib, struct, sys
args = sys.argv[1:]
if '-o' in args:
    source, output = args[-3], args[-1]
else:
    source, output, shader_hash = args
    assert shader_hash == 'synthetic-hash'
assert pathlib.Path(source).read_bytes() == struct.pack('<6I', *([7] * 6))
pathlib.Path(os.environ['FIXTURE_LOG']).write_text(json.dumps(args))
pathlib.Path(output).write_bytes(struct.pack('<8I', *([19] * 8)))
''')
        script.chmod(0o755)
        return script

    def test_simulator_tool_and_opt_fail_before_files_or_subprocess(self):
        binary = self.compile(True)
        for env in ({'NX_SPIRV_TOOL': str(self.tool())}, {'NX_SPIRV_OPT': '--synthetic'}):
            result = self.run_fixture(binary, **env)
            self.assertEqual(result.returncode, 73, result.stdout)
            self.assertIn('unsupported iOS host operation: external SPIR-V tool', result.stdout)
            self.assertNotIn('process-id-called', result.stdout)
            self.assertFalse((self.d / 'tool.log').exists())
            self.assertNotIn('words=', result.stdout)

    def test_simulator_without_diagnostic_request_does_not_claim_compilation(self):
        result = self.run_fixture(self.compile(True))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, 'words=6 first=7\n')

    def test_desktop_preserves_both_commands_output_loading_and_cleanup(self):
        import json
        binary = self.compile(False)
        for env in ({'NX_SPIRV_TOOL': str(self.tool())}, {'NX_SPIRV_OPT': '--synthetic'}):
            result = self.run_fixture(binary, **env)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('words=8 first=19', result.stdout)
            args = json.loads((self.d / 'tool.log').read_text())
            paths = [Path(arg) for arg in args if arg.startswith('/tmp/nx_spv_')]
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(not p.exists() for p in paths))

    def test_overlay_owns_only_evidenced_external_command_file(self):
        paths = [line.split(' b/', 1)[1] for line in PATCH.read_text().splitlines()
                 if line.startswith('diff --git ')]
        self.assertEqual(paths, ['runtime/src/nvn/nvn_pipeline.cpp'])
        self.assertEqual(PATCH.read_text().count('+            nx::fatal('), 1)


if __name__ == '__main__':
    unittest.main()
