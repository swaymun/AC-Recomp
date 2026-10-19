"""Tests for tools/acr_build.py, the one-command player build, and runtime/patches/series.macos.

Everything runs on synthetic inputs in temporary directories: fake NSP/key files (never opened), fake upstream Git
repositories with a stand-in recompiler, synthetic fonts and synthetic harness results. No game data, network, .NET
or compiler toolchain is needed, and nothing is downloaded.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import acr_build as acr  # noqa: E402


def git(*args, cwd=None):
    return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def init_repo(path, files):
    path.mkdir(parents=True)
    git('init', '-q', path)
    git('-C', path, 'config', 'user.email', 'test@example.com')
    git('-C', path, 'config', 'user.name', 'Test')
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    git('-C', path, 'add', '-A')
    git('-C', path, 'commit', '-q', '-m', 'base')
    return git('-C', path, 'rev-parse', 'HEAD')


def make_patch(repo, rel, new_text):
    """A git-apply patch that turns repo's committed `rel` into new_text (made with git diff, then reset)."""
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(new_text)
    git('-C', repo, 'add', '-N', rel)
    diff = git('-C', repo, 'diff') + '\n'
    git('-C', repo, 'reset', '-q', '--hard')
    git('-C', repo, 'clean', '-qfd')
    return diff


def fake_ttf(n, size=64):
    return b'\0\1\0\0' + bytes((n * 7 + i) % 251 for i in range(size - 4))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.nsp = self.tmp / 'in/game.nsp'
        self.nsp.parent.mkdir()
        self.nsp.write_bytes(b'\0' * 16)
        self.keys = self.tmp / 'in/prod.keys'
        self.keys.write_text('not a real key file\n')

    def args(self, *extra, out=None):
        return acr.parse(['--nsp', str(self.nsp), '--keys', str(self.keys), '--out', str(out or self.tmp / 'out'),
                          *extra])

    def ctx(self, *extra, root=ROOT, out=None):
        return acr.Context(self.args(*extra, out=out), root=root, out=io.StringIO())


