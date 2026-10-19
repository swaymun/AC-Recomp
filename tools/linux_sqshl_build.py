#!/usr/bin/env python3
"""Fail-closed SQSHL compile-only lane. Never invokes a title or regeneration."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tarfile
import time

import prepare_runtime as prep
import regenerate_sqshl as regen
# Only the process/session primitives are reused; execute() is never called.
from linux_runtime_startup import run_stage, save, utc, session_groups

UNIT = 'LINUX-SQSHL-021'
HEAD = '39fc30ab25d83b328e1026a12892db1fc18b305a'
BASE = '942747883cce902b7d06c0c541cb02d9f64f613f'
PATCH = '0bdb67cad8a330deb3368937fa942949bf54e03aa72b113572aa01a4abc35222'
PRODUCER = '7419dea9b2ad455fad02b4d6f044911c'
REVIEW = '7cfaa9ed177144348c6f072f388d0b85'
REPORT_SHA = '4550554fc4715c750e3dd71943e9b4968a2cbcd5539441100a33932219a3b6d5'
HOST = 'acs-recovery-linux'
# Owned RunPod identity comes from configuration (--pod or ACS_RUNPOD_POD_ID), never from source.
POD = os.environ.get('ACS_RUNPOD_POD_ID', '')
REMOTE = Path('/root/acs-units') / UNIT
GPU = Path('/root/acs-units/LINUX-GPU-002')
HELPERS = ('tools/prepare_runtime.py', 'tools/import_owned_dump.py',
           'tools/regenerate_sqshl.py', 'tools/check_sqshl.py',
           'tools/linux_runtime_startup.py', 'dependencies.lock',
           'runtime/patches/apple-memory.patch', 'runtime/patches/astral-bootstrap.patch',
           'runtime/patches/astral-sqshl.patch')
require = prep.require
sha = prep.sha


def read(path):
    regen.regular(path)
    return json.loads(path.read_text())


def identity(repo, base, head):
    diff = subprocess.check_output(['git', '-c', 'core.fsmonitor=false', '-C', str(repo),
        'diff', '--binary', '--full-index', '--no-ext-diff', '--no-renames', '--unified=0', base, head]).decode()
    return hashlib.sha256('\n'.join(x for x in diff.split('\n')
        if not x.startswith(('index ', '@@ '))).encode()).hexdigest()


def acceptance(repo, store):
    """Check durable landing, independent review, producer and Git, before inputs."""
    rows = list(csv.DictReader(io.StringIO((store / 'units.tsv').read_text()), delimiter='\t'))
    unit = next(x for x in rows if x['id'] == 'CPU-REGEN-020')
    require(unit['state'] == 'landed' and unit['head'] == HEAD and
            unit['run_id'] == PRODUCER and unit['patch'] == PATCH, 'producer not exactly landed')
    records = {}
    for label, name in [('producer', PRODUCER + '.json'), ('review', REVIEW + '.review.json'),
                        ('land', PRODUCER + '.land.json')]:
        records[label] = read(store / 'reports' / name)
    p, r, land = (records[k] for k in ('producer', 'review', 'land'))
    require(p['head'] == HEAD and p['patch'] == PATCH and p['run_id'] == PRODUCER and
            p['state'] == 'completed' and p['report']['head'] == HEAD, 'wrong producer report')
    require(r['head'] == HEAD and r['patch'] == PATCH and r['producer_run'] == PRODUCER and
            r['run_id'] == REVIEW and r['model'] == 'gpt-6-astra' and r['effort'] == 'medium' and
            r['verdict'] == r['report']['verdict'] == 'pass' and r['report']['head'] == HEAD and
            r['report']['patch'] == PATCH, 'independent review missing/mismatched')
    require(land['unit'] == 'CPU-REGEN-020' and land['head'] == land['reviewed_head'] == HEAD and
            land['patch'] == PATCH, 'wrong landing identity')
    prep.git(repo, 'merge-base', '--is-ancestor', HEAD, 'main')
    prep.git(repo, 'merge-base', '--is-ancestor', HEAD, 'HEAD')
    require(identity(repo, BASE, HEAD) == PATCH, 'producer Git patch mismatch')
    require(not prep.git(repo, 'status', '--porcelain', '--untracked-files=no'), 'dirty tracked sources')
    for name in HELPERS:
        expected = subprocess.check_output(['git', '-C', str(repo), 'show', HEAD + ':' + name])
        require(hashlib.sha256(expected).hexdigest() == sha(regen.regular(repo / name)),
                'unreviewed helper bytes: ' + name)
    work = Path(unit['worktree'])
    for a in p['artifacts']:
        f = regen.regular(work / a['path'])
        require(f.is_relative_to(work / '.local/cpu-regen-020') and
                sha(f) == a['sha256'] and f.stat().st_size == a['size'], 'producer artifact mismatch')
    records['record_hashes'] = {n: sha(store / 'reports' / n) for n in
        (PRODUCER + '.json', REVIEW + '.review.json', PRODUCER + '.land.json')}
    return work, records


def provenance(repo, store):
    work, accepted = acceptance(repo, store)
    root = work / '.local/cpu-regen-020'
    artifacts = read(root / 'artifact-manifest.json')
    require(artifacts['head'] == HEAD, 'wrong artifact head')
    for name, rec in artifacts['files'].items():
        f = regen.regular(root / name)
        require(f.is_relative_to(root) and sha(f) == rec['sha256'] and
                f.stat().st_size == rec['size'], 'retained artifact mismatch: ' + name)
    report = regen.read_checked(root / 'regeneration/report.json', REPORT_SHA)
    require(report['state'] == 'accepted' and report['pin'] == regen.PIN and
            report['patch_sha256'] == regen.PATCH_SHA, 'wrong regeneration identity')
    argv = read(root / 'commands.json')[0]['argv']
    arg = lambda flag: Path(argv[argv.index(flag) + 1])
    inputs, gen, prepared, reference = [arg('--' + n) for n in ('inputs', 'gen', 'out', 'reference')]
    require(gen == root / 'regeneration/gen' and prepared == root / 'native', 'unexpected producer outputs')
    invroot = store / 'worktrees/CPU-SQSHL-019/.local/cpu-sqshl-019'
    inv = regen.read_checked(invroot / 'inventory.json', regen.INVENTORY_SHA)
    sites = regen.read_checked(invroot / 'actual-site-audit.json', regen.SITES_SHA)['sites']
    regen.read_checked(store / 'worktrees/IPC-CALLER-014/.local/ipc-caller-014/prepared-initial/prepared.json', regen.RECEIPT_SHA)
    old = regen.read_checked(store / 'worktrees/IPC-CALLER-014/.local/ipc-caller-014/prepared/prepared.json',
        '9111d64ab9f991c4742e029fd20dcade8ddc7664d6e023db9f9093a26f6126be')
    # Canonical directory is retained in the exact producer wrapper argv.
    wrapper = report['wrapper_argv']
    baseline = Path(wrapper[wrapper.index('--baseline') + 1])
    manifest, mh = prep.validate_inputs(inputs)
    require(mh == regen.MANIFEST_SHA, 'input manifest drift')
    require(regen.tree(baseline) == report['baseline'], 'canonical generated drift')
    audited = regen.audit(baseline, gen, sites)
    for key, value in audited.items():
        require(report[key] == value, 'generated audit mismatch: ' + key)
    require(len(audited['files']) == 319 and len([k for k in audited['files'] if k.startswith('sdk/')]) == 110,
            'wrong generated manifest count')
    for site in sites:
        with (inputs / manifest['modules'][0]['flat']['path']).open('rb') as f:
            f.seek(site['offset'])
            require(f.read(4).hex() == site['word'], 'input site word drift')
    native = read(prepared / 'prepared.json')
    require(native['source'] == old['source'] and len(native['source']) == 449 and
            prep.source_fingerprint(prepared / 'source') == native['source'], 'prepared source drift')
    require(native['identity']['patches'] == old['identity']['patches'] and
            native['identity']['manifest_sha256'] == mh, 'prepared input/patch drift')
    require(prep.git(reference, 'rev-parse', 'HEAD') == regen.PIN and
            not prep.git(reference, 'status', '--porcelain', '--untracked-files=all'), 'reference pin/dirty')
    return {'accepted': accepted, 'landed_head': HEAD, 'generated': regen.tree(gen),
            'source': native['source'], 'manifest_sha256': mh,
            'helpers': {n: sha(repo / n) for n in HELPERS}, 'sites': 8, 'sdk_files': 110,
            'canonical_unchanged': True}, inputs, gen, manifest


def controls(registry, ready, transfer):
    reg, r, t = map(read, (registry, ready, transfer))
    require(reg['task_id'] == 'acs-recovery-20261018', 'wrong task registry')
    require(bool(POD), 'owned Pod id required (--pod or ACS_RUNPOD_POD_ID)')
    owned = [x for x in reg['resources'] if x['id'] == POD]
    require(len(owned) == 1 and owned[0]['provider'] == 'runpod' and owned[0]['host'] == HOST,
            'owned host mismatch')
    require(r['host'] == HOST and r['pod_id'] == POD and r['ssh_verified'] is True and
            r['account_credentials_present'] is False and r['vm_auth_absent_state_signout_verified'] is True,
            'ssh-ready control missing')
    require(t['host'] == HOST and t['pod'] == POD and t['hash_verified'] is True and
            t['extracted'] is True and t['sha256'] ==
            '79dd84489bb55d71374b126bf8130c0c697059447ca5c17ea1ad6c010d9bd301' and
            t['destination'] == '/root/ACSRecomp/.local/game-private/', 'wrong transfer receipt')
    return {str(p): sha(p) for p in (registry, ready, transfer)}


def host_probe():
    # Only one nonsecret environment field is emitted, never the full environment.
    return "import pathlib; e=pathlib.Path('/proc/1/environ').read_bytes().split(b'\\0'); p=[x.split(b'=',1)[1].decode() for x in e if x.startswith(b'RUNPOD_POD_ID=')]; assert p==[%r], 'owned Pod mismatch'; print(p[0])" % POD


def ssh(argv):
    return ['ssh', '-oBatchMode=yes', '-oConnectTimeout=10', HOST,
            shlex.join(list(map(str, argv)))]


def remaining(end):
    return max(0, end - time.monotonic())


def stage(out, name, argv, end, **kw):
    rec = run_stage(argv, out / (name + '.log'), remaining(end), **kw)
    require(rec['ok'], name + ' failed; retained receipt')
    return rec


def safe_unpack(archive, target, hashes):
    require(not target.exists(), 'existing extraction refused')
    with tarfile.open(archive, 'r:gz') as t:
        members = t.getmembers()
        require(len(members) == len(hashes) and {m.name for m in members} == set(hashes), 'archive inventory mismatch')
        for m in members:
            require(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts,
                    'unsafe archive member')
            data = t.extractfile(m).read()
            require(hashlib.sha256(data).hexdigest() == hashes[m.name], 'transfer member hash mismatch')
        target.mkdir(mode=0o700)
        for m in members:
            f = target / m.name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(t.extractfile(m).read())


def compile_objects(commands, build, expect=395):
    require(len(commands) == expect, 'wrong compile command count')
    objects = []
    for c in commands:
        args = c.get('arguments') or shlex.split(c['command'])
        require('-DNX_ASTRAL_STRICT=1' in args and '-ffp-contract=off' in args and
                '-march=x86-64-v3' in args, 'strict/platform compile flags missing')
        require('-o' in args, 'object output missing')
        p = Path(args[args.index('-o') + 1])
        p = p if p.is_absolute() else Path(c['directory']) / p
        require(p.resolve().is_relative_to(build), 'object outside owned build')
        objects.append(p)
    require(len(set(objects)) == expect, 'duplicate compile objects')
    return objects


def dependencies(ninja_text, build):
    names = set()
    for line in ninja_text.splitlines():
        if line.startswith('    '):
            p = Path(line.strip())
            names.add(p if p.is_absolute() else build / p)
    require(names, 'missing dependency inventory')
    return {str(p.resolve()): sha(p.resolve()) for p in sorted(names)}


def native(plan, out, end):
    repo = out / 'repo'
    spec = read(plan)
    require(spec['landed_head'] == HEAD and spec['sites'] == 8 and spec['sdk_files'] == 110,
            'wrong remote provenance')
    for n, h in spec['helpers'].items():
        require(sha(regen.regular(repo / n)) == h, 'remote helper drift')
    inputs, gen = repo / '.local/inputs', repo / '.local/gen'
    require(regen.tree(gen) == spec['generated'], 'remote generated drift')
    require(prep.validate_inputs(inputs)[1] == spec['manifest_sha256'], 'remote input drift')
    reference = GPU / 'repo/.local/references/wonder'
    prefix = GPU / 'repo/.local/sdl3'
    vulkan = GPU / 'repo/.local/references/Vulkan-Headers'
    sdl = GPU / 'repo/.local/references/SDL'
    pins = [(reference, regen.PIN), (vulkan, 'e3b1eec08173d6b825cd3ac88c885a63b621504a'),
            (sdl, 'a8589a84226a6202831a3d49ff4edda4acab9acd')]
    for path, pin in pins:
        require(prep.git(path, 'rev-parse', 'HEAD') == pin and
                not prep.git(path, 'status', '--porcelain', '--untracked-files=all'), 'dependency pin/dirty')
    installed = {str(p): sha(p.resolve()) for p in sorted(prefix.rglob('*')) if p.is_file()}
    require(installed, 'SDL prefix missing')
    cmake, ninja = GPU / 'venv/bin/cmake', Path('/usr/bin/ninja')
    receipt = {'schema': 1, 'unit': UNIT, 'started_utc': utc(), 'landed_head': HEAD,
               'title_launched': False, 'gameplay': 'unknown', 'cross_isa_byte_match': 'N/A',
               'stages': {}, 'wrapper_sha256': sha(Path(__file__)), 'helpers': spec['helpers']}
    save(out / 'receipt.json', receipt)
    prepared = repo / '.local/prepared'
    require(not prepared.exists(), 'existing prepared output')
    env = dict(os.environ, CC='clang', CXX='clang++', PYTHONDONTWRITEBYTECODE='1')
    try:
        for name, argv in [('git-init', ['git', 'init', repo]),
            ('configure', [sys.executable, repo / 'tools/prepare_runtime.py', '--repo', repo,
             '--reference', reference, '--inputs', inputs, '--gen', gen, '--out', prepared,
             '--configure', '--jobs', '3', '--cmake', cmake, '--ninja', ninja,
             '--prefix', prefix, '--vulkan-include', vulkan / 'include'])]:
            receipt['stages'][name] = stage(out, name, argv, end, env=env)
        prov = read(prepared / 'prepared.json')
        require(prov['source'] == spec['source'], '449 prepared source mismatch')
        commands = read(prepared / 'build/compile_commands.json')
        objects = compile_objects(commands, prepared / 'build')
        require(not any(x.exists() for x in objects), 'object reuse refused')
        require(any(str(gen / 'main') in c['file'] for c in commands) and
                any(str(gen / 'sdk') in c['file'] for c in commands), 'generated target missing')
        before_commands = sha(prepared / 'build/compile_commands.json')
        save(out / 'compiler-commands.json', commands)
        receipt['toolchain'] = {}
        for name, exe in [('clang', Path('/usr/bin/clang++')), ('cmake', cmake), ('ninja', ninja)]:
            receipt['stages'][name] = stage(out, name, [exe, '--version'], end)
            receipt['toolchain'][name] = {'path': str(exe.resolve()), 'sha256': sha(exe.resolve())}
        receipt['stages']['build'] = stage(out, 'build', [cmake, '--build', prepared / 'build',
                                              '--parallel', '3', '--target', 'astral'], end, env=env)
        receipt['objects'] = {str(x.relative_to(prepared / 'build')): sha(regen.regular(x)) for x in objects}
        receipt['object_count'] = len(receipt['objects'])
        receipt['stages']['deps'] = stage(out, 'deps', [ninja, '-C', prepared / 'build', '-t', 'deps'], end)
        deps = dependencies((out / 'deps.log').read_text(), prepared / 'build')
        receipt['stages']['link-commands'] = stage(out, 'link-commands',
                        [ninja, '-C', prepared / 'build', '-t', 'commands', 'astral'], end)
        # Hash every absolute linked library named by Ninja (including installed SDL).
        linked = {}
        for line in (out / 'link-commands.log').read_text().splitlines():
            for token in shlex.split(line):
                if token.startswith('/') and Path(token).is_file():
                    linked[token] = sha(Path(token).resolve())
        receipt['dependencies'] = deps
        receipt['linked_files'] = linked
        receipt['executable'] = {'bytes': (prepared / 'build/astral').stat().st_size,
                                'sha256': sha(regen.regular(prepared / 'build/astral'))}
        require(before_commands == sha(prepared / 'build/compile_commands.json'), 'compile commands drift')
        require(prep.source_fingerprint(prepared / 'source') == spec['source'], 'prepared source drift')
        require(regen.tree(gen) == spec['generated'] and
                prep.validate_inputs(inputs)[1] == spec['manifest_sha256'], 'post-build input drift')
        require(all(sha(Path(p)) == h for p, h in deps.items()) and
                all(sha(Path(p).resolve()) == h for p, h in installed.items()), 'dependency drift')
        for path, pin in pins:
            require(prep.git(path, 'rev-parse', 'HEAD') == pin and
                    not prep.git(path, 'status', '--porcelain', '--untracked-files=all'), 'post-build dependency drift')
        receipt.update(state='compiled', canonical_unchanged=True, source_files=449,
                       generated_files=319, manifest_sha256=spec['manifest_sha256'],
                       compile_commands_sha256=before_commands, installed_dependencies=installed)
    except BaseException as exc:
        receipt.update(state='blocked', blocker=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        receipt['finished_utc'] = utc()
        receipt['cleanup'] = {'session_members': {str(v['session_id']): sorted(session_groups(v['session_id']))
            for v in receipt['stages'].values() if 'session_id' in v},
            'uncertainty': 'Session enumeration cannot exclude descendants that created a new session; remote disconnect cleanup cannot be guaranteed.'}
        save(out / 'receipt.json', receipt)


def private_output(repo, out):
    """Validate without mutation; return the only path dispatch may write to."""
    repo = repo.resolve(strict=True)
    requested = out.absolute()
    # private() uses abspath before checking links. Check the original spelling
    # too, so normalization cannot erase a symlink component followed by '..'.
    for p in (requested, *requested.parents):
        require(not p.is_symlink(), 'symlink private output refused')
    root = prep.private(repo, repo / '.local/linux-sqshl-021')
    out = prep.private(repo, requested)
    # private() enforces repository .local, not this unit's exclusive boundary.
    require(out.is_relative_to(root) and out != root, 'output outside unit ownership')
    require(not out.exists(), 'existing local output refused')
    # A fresh child of a retained run would still mutate historical evidence.
    # Only the ownership root may already exist on the output's parent chain.
    for p in out.parents:
        if p == root:
            break
        require(not p.exists(), 'overlapping local output refused')
    return out


def dispatch(repo, store, out, end):
    out = private_output(repo, out)
    out.mkdir(parents=True, mode=0o700)
    try:
        spec, inputs, gen, manifest = provenance(repo, store)
        common = Path(prep.git(repo, 'rev-parse', '--git-common-dir')).resolve().parent
        control = common / '.local/recovery-control'
        spec['controls'] = controls(store / 'resources.json', control / 'ssh-ready.json',
                                    control / 'runtime-inputs-transfer.json')
        stage(out, 'host-identity', ssh(['python3', '-c', host_probe()]), end)
        save(out / 'provenance.json', spec)
        members = {n: repo / n for n in HELPERS}
        members['tools/linux_sqshl_build.py'] = Path(__file__).resolve()
        for name in spec['generated']:
            members['.local/gen/' + name] = gen / name
        for rec in [manifest['npdm']] + [m[k] for m in manifest['modules'] for k in ('nso', 'flat')]:
            members['.local/inputs/' + rec['path']] = inputs / rec['path']
        members['.local/inputs/.wrapper/manifest.json'] = inputs / '.wrapper/manifest.json'
        hashes = {n: sha(regen.regular(p)) for n, p in members.items()}
        with tarfile.open(out / 'payload.tar.gz', 'w:gz') as tar:
            for name, p in members.items():
                tar.add(p, arcname=name, recursive=False)
        save(out / 'members.json', hashes)
        # Creation is exclusive and occurs only after a second live Pod check.
        script = host_probe() + '; pathlib.Path(%r).mkdir(mode=0o700)' % str(REMOTE)
        stage(out, 'remote-create', ssh(['python3', '-c', script]), end)
        for name in ('payload.tar.gz', 'provenance.json', 'members.json'):
            stage(out, 'transfer-' + name.replace('.', '-'), ['scp', '-q', '-oBatchMode=yes',
                  '-oConnectTimeout=10', str(out / name), HOST + ':' + str(REMOTE / name)], end)
        # Bootstrap only original wrapper/helper files after full archive hash verification.
        bootstrap = "import pathlib,tarfile,hashlib; p=pathlib.Path(%r); a=p/'payload.tar.gz'; assert hashlib.sha256(a.read_bytes()).hexdigest()==%r; t=tarfile.open(a); names=['tools/linux_sqshl_build.py','tools/prepare_runtime.py','tools/import_owned_dump.py','tools/linux_runtime_startup.py','tools/regenerate_sqshl.py','tools/check_sqshl.py']; [(p/pathlib.Path(n).name).write_bytes(t.extractfile(n).read()) for n in names]" % (str(REMOTE), sha(out / 'payload.tar.gz'))
        stage(out, 'bootstrap', ssh(['python3', '-c', bootstrap]), end)
        remote_end = datetime.now(timezone.utc).timestamp() + remaining(end) - 20
        command = ['python3', str(REMOTE / 'linux_sqshl_build.py'), 'remote', '--expires', str(remote_end)]
        try:
            stage(out, 'remote-build', ssh(command), end)
        finally:
            # Compact receipts only; no executable/generated source is fetched.
            pack = "import pathlib,tarfile,hashlib; p=pathlib.Path(%r); files=[f for f in p.iterdir() if f.is_file() and f.suffix in ('.json','.log')]; t=tarfile.open(p/'compact.tar.gz','w:gz'); [t.add(f,arcname=f.name) for f in files]; t.close(); print(hashlib.sha256((p/'compact.tar.gz').read_bytes()).hexdigest())" % str(REMOTE)
            stage(out, 'pack', ssh(['python3', '-c', pack]), end)
            stage(out, 'fetch', ['scp', '-q', '-oBatchMode=yes', HOST + ':' + str(REMOTE / 'compact.tar.gz'),
                                 str(out / 'compact.tar.gz')], end)
            expected = (out / 'pack.log').read_text().strip()
            require(sha(out / 'compact.tar.gz') == expected, 'fetched receipt hash mismatch')
        # Revalidate canonical and retained producer bytes after remote completion.
        after, _, _, _ = provenance(repo, store)
        require(after['generated'] == spec['generated'], 'post-transfer producer drift')
    except BaseException as exc:
        save(out / 'refusal.json', {'utc': utc(), 'error': type(exc).__name__ + ': ' + str(exc),
             'remote_cleanup_uncertainty': 'Consult remote stage receipts; no unrelated host/process operation authorized.'})
        raise


def main():
    global POD
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt('SIGTERM')))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['dispatch', 'remote'])
    p.add_argument('--store', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--expires', type=float)
    p.add_argument('--pod', default=POD, help='Owned RunPod Pod id (default: $ACS_RUNPOD_POD_ID)')
    a = p.parse_args()
    POD = a.pod
    try:
        now = datetime.now(timezone.utc)
        cutoff = datetime(2026, 10, 18, 14, 30, tzinfo=timezone.utc)
        deadline = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)
        require(now < cutoff, 'dispatch cutoff reached')
        end = time.monotonic() + min(1500, (deadline - now).total_seconds())
        if a.mode == 'dispatch':
            require(a.store is not None and a.out is not None, 'store/out required')
            dispatch(Path(__file__).resolve().parents[1], a.store, a.out.absolute(), end)
        else:
            require(sys.platform == 'linux' and Path(__file__).resolve().parent == REMOTE, 'remote ownership mismatch')
            require(a.expires is not None and a.expires <= deadline.timestamp(), 'remote expiry required')
            end = min(end, time.monotonic() + a.expires - time.time())
            require(remaining(end) > 0, 'remote expired')
            safe_unpack(REMOTE / 'payload.tar.gz', REMOTE / 'repo', read(REMOTE / 'members.json'))
            (REMOTE / 'repo/.gitignore').write_text('.local/\n')
            native(REMOTE / 'provenance.json', REMOTE, end)
    except (ValueError, OSError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
        p.exit(1, 'build blocked: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
