#!/usr/bin/env python3
"""One local-only, fail-closed main regeneration with an exact eight-site audit.

No SDK lifting, installation, runtime execution, canonical writes or object reuse.
All receipts and derived bytes belong in this worktree's .local/cpu-regen-020.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import prepare_runtime as prep
import check_sqshl as sq

ROOT = Path(__file__).resolve().parents[1]
PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
ACCEPTED = '942747883cce902b7d06c0c541cb02d9f64f613f'
PATCH_SHA = 'e0e90c230e2a4c50eb2885a7d1298b24020158c67360303e2e36660fd44e4035'
INVENTORY_SHA = '6dda05727aa2e398f522a909331bd2a10ced3544393045eaddc8362f02f7d25e'
SITES_SHA = '8a370c2fac07b37c6d915ee40c439e424c7b3e0da516b014a0cb746903079bb5'
MANIFEST_SHA = 'fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d'
RECEIPT_SHA = 'c3efa47ea8b3940cffdcd8f22c47da5b5c2d690d90ee80c854b3a0b1d5138f2d'
require = prep.require
sha = prep.sha


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def regular(path):
    path = Path(os.path.abspath(path))
    require(all(not p.is_symlink() for p in (path, *path.parents)), 'symlink path refused')
    require(path.is_file() and path.stat().st_nlink == 1, 'missing or linked file')
    return path


def tree(path):
    require(path.is_dir() and not path.is_symlink(), 'missing or linked directory')
    result = {}
    for p in sorted(path.rglob('*')):
        require(not p.is_symlink(), 'symlink tree member')
        if p.is_file():
            regular(p)
            result[str(p.relative_to(path))] = sha(p)
        else:
            require(p.is_dir(), 'special tree member')
    return result


def read_checked(path, expected):
    regular(path)
    require(sha(path) == expected, 'provenance hash mismatch: ' + str(path))
    return json.loads(path.read_text())


class Runner:
    """Bound every process group, retain commands/exits, kill and reap on timeout."""
    def __init__(self, out, seconds):
        self.out, self.deadline, self.records = out, time.monotonic() + seconds, []

    def run(self, argv, cwd=None):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'timebox exhausted')
        rec = {'argv': list(map(str, argv)), 'cwd': str(cwd) if cwd else None,
               'start_utc': utc(), 'timeout_seconds': remaining}
        self.records.append(rec)
        log = self.out / ('command-%02d.log' % len(self.records))
        rec['log'] = log.name
        try:
            with log.open('w') as f:
                p = subprocess.Popen(rec['argv'], cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                                     start_new_session=True,
                                     env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                          'PYTHONHASHSEED': '0'})
                rec['pid'] = p.pid
                try:
                    rec['exit_code'] = p.wait(timeout=remaining)
                except BaseException:
                    os.killpg(p.pid, signal.SIGTERM)
                    try:
                        p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait()
                    rec.update(exit_code=p.returncode, terminated=True)
                    raise
                finally:
                    # No detached descendant from an owned command may survive.
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    rec['reaped'] = p.poll() is not None
        finally:
            rec['end_utc'] = utc()
            rec['log_sha256'] = sha(log)
            (self.out / 'commands.json').write_text(json.dumps(self.records, indent=2) + '\n')
        require(rec['exit_code'] == 0, 'child failed; see ' + str(log))
        return log.read_text()


def audit(baseline, fresh, sites):
    """Require byte equality against baseline plus exactly accepted replacements."""
    require(len(sites) == 8 and len({(s['file'], s['offset']) for s in sites}) == 8, 'wrong site count')
    old, new = tree(baseline), tree(fresh)
    require(old.keys() == new.keys(), 'generated file inventory changed')
    expected = {}
    changes = []
    for site in sites:
        name = 'main/' + site['file']
        require(Path(name).parent == Path('main'), 'unsafe site filename')
        require(hashlib.sha256(site['emission'].encode()).hexdigest() == site['emission_sha256'],
                'site emission hash mismatch')
        text = expected.setdefault(name, (baseline / name).read_text())
        operands, offset = site['operands'], site['offset']
        before = (f'nx::unimpl(c, NXB + {offset:#x}ull, "sqshl {operands}"); '
                  f'// no handler // sqshl {operands}')
        after = site['emission'] + ' // sqshl ' + operands
        require(text.count(before) == 1, 'missing/duplicate baseline site')
        expected[name] = text.replace(before, after, 1)
        changes.append({'file': name, 'offset': offset, 'emission_sha256': site['emission_sha256']})
    report = (baseline / 'main/report.txt').read_text()
    require(report.startswith('functions 27763, handled 2569143, unhandled 8\n'), 'wrong baseline counts')
    require(report.endswith('       8 sqshl\n'), 'wrong baseline unsupported report')
    expected['main/report.txt'] = report.replace('handled 2569143, unhandled 8',
                                               'handled 2569151, unhandled 0', 1).removesuffix('       8 sqshl\n')
    for name in old:
        if name in expected:
            require((fresh / name).read_bytes() == expected[name].encode(),
                    'unexplained generated change: ' + name)
        else:
            require(old[name] == new[name], 'unexplained generated change: ' + name)
    return {'sites': changes, 'semantic_sites': len(changes),
            'baseline_counts': [27763, 2569143, 8], 'new_counts': [27763, 2569151, 0],
            'sdk_counts': [33573, 1302326, 0],
            'files': {k: {'before': old[k], 'after': new[k],
                          'kind': 'site' if k in expected and k != 'main/report.txt' else
                          'report' if k == 'main/report.txt' else 'identical'} for k in old}}


def regenerate(reference, python, nso, baseline, out, patch, sites, runner, pin=PIN):
    """Shared orchestration core, also exercised with a temporary fake emitter."""
    require(prep.git(reference, 'rev-parse', 'HEAD') == pin, 'wrong reference pin')
    require(not prep.git(reference, 'status', '--porcelain', '--untracked-files=all'), 'dirty reference')
    regular(patch)
    source = out / 'source'
    runner.run(['git', 'clone', '--no-hardlinks', '--no-checkout', reference, source])
    runner.run(['git', '-C', source, 'checkout', '--detach', pin])
    before = prep.source_fingerprint(source)
    runner.run(['git', '-C', source, 'apply', '--check', patch])
    runner.run(['git', '-C', source, 'apply', patch])
    after = prep.source_fingerprint(source)
    require(before.keys() == after.keys() and
            [k for k in before if before[k] != after[k]] == ['recomp/emit_neon.py'],
            'patch changed unexpected source')
    combined = out / 'gen'
    combined.mkdir()
    # copy2 creates independent files; never link canonical SDK bytes.
    shutil.copytree(baseline / 'sdk', combined / 'sdk', copy_function=shutil.copy2)
    runner.run([python, '-m', 'recomp', nso, combined / 'main', '--name', 'main',
                '--base', '0x4000000000'], cwd=source)
    result = audit(baseline, combined, sites)
    require(prep.source_fingerprint(source) == after, 'emitter source drift')
    result['source_before'], result['source_after'] = before, after
    return result


def execute(a):
    # Normalize only after checking lexical parents, so symlinks cannot disappear.
    for p in (a.reference, a.inputs, a.baseline, a.receipt, a.inventory, a.sites, a.out):
        require(all(not x.is_symlink() for x in (p, *p.parents)), 'symlink argument refused')
    owned = ROOT / '.local/cpu-regen-020'
    out = prep.private(ROOT, a.out)
    require(out.is_relative_to(owned) and out != owned, 'output outside unit ownership')
    require(not out.exists(), 'existing output refused; no retry')
    for p in (a.inputs, a.baseline, a.reference, a.receipt, a.inventory, a.sites):
        require(not out.is_relative_to(p) and not p.is_relative_to(out), 'output overlap')
    require(prep.git(ROOT, 'merge-base', '--is-ancestor', ACCEPTED, 'HEAD') == '', 'accepted head missing')
    patch = ROOT / 'runtime/patches/astral-sqshl.patch'
    regular(patch)
    require(sha(patch) == PATCH_SHA, 'wrong SQSHL patch')
    inv = read_checked(a.inventory, INVENTORY_SHA)
    actual = read_checked(a.sites, SITES_SHA)
    receipt = read_checked(a.receipt, RECEIPT_SHA)
    require(inv['reference_pin'] == PIN and inv['reference_clean'], 'wrong inventory pin')
    require(inv['receipt_sha256'] == RECEIPT_SHA, 'wrong inventory receipt')
    require(actual['count'] == len(actual['sites']) == len(inv['sites']) == 8, 'wrong site count')
    require(len({(x['file'], x['offset']) for x in actual['sites']}) == 8, 'duplicate sites')
    require([{k: s[k] for k in inv['sites'][0]} for s in actual['sites']] == inv['sites'], 'site inventory mismatch')
    require(prep.git(a.reference, 'rev-parse', 'HEAD') == PIN, 'wrong reference pin')
    require(not prep.git(a.reference, 'status', '--porcelain', '--untracked-files=all'), 'dirty reference')
    for p in prep.git(a.reference, 'ls-files').splitlines():
        regular(a.reference / p)
    regular(a.inputs / '.wrapper/manifest.json')
    manifest, mh = prep.validate_inputs(a.inputs)
    require(mh == MANIFEST_SHA == inv['manifest_sha256'] == receipt['identity']['manifest_sha256'], 'wrong manifest')
    baseline_hashes = tree(a.baseline)
    generated = prep.generated_evidence(a.baseline, manifest)
    require(generated == receipt['identity']['generated'], 'canonical generated drift')
    require(len(baseline_hashes) == inv['generated_files'] == 319, 'wrong generated inventory')
    require(generated['sdk']['report'].startswith('functions 33573, handled 1302326, unhandled 0\n'), 'wrong SDK counts')
    for site in actual['sites']:
        require(not site['scalar'] and not site['immediate'] and site['vas'] == 9, 'unsupported actual form')
        flat = a.inputs / manifest['modules'][0]['flat']['path']
        with flat.open('rb') as f:
            f.seek(site['offset'])
            require(f.read(4).hex() == site['word'], 'site word mismatch')
    out.mkdir(parents=True, mode=0o700)
    runner = Runner(out, a.timeout)
    report = {'schema': 1, 'start_utc': utc(), 'state': 'running', 'pin': PIN,
              'patch_sha256': sha(patch), 'manifest_sha256': mh,
              'inventory_sha256': sha(a.inventory), 'sites_sha256': sha(a.sites),
              'receipt_sha256': sha(a.receipt), 'baseline': baseline_hashes,
              'wrapper_argv': [sys.executable, *sys.argv], 'python_requested': str(a.python),
              'python_executable_sha256': sha(a.python.resolve()),
              'wrapper_sha256': sha(Path(__file__)),
              'inputs': [manifest['npdm']] + [m[k] for m in manifest['modules'] for k in ('nso', 'flat')]}
    try:
        dependency_probe = runner.run([a.python, '-c',
            "import capstone,lz4,zstandard,json; "
            "v=[capstone.__version__,lz4.__version__,zstandard.__version__]; "
            "assert v==['5.0.6','4.4.4','0.24.0']; print(json.dumps(v))"])
        report['dependency_probe'] = json.loads(dependency_probe)
        # regenerate() owns the one clone/application and bounded generation invocation.
        result = regenerate(a.reference, a.python, a.inputs / manifest['modules'][0]['nso']['path'],
                            a.baseline, out, patch, actual['sites'], runner)
        emitted = json.loads(runner.run([a.python, '-c', sq.EMIT_CHILD, out / 'source']))
        require(len(emitted['rejected']) == 32, 'unsupported-form regression')
        require(prep.source_fingerprint(out / 'source') == result['source_after'], 'emitter source drift')
        report.update(result, unsupported_forms=emitted['rejected'], dependencies=emitted['dependencies'])
        require(tree(a.baseline) == baseline_hashes, 'canonical output changed')
        require(prep.validate_inputs(a.inputs)[1] == mh, 'input drift')
        require(not prep.git(a.reference, 'status', '--porcelain', '--untracked-files=all'), 'reference drift')
        report['state'] = 'accepted'
    except BaseException as e:
        report.update(state='blocked', error=type(e).__name__ + ': ' + str(e))
        raise
    finally:
        report['end_utc'] = utc()
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'state': report['state'], 'report': str(out / 'report.json'),
                      'semantic_sites': report['semantic_sites'], 'counts': report['new_counts']}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('reference', 'python', 'inputs', 'baseline', 'receipt', 'inventory', 'sites', 'out'):
        p.add_argument('--' + name, type=lambda x: Path(os.path.abspath(x)), required=True)
    p.add_argument('--timeout', type=int, default=600)
    a = p.parse_args()
    try:
        require(1 <= a.timeout <= 900, 'timeout must be 1..900 seconds')
        execute(a)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as e:
        p.exit(1, 'regeneration blocked: ' + str(e) + '\n')


if __name__ == '__main__':
    main()