class SeriesTest(unittest.TestCase):
    def test_series_matches_the_overlay_tests(self):
        import test_astral_texel_coalesce as last  # the newest overlay test composes every earlier one (ORDER)
        series = acr.read_series(ROOT / 'runtime/patches/series.macos')
        self.assertEqual(last.ORDER[-1], last.OVERLAY)
        self.assertEqual(series, list(last.ORDER))

    def test_series_covers_every_native_patch(self):
        series = set(acr.read_series(ROOT / 'runtime/patches/series.macos'))
        linux = set(acr.read_series(ROOT / 'runtime/patches/series.linux'))  # series.macos + the Linux overlay
        patches = {p.name for p in (ROOT / 'runtime/patches').glob('*.patch')}
        self.assertLessEqual(series, patches)
        self.assertLessEqual(linux, patches)
        self.assertEqual(linux - series, {'astral-linux.patch'})
        windows = set(acr.read_series(ROOT / 'runtime/patches/series.windows'))  # series.linux + Windows overlays
        self.assertEqual(windows - linux, {'windows-native.patch', 'astral-windows.patch'})
        self.assertTrue(all(p.startswith(('ios-', 'windows-')) for p in patches - windows), patches - windows)

    def test_read_series_rejects_bad_lists(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 's'
            for text in ('a.patch\na.patch\n', '../x.patch\n', '# only comments\n', 'x.diff\n'):
                p.write_text(text)
                with self.assertRaises(acr.BuildError):
                    acr.read_series(p)
            p.write_text('# c\n a.patch  # trailing\n\nb-1.patch\n')
            self.assertEqual(acr.read_series(p), ['a.patch', 'b-1.patch'])


class BfttfTest(unittest.TestCase):
    def test_round_trip_both_keys_and_odd_sizes(self):
        for size in (5, 64, 1001):
            ttf = fake_ttf(size, size)
            for key in (acr.BFTTF_KEY, 0xA6018502):
                blob = acr.encode_bfttf(ttf, key)
                self.assertEqual(len(blob), 8 + size + (-size % 4))
                if key == acr.BFTTF_KEY:
                    self.assertEqual(acr.decode_bfttf(blob), ttf)

    def test_layout_matches_the_runtime_fixture_rule(self):
        # tests/test_astral_shared_font.py: word0 = swap(swap(MAGIC) ^ key), word1 = swap(size ^ key), data words
        # little-endian XOR swap(key).
        ttf = fake_ttf(1, 8)
        blob = acr.encode_bfttf(ttf)
        w0, w1, d0, d1 = struct.unpack('<4I', blob)
        sw = acr.bswap
        self.assertEqual(w0, sw(sw(0x18029A7F) ^ 0x49621806))
        self.assertEqual(w1, sw(8 ^ 0x49621806))
        self.assertEqual(d0 ^ sw(0x49621806), struct.unpack_from('<I', ttf, 0)[0])
        self.assertEqual(d1 ^ sw(0x49621806), struct.unpack_from('<I', ttf, 4)[0])

    def test_rejects_non_fonts(self):
        with self.assertRaises(acr.BuildError):
            acr.encode_bfttf(b'PK\3\4' + b'\0' * 8)
        with self.assertRaises(acr.BuildError):
            acr.decode_bfttf(b'\0' * 32)
        blob = bytearray(acr.encode_bfttf(fake_ttf(2)))
        blob[4:8] = b'\xff\xff\xff\x7f'
        with self.assertRaises(acr.BuildError):
            acr.decode_bfttf(bytes(blob))


class FormatProfileTest(unittest.TestCase):
    def profile(self, image, offset=16, count=4, stride=8, fingerprint=None):
        table = image[offset:offset + count * stride]
        fp = acr.fnv1a64(table) if fingerprint is None else fingerprint
        return f'NX_FORMAT_PROFILE_V1 {offset:x} {count:x} {stride:x} 0 1 2 3 1 {fp:x}\n'

    def test_fnv_matches_the_runtime_constant(self):
        self.assertEqual(acr.fnv1a64(b''), 14695981039346656037)
        self.assertEqual(acr.fnv1a64(b'a'), 0xaf63dc4c8601ec8c)

    def test_profile_checked_against_the_sdk_image(self):
        image = bytes(range(256)) * 2
        p = acr.parse_format_profile(self.profile(image))
        acr.check_format_profile(p, image)
        with self.assertRaises(acr.BuildError) as e:
            acr.check_format_profile(p, image[:16] + b'\xff' + image[17:])
        self.assertIn('fingerprint mismatch', str(e.exception))
        with self.assertRaises(acr.BuildError):
            acr.check_format_profile(acr.parse_format_profile(self.profile(image, offset=500)), image)

    def test_built_in_profiles_parse(self):
        for name, text in acr.KNOWN_FORMAT_PROFILES:
            p = acr.parse_format_profile(text)
            self.assertTrue(p['fingerprint'], name)

    def test_malformed_profiles(self):
        for text in ('', 'NX_FORMAT_PROFILE_V2 0 1 8 0 1 2 3 1 0', 'NX_FORMAT_PROFILE_V1 0 1 8 0 1 2 3 1',
                     'NX_FORMAT_PROFILE_V1 0 0 8 0 1 2 3 1 0', 'NX_FORMAT_PROFILE_V1 0 1 8 0 1 2 9 1 0',
                     'NX_FORMAT_PROFILE_V1 0 1 8 0 1 2 3 1 zz'):
            with self.assertRaises(acr.BuildError):
                acr.parse_format_profile(text)


class CliTest(Base):
    def run_main(self, *argv, root=ROOT):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = acr.main(list(argv), root=root, stream=out)
        return rc, out.getvalue(), err.getvalue()

    def test_dry_run_changes_nothing_and_shows_the_whole_plan(self):
        out = self.tmp / 'dry'
        rc, text, err = self.run_main('--dry-run', '--nsp', str(self.nsp), '--keys', str(self.keys),
                                      '--out', str(out), '--moltenvk', str(self.keys))
        self.assertEqual(rc, 0, err)
        self.assertFalse(out.exists())
        for i, (name, _) in enumerate(acr.STAGES, 1):
            self.assertIn(f'[{i}/{len(acr.STAGES)}] {name}:', text)
        applied = [line.rsplit('/', 1)[1] for line in text.splitlines()
                   if 'would run: git -C' in line and line.endswith('.patch') and '/runtime/source apply' in line]
        self.assertEqual(applied, acr.read_series(ROOT / 'runtime/patches/series.macos'))
        self.assertIn('--name main --base 0x4000000000', text)
        self.assertIn('--name sdk --base 0x4010000000', text)
        self.assertIn('-DNX_GAME=astral', text)
        self.assertIn('-DNX_HWOPUS=ON', text)
        self.assertIn('--astral-headerless-compute', text)
        self.assertIn('--control-metadata <keys> <nsp>', text)
        self.assertNotIn(str(self.keys) + ' ', text.split('[6/')[1].split('[7/')[0])  # keys not echoed

    def test_missing_inputs_are_reported(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            acr.parse(['--out', str(self.tmp / 'x')])
        self.assertIn('--nsp', err.getvalue())
        # Later stages alone, or a rerun after the import, do not need the dump.
        acr.parse(['--out', str(self.tmp / 'x'), '--only', 'app'])
        out = self.tmp / 'y'
        out.mkdir()
        (out / 'acr-state.json').write_text(json.dumps({'stages': {'import': {}, 'control': {}}}))
        acr.parse(['--out', str(out), '--from-stage', 'fonts'])
        acr.parse(['--out', str(out)])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            acr.parse(['--out', str(out), '--from-stage', 'control'])

    def test_list_stages(self):
        rc, text, _ = self.run_main('--list-stages')
        self.assertEqual(rc, 0)
        self.assertEqual([line.split()[0] for line in text.splitlines()], list(acr.STAGE_NAMES))

    def test_preflight_lists_every_problem_with_a_hint(self):
        ctx = self.ctx('--moltenvk', str(self.tmp / 'nope.dylib'))
        with mock.patch.object(acr.Context, 'tool', return_value=None), \
                mock.patch.object(acr.Context, 'moltenvk', return_value=None), \
                mock.patch.object(acr.Context, 'dotnet', return_value=None), \
                mock.patch.object(acr.Context, 'brew_prefix', return_value=self.tmp / 'noprefix'):
            with self.assertRaises(acr.BuildError) as e:
                acr.stage_preflight(ctx)
        msg = str(e.exception)
        for needle in ('xcode-select --install', 'pkg-config', 'SDL3', 'MoltenVK', '.NET 10 SDK',
                       'dotnet-sdk', 'spirv-val', 'brew install'):
            self.assertIn(needle, msg)

    def test_preflight_rejects_non_nsp(self):
        xci = self.tmp / 'in/game.xci'
        xci.write_bytes(b'\0' * (2 << 20))
        ctx = acr.Context(acr.parse(['--nsp', str(xci), '--keys', str(self.keys), '--out', str(self.tmp / 'o'),
                                     '--skip-shaders']), out=io.StringIO())
        with self.assertRaises(acr.BuildError) as e:
            acr.stage_preflight(ctx)
        self.assertIn('only NSP', str(e.exception))


class ResumeTest(Base):
    def test_finished_stages_are_skipped_and_from_stage_forces(self):
        calls = []
        funcs = {n: (lambda n: lambda ctx: calls.append(n) or {'k': n})(n) for n in acr.STAGE_NAMES}
        with mock.patch.dict(acr.STAGE_FUNCS, funcs):
            ctx = self.ctx('--to-stage', 'import')
            ctx.out.mkdir()
            acr.run_pipeline(ctx)
            self.assertEqual(calls, ['preflight', 'workspace', 'upstream', 'toolchain', 'import'])
            state = json.loads((ctx.out / 'acr-state.json').read_text())
            self.assertEqual(sorted(state['stages']), sorted(['workspace', 'upstream', 'toolchain', 'import']))
            calls.clear()
            acr.run_pipeline(self.ctx('--to-stage', 'lift'))
            self.assertEqual(calls, ['preflight', 'control', 'lift'])  # preflight always reruns
            calls.clear()
            acr.run_pipeline(self.ctx('--from-stage', 'toolchain', '--to-stage', 'import'))
            self.assertEqual(calls, ['preflight', 'toolchain', 'import'])
            calls.clear()
            acr.run_pipeline(self.ctx('--only', 'fonts', '--only', 'workspace'))
            self.assertEqual(calls, ['workspace', 'fonts'])

    def test_changed_patches_invalidate_later_stages(self):
        calls = []
        funcs = {n: (lambda n: lambda ctx: calls.append(n) or {})(n) for n in acr.STAGE_NAMES}
        root = self.tmp / 'root'
        shutil.copytree(ROOT / 'runtime/patches', root / 'runtime/patches')
        with mock.patch.dict(acr.STAGE_FUNCS, funcs):
            ctx = acr.Context(self.args(), root=root, out=io.StringIO())
            ctx.out.mkdir()
            acr.run_pipeline(ctx)
            calls.clear()
            acr.run_pipeline(acr.Context(self.args(), root=root, out=io.StringIO()))
            self.assertEqual(calls, ['preflight'])
            with (root / 'runtime/patches/astral-vi.patch').open('a') as f:
                f.write('\n')
            ctx = acr.Context(self.args(), root=root, out=io.StringIO())
            acr.run_pipeline(ctx)
            self.assertEqual(calls[1:], ['preflight', 'runtime', 'build', 'fonts', 'data', 'app'])
            self.assertIn('inputs changed', ctx.stream.getvalue())
            calls.clear()
            with mock.patch.object(acr, 'PIN', '0' * 40):
                acr.run_pipeline(acr.Context(self.args(), root=root, out=io.StringIO()))
            self.assertEqual(calls[:3], ['preflight', 'upstream', 'toolchain'])

    def test_foreign_non_empty_out_is_refused(self):
        out = self.tmp / 'mine'
        out.mkdir()
        (out / 'notes.txt').write_text('mine')
        ctx = self.ctx(out=out)
        with self.assertRaises(acr.BuildError) as e:
            acr.run_pipeline(ctx)
        self.assertIn('not an AC-Recomp build directory', str(e.exception))
        self.assertFalse((out / '.gitignore').exists())
        self.assertFalse((out / '.git').exists())

    def test_a_failed_stage_is_not_recorded(self):
        def boom(ctx):
            raise acr.BuildError('nope')
        with mock.patch.dict(acr.STAGE_FUNCS, {n: (lambda c: {}) for n in acr.STAGE_NAMES}):
            with mock.patch.dict(acr.STAGE_FUNCS, {'upstream': boom}):
                ctx = self.ctx()
                ctx.out.mkdir()
                with self.assertRaises(acr.BuildError):
                    acr.run_pipeline(ctx)
            state = json.loads((ctx.out / 'acr-state.json').read_text())
            self.assertEqual(list(state['stages']), ['workspace'])


class HostResourceTest(Base):
    VM_STAT = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
               'Pages free:                                  100000.\n'
               'Pages active:                                900000.\n'
               'Pages inactive:                              200000.\n'
               'Pages speculative:                            10000.\n'
               'Pages wired down:                            300000.\n'
               'Pages purgeable:                              20000.\n')

    def test_default_jobs(self):
        G = acr.GIB
        self.assertEqual(acr.default_jobs(6, 42 * G), 3)      # half the performance cores
        self.assertEqual(acr.default_jobs(12, 64 * G), 6)
        self.assertEqual(acr.default_jobs(24, 256 * G), 8)    # capped at 8
        self.assertEqual(acr.default_jobs(12, 13 * G), 2)     # 6 GiB per compiler
        self.assertEqual(acr.default_jobs(12, 2 * G), 1)      # at least one
        self.assertEqual(acr.default_jobs(1, 64 * G), 1)
        self.assertEqual(acr.default_jobs(10, None), 5)       # unknown memory: cores decide
        self.assertEqual(self.ctx('--jobs', '7').jobs(), 7)   # override
        with mock.patch.object(acr, 'host_cpus', return_value=10), \
                mock.patch.object(acr, 'available_memory', return_value=20 * G):
            self.assertEqual(self.ctx().jobs(), 3)

    def test_host_readings(self):
        self.assertEqual(acr.parse_vm_stat(self.VM_STAT), 16384 * (100000 + 200000 + 10000 + 20000))
        self.assertEqual(acr.parse_meminfo('MemTotal: 100 kB\nMemAvailable:   2048 kB\n'), 2048 * 1024)
        self.assertIsNone(acr.parse_meminfo('MemTotal: 100 kB\n'))
        with mock.patch.object(acr.sys, 'platform', 'darwin'):
            values = {'hw.perflevel0.physicalcpu': None, 'hw.physicalcpu': 8, 'kern.memorystatus_vm_pressure_level': 2}
            with mock.patch.object(acr, '_sysctl', side_effect=values.get):
                self.assertEqual(acr.host_cpus(), 8)
                self.assertEqual(acr.memory_pressure(), 'warning')
            values['hw.perflevel0.physicalcpu'] = 6
            with mock.patch.object(acr, '_sysctl', side_effect=values.get):
                self.assertEqual(acr.host_cpus(), 6)

    def test_back_off_decision(self):
        G = acr.GIB
        self.assertFalse(acr.should_back_off('normal', 20 * G))
        self.assertFalse(acr.should_back_off(None, None))
        self.assertTrue(acr.should_back_off('warning', 20 * G))
        self.assertTrue(acr.should_back_off('critical', None))
        self.assertTrue(acr.should_back_off('normal', 3 * G))
        self.assertTrue(acr.should_back_off(None, 3 * G))

    def test_watchdog_halves_jobs_and_resumes(self):
        marker = self.tmp / 'runs.txt'
        script = ('import sys, time\n'
                  f'open({str(marker)!r}, "a").write(sys.argv[1] + "\\n")\n'
                  'time.sleep(0.6 if sys.argv[1] != "1" else 0.1)\n')

        def make(n):
            return [sys.executable, '-c', script, n]
        readings = iter([('warning', 20 * acr.GIB), ('normal', 2 * acr.GIB)])
        probe = lambda: next(readings, ('normal', 30 * acr.GIB))  # noqa: E731
        ctx = self.ctx()
        log = self.tmp / 'build.log'
        final = acr.watched_build(ctx, make, 4, log, probe=probe, interval=0.1)
        self.assertEqual(final, 1)
        self.assertEqual(marker.read_text().split(), ['4', '2', '1'])
        text = log.read_text()
        self.assertIn('resuming with 2 jobs instead of 4', text)
        self.assertIn('resuming with 1 jobs instead of 2', text)
        self.assertIn('nice -n 10', text)

    def test_watchdog_reports_a_failed_build(self):
        ctx = self.ctx()
        with self.assertRaises(acr.BuildError) as e:
            acr.watched_build(ctx, lambda n: [sys.executable, '-c', 'print("boom"); raise SystemExit(3)'], 2,
                              self.tmp / 'b.log', probe=lambda: ('normal', None), interval=0.1)
        self.assertIn('exit 3', str(e.exception))
        self.assertIn('boom', str(e.exception))


class StageTest(Base):
    def upstream(self, extra=None):
        """A fake pinned upstream with a stand-in recompiler that writes report.txt and code."""
        recomp = ('import pathlib, sys\n'
                  'src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])\n'
                  'out.mkdir(parents=True)\n'
                  'name, base = sys.argv[sys.argv.index("--name") + 1], sys.argv[sys.argv.index("--base") + 1]\n'
                  'from recomp import emit_neon\n'
                  '(out / "code_000.cpp").write_text(f"// {name} {base} {len(src.read_bytes())} {emit_neon.MARK}\\n")\n'
                  '(out / "report.txt").write_text("functions 3, handled 10, unhandled 0\\n")\n')
        files = {'recomp/__init__.py': '', 'recomp/__main__.py': recomp, 'recomp/emit_neon.py': 'MARK = "base"\n',
                 'runtime/src/a.cpp': 'int a;\n', 'CMakeLists.txt': '# fake\n'}
        files.update(extra or {})
        up = self.tmp / 'upstream'
        pin = init_repo(up, files)
        return up, pin

    def fake_root(self, up, patches):
        root = self.tmp / 'root'
        (root / 'runtime/patches').mkdir(parents=True)
        for name, text in patches.items():
            (root / 'runtime/patches' / name).write_text(text)
        return root

    def test_lift_applies_sqshl_to_its_own_checkout_and_records_reports(self):
        up, pin = self.upstream()
        sqshl = make_patch(up, 'recomp/emit_neon.py', 'MARK = "sqshl"\n')
        root = self.fake_root(up, {'astral-sqshl.patch': sqshl})
        ctx = self.ctx('--fps', '30', root=root)
        ctx.upstream = up
        for name in ('main', 'sdk'):
            (ctx.import_dir / 'exefs').mkdir(parents=True, exist_ok=True)
            (ctx.import_dir / 'exefs' / name).write_bytes(b'x' * (3 if name == 'main' else 5))
        ctx.venv_python = lambda: Path(sys.executable)
        with mock.patch.object(acr, 'PIN', pin), mock.patch('prepare_runtime.validate_inputs',
                                                            return_value=({}, 'h')) as vi, \
                mock.patch('prepare_runtime.generated_evidence') as ge:
            evidence = acr.stage_lift(ctx)
        vi.assert_called_once()
        ge.assert_called_once()
        self.assertEqual((ctx.gen / 'main/code_000.cpp').read_text(), '// main 0x4000000000 3 sqshl\n')
        self.assertEqual((ctx.gen / 'sdk/code_000.cpp').read_text(), '// sdk 0x4010000000 5 sqshl\n')
        self.assertEqual(evidence['main']['report'], 'functions 3, handled 10, unhandled 0')
        self.assertEqual(git('-C', up, 'status', '--porcelain'), '')  # pristine upstream untouched

    def test_fps60_lifts_a_verified_patched_main(self):
        from test_astral_fps60 import synthetic_nso
        import astral_fps60
        up, pin = self.upstream()
        sqshl = make_patch(up, 'recomp/emit_neon.py', 'MARK = "sqshl"\n')
        root = self.fake_root(up, {'astral-sqshl.patch': sqshl})
        raw, _ = synthetic_nso()
        for fps, argv, env in (('60', ['--fps', '60'], {}), ('60', [], {'NX_FPS': '60'}), ('30', ['--fps', '30'], {}),
                               ('both', [], {})):
            with mock.patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop('NX_FPS', None)
                ctx = self.ctx(*argv, root=root, out=self.tmp / f'out-{fps}-{len(argv)}-{len(env)}')
                ctx.upstream = up
                (ctx.import_dir / 'exefs').mkdir(parents=True, exist_ok=True)
                (ctx.import_dir / 'exefs/main').write_bytes(raw)
                (ctx.import_dir / 'exefs/sdk').write_bytes(b'x' * 5)
                ctx.venv_python = lambda: Path(sys.executable)
                with mock.patch.object(acr, 'PIN', pin), \
                        mock.patch('prepare_runtime.validate_inputs', return_value=({}, 'h')), \
                        mock.patch('prepare_runtime.generated_evidence'):
                    evidence = acr.stage_lift(ctx)
                    lift_key = acr.stage_inputs(ctx)['lift']
            lifted = (ctx.gen / 'main/code_000.cpp').read_text().split()[3]
            if fps == '60':
                patched = ctx.work / 'lift-fps60/main'
                self.assertEqual(patched.read_bytes(), astral_fps60.patch(raw))
                self.assertEqual(int(lifted), patched.stat().st_size)
                self.assertEqual(evidence['fps'], 60)
                self.assertIn(':fps60:', lift_key)
                self.assertFalse(ctx.gen_variant.exists())
            elif fps == 'both':  # the default: main lifted twice, the second from the verified 60 fps copy
                self.assertEqual(int(lifted), len(raw))
                patched = ctx.work / 'lift-fps60/main'
                self.assertEqual(patched.read_bytes(), astral_fps60.patch(raw))
                second = (ctx.gen_variant / 'main/code_000.cpp').read_text()
                self.assertIn(str(patched.stat().st_size), second)
                self.assertFalse((ctx.gen_variant / 'sdk').exists())
                self.assertEqual(evidence['fps'], '30+60')
                self.assertIn('main_60fps', evidence)
                self.assertIn(':fps30+60:', lift_key)
            else:
                self.assertEqual(int(lifted), len(raw))
                self.assertNotIn('fps', evidence)
                self.assertNotIn('fps60', lift_key)
                self.assertFalse(ctx.gen_variant.exists())
            self.assertEqual((ctx.import_dir / 'exefs/main').read_bytes(), raw)  # the player's main is untouched

    def test_fps60_refuses_another_version(self):
        up, pin = self.upstream()
        sqshl = make_patch(up, 'recomp/emit_neon.py', 'MARK = "sqshl"\n')
        root = self.fake_root(up, {'astral-sqshl.patch': sqshl})
        ctx = self.ctx('--fps', '60', root=root)
        ctx.upstream = up
        (ctx.import_dir / 'exefs').mkdir(parents=True, exist_ok=True)
        (ctx.import_dir / 'exefs/main').write_bytes(b'NSO0' + b'\0' * 0x200)
        ctx.venv_python = lambda: Path(sys.executable)
        with mock.patch.object(acr, 'PIN', pin), self.assertRaisesRegex(acr.BuildError, '--fps 60: build id'):
            acr.stage_lift(ctx)

    def test_default_build_falls_back_to_30_fps_on_another_version(self):
        up, pin = self.upstream()
        sqshl = make_patch(up, 'recomp/emit_neon.py', 'MARK = "sqshl"\n')
        root = self.fake_root(up, {'astral-sqshl.patch': sqshl})
        ctx = self.ctx(root=root)  # no --fps: both asked for
        ctx.upstream = up
        (ctx.import_dir / 'exefs').mkdir(parents=True, exist_ok=True)
        (ctx.import_dir / 'exefs/main').write_bytes(b'NSO0' + b'\0' * 0x200)
        (ctx.import_dir / 'exefs/sdk').write_bytes(b'x' * 5)
        ctx.gen_variant.joinpath('main').mkdir(parents=True)  # a stale second lift from an earlier build
        ctx.venv_python = lambda: Path(sys.executable)
        with mock.patch.object(acr, 'PIN', pin), mock.patch('prepare_runtime.validate_inputs', return_value=({}, 'h')), \
                mock.patch('prepare_runtime.generated_evidence'):
            evidence = acr.stage_lift(ctx)
        self.assertEqual(evidence['fps'], 30)
        self.assertIn('build id', evidence['fps60_unavailable'])
        self.assertIn('NOTE: no 60 fps binary', ctx.stream.getvalue())
        self.assertIn('pass --fps 30', ctx.stream.getvalue())
        self.assertTrue((ctx.gen / 'main/code_000.cpp').is_file())
        self.assertFalse(ctx.gen_variant.exists())
        self.assertFalse(acr.variant_built(ctx))
        self.assertEqual(acr.single_fps(ctx), '30')
        ctx.gen_variant.joinpath('main').mkdir(parents=True)
        self.assertTrue(acr.variant_built(ctx))
        self.assertEqual(acr.single_fps(ctx), '')
        self.assertEqual(acr.single_fps(self.ctx('--fps', '60')), '60')

    def test_runtime_applies_the_series_in_order_and_writes_the_control_header(self):
        up, pin = self.upstream()
        p1 = make_patch(up, 'runtime/src/a.cpp', 'int a;\nint one;\n')
        # two.patch only applies on top of one.patch, so the order matters.
        scratch = self.tmp / 'scratch'
        git('clone', '-q', up, scratch)
        git('-C', scratch, 'config', 'user.email', 'test@example.com')
        git('-C', scratch, 'config', 'user.name', 'Test')
        (scratch / 'runtime/src/a.cpp').write_text('int a;\nint one;\n')
        git('-C', scratch, 'commit', '-qam', 'one')
        p2 = make_patch(scratch, 'runtime/src/a.cpp', 'int a;\nint one;\nint two;\n')
        root = self.fake_root(up, {'one.patch': p1, 'two.patch': p2, 'series.macos': '# x\none.patch\ntwo.patch\n'})
        ctx = self.ctx(root=root)
        ctx.upstream = up
        binding = {'application_id': acr.TITLE, 'program_id': acr.TITLE, 'parental_flags': 0,
                   'ratings': [-1] * 32}
        ctx.control.mkdir(parents=True)
        (ctx.control / 'receipt.json').write_text(json.dumps({'binding': binding}))
        with mock.patch.object(acr, 'PIN', pin):
            evidence = acr.stage_runtime(ctx)
        self.assertEqual((ctx.runtime_src / 'runtime/src/a.cpp').read_text(), 'int a;\nint one;\nint two;\n')
        header = (ctx.runtime_src / 'runtime/src/astral_control_context.h').read_text()
        self.assertIn('#define NX_CONTROL_CONTEXT {0x01007300020fa000ull', header)
        self.assertEqual(list(evidence['patches']), ['one.patch', 'two.patch'])

    def test_runtime_names_the_patch_that_fails(self):
        up, pin = self.upstream()
        bad = make_patch(up, 'runtime/src/a.cpp', 'int b;\n').replace('-int a;', '-int zzz;')
        root = self.fake_root(up, {'bad.patch': bad, 'series.macos': 'bad.patch\n'})
        ctx = self.ctx(root=root)
        ctx.upstream = up
        with mock.patch.object(acr, 'PIN', pin), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(acr.BuildError) as e:
                acr.stage_runtime(ctx)
        self.assertIn('bad.patch', str(e.exception))

    def test_import_failure_is_explained(self):
        root = self.tmp / 'root'
        (root / 'tools').mkdir(parents=True)
        (root / 'tools/import_owned_dump.py').write_text(
            'import json, sys\nprint(json.dumps({"state": "blocked", "error": "importer_failed_resume_same_command"}))\n'
            'sys.exit(1)\n')
        ctx = self.ctx(root=root)
        ctx.logs.mkdir(parents=True)
        with self.assertRaises(acr.BuildError) as e:
            acr.stage_import(ctx)
        self.assertIn('prod.keys', str(e.exception))
        self.assertIn('importer_failed_resume_same_command', str(e.exception))

    def test_workspace_ignores_everything(self):
        ctx = self.ctx()
        acr.stage_workspace(ctx)
        probe = ctx.import_dir / 'x'
        self.assertEqual(subprocess.run(['git', '-C', str(ctx.out), 'check-ignore', '--no-index', '-q',
                                         str(probe.relative_to(ctx.out))]).returncode, 0)

    def test_fonts_from_the_player(self):
        fonts = self.tmp / 'fonts'
        fonts.mkdir()
        ttfs = {stem: fake_ttf(i, 40 + i) for i, stem in enumerate(acr.FONT_FILES)}
        for i, (stem, ttf) in enumerate(ttfs.items()):
            if i % 2:
                (fonts / (stem + '.ttf')).write_bytes(ttf)
            else:
                (fonts / (stem + '.bfttf')).write_bytes(acr.encode_bfttf(ttf))
        ctx = self.ctx('--fonts', str(fonts))
        self.assertEqual(acr.stage_fonts(ctx)['source'], 'player')
        for stem, ttf in ttfs.items():
            self.assertEqual(acr.decode_bfttf((ctx.data / 'shared-fonts' / (stem + '.bfttf')).read_bytes()), ttf)
        # Player fonts replace an earlier replacement-font install, notes included.
        replaced = self.tmp / 'Free.ttf'
        replaced.write_bytes(fake_ttf(9, 100))
        acr.stage_fonts(self.ctx('--replacement-font', str(replaced)))
        self.assertTrue((ctx.data / 'shared-fonts/REPLACEMENT.txt').is_file())
        acr.stage_fonts(self.ctx('--fonts', str(fonts)))
        self.assertFalse((ctx.data / 'shared-fonts/REPLACEMENT.txt').exists())
        self.assertEqual(acr.decode_bfttf((ctx.data / 'shared-fonts' / (acr.FONT_FILES[0] + '.bfttf')).read_bytes()),
                         ttfs[acr.FONT_FILES[0]])
        acr.font_slot_source(fonts, acr.FONT_FILES[4]).unlink()
        with self.assertRaises(acr.BuildError) as e:
            acr.stage_fonts(self.ctx('--fonts', str(fonts)))
        self.assertIn('nintendo_udsg-r_ko_003.bfttf', str(e.exception))

    def test_replacement_fonts_fill_every_slot(self):
        font = self.tmp / 'Free.ttf'
        font.write_bytes(fake_ttf(9, 100))
        ctx = self.ctx('--replacement-font', str(font))
        self.assertEqual(acr.stage_fonts(ctx)['source'], 'replacement')
        for stem in acr.FONT_FILES:
            self.assertEqual(acr.decode_bfttf((ctx.data / 'shared-fonts' / (stem + '.bfttf')).read_bytes()),
                             font.read_bytes())
        self.assertIn('not Nintendo fonts', (ctx.data / 'shared-fonts/REPLACEMENT.txt').read_text())

    def test_replacement_download_is_checksummed(self):
        ctx = self.ctx()
        ctx.work.mkdir(parents=True)

        def fake_run(argv, **kw):
            Path(argv[argv.index('-o') + 1]).write_bytes(b'tampered')
            return ''
        with mock.patch.object(ctx, 'run', side_effect=fake_run):
            with self.assertRaises(acr.BuildError) as e:
                acr.stage_fonts(ctx)
        self.assertIn('checksum mismatch', str(e.exception))

    def test_assemble_prefers_the_listed_variant_and_merges_results(self):
        header = 'hash\tgroup\tstage\tstages_using\tstatus\tms\tspv_bytes\tresources\ttranslator_messages\terror\tq\n'
        key, other, bad = sorted(acr.PREFERRED_VARIANT)[0], '0123456789abcdef', 'fedcba9876543210'
        out, var = self.tmp / 'out', self.tmp / 'var'
        out.mkdir()
        var.mkdir()
        (out / 'results.tsv').write_text(header + f'{key}\t.\tcompute\t1\tok\t1\t4\t\t\t\t\n'
                                         f'{other}\t.\tvertex\t1\tok\t1\t4\t\t\t\t\n'
                                         f'{bad}\t.\tfragment\t1\tinvalid\t1\t0\t\t\tboom\t\n')
        (out / f'{key}.spv').write_bytes(b'BATC')
        (out / f'{other}.spv').write_bytes(b'OTHR')
        (var / 'results.tsv').write_text(header + f'{key}\t.\tcompute\t1\tok-retry\t1\t4\t\t\t\t\n')
        (var / f'{key}.spv').write_bytes(b'VARI')
        ctx = self.ctx()
        final = ctx.out / 'spirv'
        ev = acr.assemble_spirv(ctx, [out, var], final)
        self.assertEqual((final / f'{key}.spv').read_bytes(), b'VARI')
        self.assertEqual((final / f'{other}.spv').read_bytes(), b'OTHR')
        self.assertFalse((final / f'{bad}.spv').exists())
        rows = (final / 'results.tsv').read_text().splitlines()
        self.assertEqual(rows[0], header.rstrip('\n'))
        self.assertIn(f'{key}\t.\tcompute\t1\tok-retry', '\n'.join(rows))
        self.assertEqual(ev['products'], 2)
        self.assertEqual(ev['statuses'], {'ok': 1, 'ok-retry': 1, 'invalid': 1})

    def test_data_root_and_app_bundle(self):
        image = bytes(range(256))
        profile = self.tmp / 'astral.profile'
        profile.write_text(f'NX_FORMAT_PROFILE_V1 10 4 8 0 1 2 3 1 {acr.fnv1a64(image[16:48]):x}\n')
        ctx = self.ctx('--moltenvk', str(self.tmp / 'libMoltenVK.dylib'), '--nvn-format-profile', str(profile))
        (self.tmp / 'libMoltenVK.dylib').write_bytes(b'mvk')
        (ctx.import_dir / 'analysis').mkdir(parents=True)
        (ctx.import_dir / 'analysis/sdk.bin').write_bytes(image)
        for rel in ('analysis/main.npdm', 'exefs/main', 'extract/romfs/x', '.wrapper/manifest.json', '.import/i'):
            (ctx.import_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (ctx.import_dir / rel).write_bytes(b'x')
        (ctx.shaders / 'spirv').mkdir(parents=True)
        (ctx.shaders / 'spirv/results.tsv').write_text('hash\n')
        (ctx.data / 'shared-fonts').mkdir(parents=True)
        (ctx.data / 'user/save').mkdir(parents=True)
        (ctx.data / 'user/save.bin').write_bytes(b'keep me')
        (ctx.data / 'user/save/SlotData_0.dat').write_bytes(b'slot')  # where the game's saves are
        (ctx.data / 'settings.ini').write_text('perf_hud = 1\n')  # the launcher's files beside them
        (ctx.data / 'controls.ini').write_text('[gamepad]\n')
        acr.stage_data(ctx)
        acr.stage_data(ctx)  # idempotent; rebuilding into the same --out keeps saves and settings
        self.assertEqual((ctx.data / 'user/save/SlotData_0.dat').read_bytes(), b'slot')
        self.assertEqual((ctx.data / 'settings.ini').read_text(), 'perf_hud = 1\n')
        self.assertEqual((ctx.data / 'controls.ini').read_text(), '[gamepad]\n')
        for doomed in (ctx.data / 'user', ctx.data / 'user/save', ctx.data, ctx.data / 'user/save/SlotData_0.dat'):
            with self.assertRaisesRegex(acr.BuildError, 'refusing to delete saves'):
                ctx.rmtree(doomed)
        self.assertEqual((ctx.data / 'user/save/SlotData_0.dat').read_bytes(), b'slot')
        self.assertTrue((ctx.data / 'extract/romfs/x').is_file())
        self.assertFalse(os.path.isabs(os.readlink(ctx.data / 'extract')))
        self.assertTrue((ctx.data / 'spirv/results.tsv').is_file())
        self.assertEqual((ctx.data / 'astral.profile').read_text(), profile.read_text())
        self.assertEqual((ctx.data / 'user/save.bin').read_bytes(), b'keep me')
        ctx.build_dir.mkdir(parents=True)
        for name in ('astral', 'astral-60fps'):  # both frame rates (the default build)
            (ctx.build_dir / name).write_text(f'#!/bin/sh\necho "{name} $*"\n')
        (ctx.gen_variant / 'main').mkdir(parents=True)  # the lift made the 60 fps main
        with mock.patch.object(acr.shutil, 'which', return_value=None):  # no codesign in the test
            acr.stage_app(ctx)
        contents = ctx.app / 'Contents'
        self.assertNotIn('NX_NATIVE_RES', (contents / 'MacOS/AC-Recomp').read_text())  # no --render-res
        self.check_fps_wrapper(contents, ctx.data, both=True)
        info = plistlib.loads((contents / 'Info.plist').read_bytes())
        self.assertEqual(info['CFBundleExecutable'], 'AC-Recomp')
        launch = contents / 'MacOS/AC-Recomp'
        self.assertTrue(os.access(launch, os.X_OK))
        self.assertIn('default_root=' + shlex.quote(str(ctx.data)) + '\n', launch.read_text())
        self.assertIn('NX_DATA_ROOT="${NX_DATA_ROOT:-$default_root}"', launch.read_text())
        self.assertIn('NX_NVN_FORMAT_PROFILE="$NX_DATA_ROOT/astral.profile"', launch.read_text())
        self.assertEqual((contents / 'Frameworks/libMoltenVK.dylib').read_bytes(), b'mvk')
        for name in ('Baloo2-Bold.ttf', 'title-bg.jpg', 'OFL.txt'):
            self.assertTrue((contents / 'Resources/assets/launcher' / name).is_file())
        self.assertTrue(os.access(ctx.out / 'run-ac-recomp.sh', os.X_OK))

    def check_fps_wrapper(self, contents, data, both):
        """The .app wrapper runs astral-60fps for NX_FPS=60, else for settings.ini fps = 60, when the build has it."""
        for name in ('astral', 'astral-60fps'):
            if (contents / 'MacOS' / name).exists():
                (contents / 'MacOS' / name).chmod(0o755)
        clean = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}
        settings = data / 'settings.ini'

        def run(text, env=None):
            if text is None:
                settings.unlink(missing_ok=True)
            else:
                settings.write_text(text)
            return subprocess.run([str(contents / 'MacOS/AC-Recomp'), 'arg'], capture_output=True, text=True,
                                  timeout=30, env={**clean, **(env or {})}, check=True).stdout
        sixty = 'astral-60fps arg\n' if both else 'astral arg\n'
        self.assertEqual(run(None), 'astral arg\n')
        self.assertEqual(run('[settings]\nfps = 30\n'), 'astral arg\n')
        self.assertEqual(run('[settings]\nperf_hud = 1\n  fps = 60\n'), sixty)
        self.assertEqual(run('fps = 60\n', {'NX_FPS': '30'}), 'astral arg\n')  # the environment wins
        self.assertEqual(run(None, {'NX_FPS': '60'}), sixty)
        settings.unlink(missing_ok=True)

    def test_app_icon_from_the_launcher_png(self):
        ctx = self.ctx('--fps', '30', '--moltenvk', str(self.tmp / 'libMoltenVK.dylib'))
        (self.tmp / 'libMoltenVK.dylib').write_bytes(b'mvk')
        ctx.build_dir.mkdir(parents=True)
        (ctx.build_dir / 'astral').write_text('#!/bin/sh\n')
        calls = []

        def fake_run(argv, **kw):
            calls.append([str(a) for a in argv])
            if Path(argv[0]).name == 'sips':
                Path(argv[-1]).write_bytes(b'png')
            elif Path(argv[0]).name == 'iconutil':
                self.assertEqual(len(list(Path(argv[3]).glob('*.png'))), 10)
                Path(argv[-1]).write_bytes(b'icns')

        tools = {'sips': '/usr/bin/sips', 'iconutil': '/usr/bin/iconutil'}
        with mock.patch.object(acr.shutil, 'which', side_effect=tools.get), mock.patch.object(ctx, 'run', fake_run):
            acr.stage_app(ctx)
        contents = ctx.app / 'Contents'
        sips = [c for c in calls if c[0].endswith('sips')]
        self.assertEqual(sorted(int(c[2]) for c in sips), [16, 32, 32, 64, 128, 256, 256, 512, 512, 1024])
        self.assertTrue(all(c[4] == str(ROOT / 'assets/launcher/AC-Recomp.png') for c in sips))
        names = {f'icon_{s}x{s}{suffix}.png' for s in acr.ICON_SIZES for suffix in ('', '@2x')}  # the .iconset names
        self.assertEqual({Path(c[-1]).name for c in sips}, names)
        self.assertEqual((contents / 'Resources/AC-Recomp.icns').read_bytes(), b'icns')
        info = plistlib.loads((contents / 'Info.plist').read_bytes())
        self.assertEqual((info['CFBundleIconFile'], info['CFBundleName'], info['CFBundleDisplayName'],
                          info['CFBundleShortVersionString']), ('AC-Recomp', 'AC-Recomp', 'AC-Recomp', '0.1.0'))
        self.assertFalse((ctx.work / 'AC-Recomp.iconset').exists())
        # Without the tools: no icon, no CFBundleIconFile, the app is still written.
        with mock.patch.object(acr.shutil, 'which', return_value=None):
            acr.stage_app(ctx)
        self.assertNotIn('CFBundleIconFile', plistlib.loads((contents / 'Info.plist').read_bytes()))
        self.assertFalse((contents / 'Resources/AC-Recomp.icns').exists())

    def test_one_frame_rate_build_ships_one_binary(self):
        ctx = self.ctx('--fps', '60', '--moltenvk', str(self.tmp / 'libMoltenVK.dylib'), '--render-res', '2560x1440')
        (self.tmp / 'libMoltenVK.dylib').write_bytes(b'mvk')
        ctx.build_dir.mkdir(parents=True)
        (ctx.build_dir / 'astral').write_text('#!/bin/sh\necho "astral $*"\n')
        ctx.data.mkdir(parents=True)
        with mock.patch.object(acr.shutil, 'which', return_value=None):
            acr.stage_app(ctx)
        contents = ctx.app / 'Contents'
        self.assertFalse((contents / 'MacOS/astral-60fps').exists())
        self.assertIn('export NX_NATIVE_RES="${NX_NATIVE_RES:-2560x1440}"', (contents / 'MacOS/AC-Recomp').read_text())
        self.check_fps_wrapper(contents, ctx.data, both=False)

    def test_variant_list_names_only_the_changed_main_files(self):
        ctx = self.ctx()
        base, var = ctx.gen / 'main', ctx.gen_variant / 'main'
        base.mkdir(parents=True)
        var.mkdir(parents=True)
        for name, a, b in (('code_000.cpp', 'same', 'same'), ('code_001.cpp', 'x', 'y'), ('table.cpp', 't', 't'),
                           ('report.txt', 'r1', 'r2')):
            (base / name).write_text(a)
            (var / name).write_text(b)
        (base / 'code_002.cpp').write_text('gone')
        (var / 'code_003.cpp').write_text('new')
        got = acr.write_variant_list(ctx)
        self.assertEqual(got, {'compile': ['code_001.cpp', 'code_003.cpp'],
                               'exclude': ['code_001.cpp', 'code_002.cpp', 'code_003.cpp']})
        self.assertEqual(ctx.variant_list.read_text().splitlines(),
                         [f'dir {var}', 'compile code_001.cpp', 'compile code_003.cpp', 'exclude code_001.cpp',
                          'exclude code_002.cpp', 'exclude code_003.cpp'])
        (var / 'shared.h').write_text('a header only the second lift has')  # every .cpp compiles again
        self.assertEqual(acr.write_variant_list(ctx)['compile'], ['code_000.cpp', 'code_001.cpp', 'code_003.cpp',
                                                                  'table.cpp'])

    def data_ctx(self, image, *extra, out=None):
        ctx = self.ctx(*extra, out=out)
        for rel in ('analysis/main.npdm', 'exefs/main', 'extract/romfs/x'):
            (ctx.import_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (ctx.import_dir / rel).write_bytes(b'x')
        (ctx.import_dir / 'analysis/sdk.bin').write_bytes(image)
        (ctx.data / 'shared-fonts').mkdir(parents=True)
        return ctx

    def test_default_profile_is_chosen_by_fingerprint(self):
        image = bytes(range(256))
        good = f'NX_FORMAT_PROFILE_V1\n10 4 8 0 1 2 3 1 {acr.fnv1a64(image[16:48]):x}\n'
        other = f'NX_FORMAT_PROFILE_V1\n10 4 8 0 1 2 3 1 {acr.fnv1a64(b"x"):x}\n'
        with mock.patch.object(acr, 'KNOWN_FORMAT_PROFILES', (('other', other), ('ours', good))):
            ctx = self.data_ctx(image)
            acr.stage_data(ctx)
            self.assertEqual((ctx.data / 'astral.profile').read_text(), good)
            self.assertIn('(ours)', ctx.stream.getvalue())
        with mock.patch.object(acr, 'KNOWN_FORMAT_PROFILES', (('other', other),)):
            with self.assertRaises(acr.BuildError) as e:
                acr.stage_data(self.data_ctx(image, out=self.tmp / 'out2'))
        self.assertIn('not supported', str(e.exception))
        self.assertIn('--nvn-format-profile', str(e.exception))

    def test_rmtree_refuses_paths_outside_out(self):
        ctx = self.ctx()
        with self.assertRaises(acr.BuildError):
            ctx.rmtree(self.tmp / 'in')
        with self.assertRaises(acr.BuildError):
            ctx.rmtree(ctx.out)


if __name__ == '__main__':
    unittest.main()
