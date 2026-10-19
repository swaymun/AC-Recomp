#!/usr/bin/env python3
"""Bounded receipt supervisor for the reviewed private Astral preparation interface.

No SSH, provisioning, regeneration or runtime implementation changes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time

import prepare_runtime as prepare

ERRORS = (ValueError, OSError, KeyError, subprocess.SubprocessError,
          prepare.struct.error, prepare.inventory.ImportFailure, prepare.control.Failure, TypeError)
LIMIT = 16 * 1024 * 1024
# Explicit independently reviewed dispatch main; never accept a CLI pin.
REVIEWED = '1a394ccc296f091115f273640560cd566f4af256'
PROFILE = 'linux-hid-cumulative-v1'
# Owned RunPod identity comes from configuration, never from source.
POD_ENV = 'ACS_RUNPOD_POD_ID'
GENERATED_RECEIPT_SHA = 'a3c9827ead0ee15fbc3a7474b043d8bcb637a6672a849d7e1448344220e06d9a'
CONTROL_RECEIPT_SHA = 'f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88'
PATCHES = ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
           'astral-sqshl.patch', 'astral-audio.patch', 'astral-notifications.patch',
           'astral-apm.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch', 'astral-hid.patch')
TARGETS = {'macos-arm64', 'windows-x86_64', 'linux-x86_64', 'ios-ipados-simulator-arm64'}
IDENTITY_PATHS = ('tools/prepare_runtime.py', 'tools/import_owned_dump.py',
                  'runtime/patches/apple-memory.patch', 'runtime/patches/astral-bootstrap.patch',
                  'tools/extract_control_metadata.py', 'tools/cnmt_metadata.py', 'tools/nacp_metadata.py',
                  'dependencies.lock') + tuple('runtime/patches/' + p for p in PATCHES[2:])


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return {'sha256': prepare.sha(path), 'bytes': path.stat().st_size}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def session_groups(pid):
    """Ninja gives compilers their own groups; all remain in our owned session."""
    groups = {pid}
    proc = Path('/proc')
    if proc.is_dir():
        for member in proc.iterdir():
            if not member.name.isdigit():
                continue
            try:
                fields = (member / 'stat').read_text().rsplit(')', 1)[1].split()
                if int(fields[3]) == pid:
                    groups.add(int(fields[2]))
            except (OSError, ValueError, IndexError):
                continue
    return groups


def stop_group(pid, poll=lambda: None):
    # Always address our new session, even after its leader has exited.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for group in session_groups(pid):
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(0.2)
            poll()  # Reap the leader; Darwin rejects signaling a zombie-only group.


def run_stage(argv, log, seconds, cwd=None, env=None, watch=()):
    """Execute real children with bounded output and owned-session cleanup."""
    started = time.monotonic()
    result = {'argv': list(map(str, argv)), 'cwd': str(cwd) if cwd else None,
              'started_utc': utc(), 'bound_seconds': max(0, seconds),
              'environment': {k: env[k] for k in ('CC', 'CXX', 'NX_TRACE', 'NX_LOG', 'NX_DATA_ROOT',
                                                'SDL_VIDEODRIVER', 'VK_ICD_FILENAMES')
                              if env and k in env}, 'timeout': False, 'log_limit': False}
    p = None
    try:
        prepare.require(seconds > 0, 'unit deadline reached')
        with log.open('wb') as output, selectors.DefaultSelector() as selector:
            p = subprocess.Popen(result['argv'], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, start_new_session=True)
            result['pid'] = p.pid
            result['session_id'] = os.getsid(p.pid)
            os.set_blocking(p.stdout.fileno(), False)
            selector.register(p.stdout, selectors.EVENT_READ)
            written = 0
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= seconds:
                    result['timeout'] = True
                    break
                if any(x.exists() and x.stat().st_size > LIMIT for x in watch):
                    result['log_limit'] = True
                    break
                for key, _ in selector.select(min(0.1, max(0, seconds - elapsed))):
                    block = os.read(key.fd, 65536)
                    if block:
                        output.write(block[:max(0, LIMIT - written)])
                        output.flush()
                        written += len(block)
                        if written > LIMIT:
                            result['log_limit'] = True
                    else:
                        selector.unregister(key.fileobj)
                if result['log_limit'] or (p.poll() is not None and not selector.get_map()):
                    break
            result['cleanup_groups'] = sorted(session_groups(p.pid))
            stop_group(p.pid, p.poll)
            result['exit_code'] = p.wait(timeout=3)
            p.stdout.close()
    except BaseException as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        if p is not None:
            result['cleanup_groups'] = sorted(session_groups(p.pid))
            stop_group(p.pid, p.poll)
            result['exit_code'] = p.wait(timeout=3)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        result['finished_utc'] = utc()
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if log.exists():
            result['log'] = {'path': str(log), **digest(log)}
        result['signal'] = -result['exit_code'] if result.get('exit_code', 0) < 0 else None
        result['ok'] = result.get('exit_code') == 0 and not any(
            result.get(k) for k in ('timeout', 'log_limit', 'error'))
        save(log.with_suffix('.json'), result)
    return result


def compile_counts(commands, build):
    objects = []
    sources = {}
    for entry in commands:
        source = Path(entry['file'])
        if not source.is_absolute():
            source = Path(entry.get('directory', build)) / source
        sources[str(source)] = digest(source) if source.is_file() else {'present': False}
        args = entry.get('arguments') or shlex.split(entry['command'])
        if '-o' in args:
            obj = Path(args[args.index('-o') + 1])
            objects.append(obj if obj.is_absolute() else Path(entry.get('directory', build)) / obj)
    return {'compile_commands': len(commands), 'object_paths_measured': len(objects),
            'objects_present': sum(x.is_file() for x in objects),
            'objects_absent': sum(not x.is_file() for x in objects),
            'translation_units': sources,
            'object_identities': {str(x): digest(x) if x.is_file() else {'present': False} for x in objects}}



def budget_cap():
    """Optional owner budget cap in USD from ACS_BUDGET_CAP_USD; the amount is configuration, not source."""
    value = os.environ.get('ACS_BUDGET_CAP_USD', '').strip()
    return float(value) if value else None

def controls(store, now):
    """Only the current approved afternoon store, never a caller-chosen deadline."""
    def read(name):
        path = store / name
        prepare.require(path.is_file() and not path.is_symlink() and
                        path.stat().st_nlink == 1 and path.stat().st_size <= LIMIT,
                        'unsafe control file: ' + name)
        return path.read_bytes()
    raw = {name: read(name) for name in
           ('AUTHORIZATION.md', 'RUN_OBJECTIVE.md', 'lead-config.json', 'config.json')}
    cfg, worker = (json.loads(raw[n]) for n in ('lead-config.json', 'config.json'))
    prepare.require(store.name == worker['date'] == '2026-10-18-afternoon' and
                    cfg['task_id'] == 'acs-afternoon-20261018' and cfg['mode'] == 'game',
                    'wrong afternoon controls')
    prepare.require(len(cfg['targets']) == 4 and set(cfg['targets']) == TARGETS,
                    'all four targets required')
    approval = cfg['owner_approval']
    prepare.require(approval['approved'] is True and approval['task_id'] == cfg['task_id'] and
                    approval['targets'] == cfg['targets'] and approval['deadline'] == cfg['deadline'] and
                    approval['authorization_sha256'] == hashlib.sha256(raw['AUTHORIZATION.md']).hexdigest()
                    and raw['RUN_OBJECTIVE.md'].strip(), 'approval/control mismatch')
    prepare.require(cfg['deadline'] == '2026-10-18T21:00:00Z' and
                    cfg['dispatch_stop_at'] == cfg['morning_report_at'] == '2026-10-18T20:30:00Z',
                    'stale or extended afternoon controls')
    prepare.require(type(worker['max_workers']) is int and 1 <= worker['max_workers'] <= 3 and
                    type(worker['budget_usd']) in (int, float) and 0 < worker['budget_usd'] and
                    (budget_cap() is None or worker['budget_usd'] <= budget_cap()),
                    'invalid worker/budget controls')
    prepare.require(now < datetime(2026, 10, 18, 20, 30, tzinfo=timezone.utc), 'dispatch cutoff reached')
    prepare.require(now >= datetime(2026, 10, 18, 15, tzinfo=timezone.utc), 'afternoon not started')
    return datetime(2026, 10, 18, 21, tzinfo=timezone.utc), {
        name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}


def validate_receipts(repo, inputs, gen, generated_receipt, control_metadata):
    manifest, mh = prepare.validate_inputs(inputs)
    generated = prepare.generated_evidence(gen, manifest)
    reviewed = prepare.private(repo, generated_receipt)
    control = prepare.private(repo, control_metadata)
    for path, expected in ((reviewed, GENERATED_RECEIPT_SHA), (control, CONTROL_RECEIPT_SHA)):
        prepare.require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1 and
                        prepare.sha(path) == expected, 'reviewed private receipt mismatch')
    prepare.validate_reviewed_generated(json.loads(reviewed.read_text()), generated, mh)
    binding, ch = prepare.validate_control(control, manifest, mh)
    return {'generated_receipt': digest(reviewed), 'control_receipt': digest(control),
            'control': binding, 'control_receipt_sha256': ch}


def reviewed_source(repo):
    prepare.git(repo, 'merge-base', '--is-ancestor', REVIEWED, 'HEAD')
    files = {}
    for name in IDENTITY_PATHS:
        expected = subprocess.check_output(['git', '-C', str(repo), 'show', f'{REVIEWED}:{name}'])
        actual = repo / name
        prepare.require(actual.is_file() and not actual.is_symlink() and actual.stat().st_nlink == 1 and
                        hashlib.sha256(expected).hexdigest() == prepare.sha(actual),
                        f'reviewed source drift: {name}')
        files[name] = digest(actual)
    prepare.require(prepare.ROOT.resolve() == repo, 'wrapper and preparation repo differ')
    prepare.require(not prepare.git(repo, 'status', '--porcelain', '--untracked-files=no'), 'dirty tracked repo')
    return files


def validate_composition(value, repo, source):
    identity, composition = value['identity'], value['composition']
    hashes = {p: prepare.sha(repo / 'runtime/patches' / p) for p in PATCHES}
    prepare.require(identity.get('profile') == PROFILE and identity.get('pin') == prepare.PIN and
                    identity.get('patch_order') == list(PATCHES) and
                    list(identity['patches']) == list(PATCHES) and identity['patches'] == hashes and
                    [x.get('name') for x in composition] == list(PATCHES),
                    'incomplete overlay composition or stale profile')
    for name, item in zip(PATCHES, composition):
        prepare.require(all(item.get(k) == v for k, v in digest(repo / 'runtime/patches' / name).items()) and
                        item.get('state') in ('applied', 'already-applied') and item.get('source_after'),
                        'tampered overlay composition: ' + name)
    prepare.require(prepare.git(source, 'rev-parse', 'HEAD') == prepare.PIN and
                    value['source'] == prepare.source_fingerprint(source), 'composed source drift')


def parent_readiness(a, hashes, now):
    path = prepare.private(a.repo.resolve(), a.parent_readiness)
    prepare.require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1 and
                    path.stat().st_size <= LIMIT, 'unsafe parent readiness')
    value = json.loads(path.read_text())
    pod = getattr(a, 'pod', None) or os.environ.get(POD_ENV, '')
    prepare.require(bool(pod), 'owned Pod id required (--pod or ' + POD_ENV + ')')
    at = datetime.fromisoformat(value['at'].replace('Z', '+00:00'))
    prepare.require(value['schema'] == 1 and value['unit'] == 'LINUX-HID-CUMULATIVE-049' and
                    value['pod'] == pod and value['alias'] == 'acs-afternoon-linux' and
                    value['head'] == prepare.git(a.repo, 'rev-parse', 'HEAD') and
                    value['profile'] == PROFILE and value['wrapper'] == digest(Path(__file__)) and
                    value['afternoon_controls'] == hashes and value['live_stop_absent'] is True and
                    value['review']['verdict'] == 'pass' and value['review']['head'] == value['head'] and
                    value['review']['model'] == 'gpt-6-astra' and value['review']['effort'] == 'medium' and
                    0 <= (now - at).total_seconds() <= 600,
                    'fresh exact cumulative parent readiness required')
    return digest(path)


def prepare_composed(a):
    """Use the existing preparation interface with the landed ordered patch list."""
    original = prepare.prepare_source
    original_logged = prepare.run_logged
    inventory = []
    def inherited_logged(command, log, cwd=None, env=None, timeout=600):
        # Keep configure children in the supervisor's owned session.
        with log.open('w') as output:
            output.write(json.dumps({'argv': list(map(str, command)), 'cwd': str(cwd)}) + '\n')
            output.flush()
            child = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                   stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        prepare.require(child.returncode == 0, f'child exit {child.returncode}; see {log}')
    def compose(reference, source, patches):
        prepare.require([p.name for p in patches] == list(PATCHES[:2]), 'unexpected base patches')
        original(reference, source, [])
        for name in PATCHES:
            patch = a.repo / 'runtime/patches' / name
            argv = ['git', '-C', str(source), 'apply']
            reverse = subprocess.run([*argv, '--reverse', '--check', str(patch)],
                                     capture_output=True, timeout=30)
            state = 'already-applied' if reverse.returncode == 0 else 'applied'
            if reverse.returncode:
                subprocess.run([*argv, '--check', str(patch)], check=True, timeout=30)
                subprocess.run([*argv, str(patch)], check=True, timeout=30)
            inventory.append({'name': name, **digest(patch), 'state': state,
                              'source_after': prepare.source_fingerprint(source)})
        return prepare.source_fingerprint(source)
    prepare.prepare_source = compose
    prepare.run_logged = inherited_logged
    try:
        prepare.execute(a)
        path = a.out / 'prepared.json'
        value = json.loads(path.read_text())
        value['identity']['profile'] = PROFILE
        value['identity']['patch_order'] = list(PATCHES)
        value['identity']['patches'] = {p: prepare.sha(a.repo / 'runtime/patches' / p) for p in PATCHES}
        value['composition'] = inventory
        save(path, value)
    finally:
        prepare.prepare_source = original
        prepare.run_logged = original_logged


def execute(a):
    repo = a.repo.resolve()
    out = prepare.private(repo, a.out)
    prepare.require(not out.exists(), 'fresh unit output required')
    prepare.require(1 <= a.jobs <= 3 and 0 < a.seconds <= 1500, 'jobs/budget out of range')
    now = datetime.now(timezone.utc)
    deadline, control_hashes = controls(a.controls, now)
    readiness = parent_readiness(a, control_hashes, now)
    budget = min(a.seconds, (deadline - now).total_seconds())
    cleanup_reserve = min(15, budget / 10)
    end = time.monotonic() + budget - cleanup_reserve
    prepare.require(end > time.monotonic(), 'deadline expired')
    out.mkdir(parents=True, mode=0o700)
    receipt = {'schema': 1, 'unit': 'LINUX-HID-CUMULATIVE-049', 'parent_readiness': readiness, 'profile': PROFILE, 'afternoon_controls': control_hashes, 'started_utc': utc(),
               'reviewed_head': REVIEWED, 'repository_head': prepare.git(repo, 'rev-parse', 'HEAD'),
               'wrapper': digest(Path(__file__)), 'stages': {}, 'game_frame': False,
               'total_bound_seconds': budget, 'cleanup_reserve_seconds': cleanup_reserve,
               'synthetic_host_frame': 'separate LINUX-GPU-002 evidence',
               'game_metrics': 'unknown', 'cross_isa_byte_match': 'N/A'}
    def remaining():
        return max(0, end - time.monotonic())
    def stage(name, argv, bound=None, **kwargs):
        value = run_stage(argv, out / (name + '.log'), min(remaining(), bound or remaining()), **kwargs)
        receipt['stages'][name] = value
        save(out / 'receipt.json', receipt)
        prepare.require(value['ok'], f'{name} failed; inspect stage receipt')
    provenance = None
    try:
        receipt['reviewed_files'] = reviewed_source(repo)
        inputs, gen = (prepare.private(repo, p) for p in (a.inputs, a.gen))
        prepare.require(not any(x.is_relative_to(y) for x, y in ((out, inputs), (out, gen),
                                                                (inputs, out), (gen, out))), 'overlap refused')
        receipt['private_receipts'] = validate_receipts(repo, inputs, gen, a.generated_receipt, a.control_metadata)
        command = [sys.executable, str(repo / 'tools/linux_runtime_startup.py'), '--prepare-composed', '--repo', str(repo),
                   '--reference', str(a.reference), '--inputs', str(inputs), '--gen', str(gen),
                   '--out', str(out / 'prepared'), '--configure', '--jobs', str(a.jobs),
                   '--generated-receipt', str(a.generated_receipt), '--control-metadata', str(a.control_metadata),
                   '--controls', str(a.controls)]
        for name in ('cmake', 'ninja', 'prefix', 'vulkan_include'):
            command.extend(['--' + name.replace('_', '-'), str(getattr(a, name))])
        env = dict(os.environ, CC='clang', CXX='clang++', PYTHONDONTWRITEBYTECODE='1')
        stage('configure', command, env=env, watch=(out / 'prepared/configure.log',))
        prepared = out / 'prepared'
        provenance = json.loads((prepared / 'prepared.json').read_text())
        receipt['prepared_receipt'] = digest(prepared / 'prepared.json')
        receipt['identity'] = provenance['identity']
        commands_path = prepared / 'build/compile_commands.json'
        commands = json.loads(commands_path.read_text())
        receipt['compile_commands'] = digest(commands_path)
        receipt['compilers'] = {}
        for entry in commands:
            compiler = (entry.get('arguments') or shlex.split(entry['command']))[0]
            if compiler not in receipt['compilers']:
                resolved = shutil.which(compiler)
                prepare.require(resolved is not None, 'compiler identity unavailable')
                tool = Path(resolved).resolve()
                receipt['compilers'][compiler] = {'path': str(tool), **digest(tool)}
        # Store exact flags privately, without duplicating generated source.
        save(out / 'compiler-commands.json', commands)
        prepare.require(any(str(gen / 'main') in x['file'] for x in commands) and
                        any(str(gen / 'sdk') in x['file'] for x in commands), 'real generated targets missing')
        prepare.require(all('-DNX_ASTRAL_STRICT=1' in (x.get('arguments') or shlex.split(x['command']))
                            for x in commands), 'strict compiler flags missing')
        executable = prepared / 'build/astral'
        try:
            validate_composition(provenance, repo, prepared / 'source')
            stage('build', [str(a.cmake), '--build', str(prepared / 'build'), '--parallel',
                            str(a.jobs), '--target', 'astral'], env=env)
        finally:
            receipt['counts'] = compile_counts(commands, prepared / 'build')
        prepare.require(executable.is_file() and not executable.is_symlink(), 'missing real executable')
        prepare.require(prepare.source_fingerprint(prepared / 'source') == provenance['source'], 'source drift')
        validate_receipts(repo, inputs, gen, a.generated_receipt, a.control_metadata)
        manifest, manifest_sha = prepare.validate_inputs(inputs)
        prepare.require(manifest_sha == provenance['identity']['manifest_sha256'] and
                        prepare.generated_evidence(gen, manifest) == provenance['identity']['generated'], 'input drift')
        receipt['executable'] = {'path': str(executable), **digest(executable)}
        startup_env = dict(env, NX_TRACE='1', NX_DATA_ROOT=str(inputs), NX_LOG=str(out / 'startup-trace.log'))
        startup_argv = [str(executable)]
        if getattr(a, 'xvfb_run', None):
            startup_argv = [str(a.xvfb_run), '-a', '-s',
                            '-screen 0 1280x720x24 -nolisten tcp', *startup_argv]
            startup_env.update(SDL_VIDEODRIVER='x11',
                               VK_ICD_FILENAMES='/etc/vulkan/icd.d/nvidia_icd.json')
        stage('startup', startup_argv, bound=60, cwd=out, env=startup_env,
              watch=(out / 'startup-trace.log',))
    except ERRORS as exc:
        receipt['blocker'] = str(exc)
    finally:
        if provenance is not None:
            try:
                validate_receipts(repo, inputs, gen, a.generated_receipt, a.control_metadata)
                manifest, manifest_sha = prepare.validate_inputs(inputs)
                receipt['post_run_identity_unchanged'] = (
                    prepare.source_fingerprint(prepared / 'source') == provenance['source'] and
                    manifest_sha == provenance['identity']['manifest_sha256'] and
                    prepare.generated_evidence(gen, manifest) == provenance['identity']['generated'])
                if not receipt['post_run_identity_unchanged']:
                    receipt['blocker'] = 'post-run source/input identity drift'
            except ERRORS as exc:
                receipt['blocker'] = f'post-run identity validation failed: {exc}'
        trace = out / 'startup-trace.log'
        if trace.is_file():
            lines = trace.read_bytes()[:LIMIT].decode(errors='replace').splitlines()
            receipt['trace_observations'] = [x for x in lines if any(token in x.lower() for token in
                ('strict ', 'fatal', 'constructor', 'nnmain', 'nn::init', '__rtld', 'service=', 'vulkan', 'gpu:'))][-100:]
            receipt['first_fatal_line'] = next((x for x in lines if 'FATAL:' in x), None)
        for log in (out / 'startup-trace.log', out / 'prepared/configure.log'):
            if log.is_file():
                receipt.setdefault('extra_logs', {})[str(log)] = digest(log)
        receipt['finished_utc'] = utc()
        save(out / 'receipt.json', receipt)
    print(json.dumps({'receipt': str(out / 'receipt.json'), 'blocker': receipt.get('blocker'),
                      'game_frame': False}))
    return 1 if receipt.get('blocker') else 0


def interrupted(signum, frame):
    raise KeyboardInterrupt(f'received signal {signum}')


def main():
    signal.signal(signal.SIGTERM, interrupted)
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'reference', 'inputs', 'gen', 'out', 'cmake', 'ninja', 'prefix', 'vulkan-include'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--xvfb-run', type=Path, help='Owned virtual X11 session for headless NVIDIA startup')
    p.add_argument('--jobs', type=int, default=3)
    p.add_argument('--seconds', type=float, default=1200)
    p.add_argument('--controls', type=Path, help='Validated afternoon store (execution required)')
    p.add_argument('--generated-receipt', type=Path, required=True)
    p.add_argument('--control-metadata', type=Path, required=True)
    p.add_argument('--parent-readiness', type=Path, help='Fresh parent exact-head review/staging receipt')
    p.add_argument('--pod', default=os.environ.get(POD_ENV, ''),
                   help='Owned RunPod Pod id named in parent readiness (default: $' + POD_ENV + ')')
    p.add_argument('--prepare-composed', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--configure', action='store_true', help=argparse.SUPPRESS)
    try:
        a = p.parse_args()
        if a.prepare_composed:
            prepare.require(a.controls is not None, 'afternoon controls required')
            controls(a.controls, datetime.now(timezone.utc))
            reviewed_source(a.repo.resolve())
            validate_receipts(a.repo.resolve(), a.inputs, a.gen, a.generated_receipt, a.control_metadata)
            a.build = False
            prepare_composed(a)
            return 0
        prepare.require(a.controls is not None and a.xvfb_run is not None and a.parent_readiness is not None,
                        'afternoon controls, fresh parent readiness and owned Xvfb required')
        return execute(a)
    except ERRORS as exc:
        p.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    sys.exit(main())
