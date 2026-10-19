"""The Astral harness patch applies to the pinned Wonder Program.cs and is opt-in; no .NET is executed.

Uses the pinned public runtime (NVN_REFERENCE overrides it) and a temporary Git repository.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_runtime import PIN

HARNESS = ROOT / 'tools/astral_spirv_harness'
PATCH = HARNESS / 'astral-headerless-compute.patch'
FLAG = '--astral-headerless-compute'
UPSTREAM = 'bool compute = BitConverter.ToUInt32(code, 0) == ComputeMagic;'
OPT_IN = 'bool compute = BitConverter.ToUInt32(code, 0) == ComputeMagic || (HeaderlessCompute && start == 0);'


def reference():
    common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
    if not common.is_absolute():
        common = (ROOT / common).resolve()
    return Path(os.environ.get('NVN_REFERENCE', str(common.parent /
        '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))


class AstralSpirvHarnessTests(unittest.TestCase):
    def test_patch_applies_to_pinned_program_and_is_opt_in(self):
        upstream = subprocess.check_output(['git', '-C', str(reference()), 'show',
                                            PIN + ':tools/maxwell/spirv_harness/Program.cs'], text=True)
        self.assertEqual(upstream.count(UPSTREAM), 1)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (Path(tmp) / 'Program.cs').write_text(upstream)
            subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=tmp, check=True, capture_output=True)
            subprocess.run(['git', 'apply', str(PATCH)], cwd=tmp, check=True, capture_output=True)
            patched = (Path(tmp) / 'Program.cs').read_text()
            # Applying twice must fail rather than duplicate the change.
            again = subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=tmp, capture_output=True)
            self.assertNotEqual(again.returncode, 0)

        # Exactly one behavioural line changes: the upstream test, OR-ed with the flag-gated headerless rule.
        diff = PATCH.read_text().splitlines()
        removed = [l[1:].strip() for l in diff if l.startswith('-') and not l.startswith('---')]
        added = [l[1:].strip() for l in diff if l.startswith('+') and not l.startswith('+++')]
        self.assertEqual(removed, [UPSTREAM])
        code = [l for l in added if not l.startswith('//')]
        self.assertEqual(code, ['static bool HeaderlessCompute;',
                                f'HeaderlessCompute = args.Contains("{FLAG}");', OPT_IN])
        self.assertEqual(patched.replace(OPT_IN, UPSTREAM).count(UPSTREAM), 1)

        # The flag is false unless passed: no initializer and no other writer or reader.
        uses = re.findall(r'.*\bHeaderlessCompute\b.*', patched)
        self.assertEqual([u.strip() for u in uses],
                         ['static bool HeaderlessCompute;', f'HeaderlessCompute = args.Contains("{FLAG}");', OPT_IN])
        # Without the flag the patched source is the upstream one except for the inert declaration/assignment.
        stripped = '\n'.join(l for l in patched.splitlines()
                             if l.strip() not in code[:2] and not l.strip().startswith('// --astral-headerless')
                             and not l.strip().startswith('// and their control records program start 0'))
        self.assertEqual(stripped.replace(OPT_IN, UPSTREAM) + '\n', upstream)

    def test_project_has_no_private_paths(self):
        project = (HARNESS / 'AstralSpirvHarness.csproj').read_text()
        props = (HARNESS / 'Directory.Build.props').read_text()
        for text in (project, props, PATCH.read_text(), (HARNESS / 'README.md').read_text()):
            self.assertNotRegex(text, r'/(?:Users)/')
            self.assertNotIn('/root/', text)
        for dll in ('Ryujinx.Graphics.Shader', 'Ryujinx.Common', 'Spv.Generator'):
            self.assertIn(f'<HintPath>$(TranslatorDir)/{dll}.dll</HintPath>', project)
        self.assertIn('<Compile Include="$(HarnessSourceDir)/Program.cs" />', project)
        self.assertIn('../../.local/astral-spirv-harness/', props)  # build output stays ignored
        self.assertEqual(sorted(p.name for p in HARNESS.iterdir()),
                         ['AstralSpirvHarness.csproj', 'Directory.Build.props', 'README.md',
                          'astral-headerless-compute.patch'])  # no copied upstream sources


if __name__ == '__main__':
    unittest.main()
