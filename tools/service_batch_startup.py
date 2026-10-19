#!/usr/bin/env python3
"""One private, bounded cumulative nativeMac service integration measurement."""
import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import subprocess
import sys
import time

import prepare_runtime as prepare

ROOT = Path(__file__).resolve().parents[1]
BASE = 'a8984f8a6c9986b4261fb515bb6f9005e2940639'
DEPENDENCIES = {
    'LOGGER-RUNTIME-029': ('eaa42fb9fa34afa9143116e903e6d85625817a85', '748fe27a0a507ca9c934b3a7c1dfd6b949207491'),
    'AUDIOOUT-COMPAT-032': ('a539fd08fadec5ec9e264c6cb707462cc656e924', 'a539fd08fadec5ec9e264c6cb707462cc656e924'),
    'APPLET-NOTIFY-033': (BASE, 'ed7877483faa45886fcd91ade1343ce114eac175'),
    'IPC-BUFFER-FRAMING-039': ('0e9ee64ae97054e2870055bd1ca76ba97b2a3b8b', '0e9ee64ae97054e2870055bd1ca76ba97b2a3b8b'),
    'APPLET-STORAGE-INTEGRATION-044': ('df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca', 'df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca'),
    'HID-ABI-COMPAT-045': ('0ee4224829d3d23c232b3906a5c0f77ffbf92c64', '0ee4224829d3d23c232b3906a5c0f77ffbf92c64'),
    'HID-CONTROLLER-SUPPORT-051': ('23caac0df9129c973de3f8bf29e04c3065e0b779', '23caac0df9129c973de3f8bf29e04c3065e0b779'),
    'APM-SESSION-030': ('791031333db04f67688c47b868bcd1ab5be4b246', '791031333db04f67688c47b868bcd1ab5be4b246'),
}
PREPARATION_DEPENDENCY = {'IOS-CUMULATIVE-041': (
    '314678ae893c27ce3d6cfb0cae0ec18e15950a3c', 'd8b1c49fc79127d93bdeb93e129eb9e0d4c7570f')}
PREPARATION_REVIEW_BASES = {'IOS-CUMULATIVE-041': 'df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca'}
SERVICE_REVIEW_BASES = {'HID-CONTROLLER-SUPPORT-051': '36cc87bc5936d5d3ed8171143535ec0d01339314'}
PARSER_DEPENDENCY = {'MAC-FATAL-PARSER-056': (
    '1c6dbeb46e0f45f83f31a6532ad570306f9f6ea6', '8d75571cef2e93cc602cba03f114abc5b0c7f119')}
PATCHES = ['apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
           'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch',
           'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch',
           'astral-hid.patch', 'astral-controller-support.patch']
SUPPORT = ['tools/prepare_runtime.py', 'tools/import_owned_dump.py', 'tools/extract_control_metadata.py',
           'tools/cnmt_metadata.py', 'tools/nacp_metadata.py', 'runtime/patches/astral-control-import.patch', 'runtime/patches/astral-sqshl.patch', 'dependencies.lock']
LIMIT = 16 * 1024 * 1024
require = prepare.require


def utc():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1, 'unsafe receipt')
    require(path.stat().st_size <= LIMIT, 'oversize receipt')
    return json.loads(path.read_text())


def digest(path):
    stat = path.stat()
    require(path.is_file() and not path.is_symlink() and stat.st_nlink == 1, 'unsafe evidence file')
    return {'sha256': prepare.sha(path), 'bytes': stat.st_size}


def save(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    tmp.replace(path)


def git(repo, *args):
    return prepare.git(repo, *args)


def patch_identity(repo, base, head):
    diff = git(repo, 'diff', '--binary', '--full-index', '--no-ext-diff', '--no-renames', '--unified=0', base, head)
    # git() strips the final newline; orchlib includes it in its normalized identity.
    normalized = '\n'.join(s for s in (diff + '\n').split('\n')
                           if not s.startswith(('index ', '@@ ')))
    return hashlib.sha256(normalized.encode()).hexdigest()



def budget_cap():
    """Optional owner budget cap in USD from ACS_BUDGET_CAP_USD; the amount is configuration, not source."""
    value = os.environ.get('ACS_BUDGET_CAP_USD', '').strip()
    return float(value) if value else None

def controls(store, now=None):
    now = now or datetime.now(timezone.utc)
    c, lead = read(store / 'config.json'), read(store / 'lead-config.json')
    auth = digest(store / 'AUTHORIZATION.md')['sha256']
    approval = lead['owner_approval']
    targets = ['macos-arm64', 'windows-x86_64', 'linux-x86_64', 'ios-ipados-simulator-arm64']
    cap, budget = budget_cap(), c['budget_usd']
    require(type(budget) in (int, float) and budget > 0 and (cap is None or budget == cap) and
            c['max_workers'] == 3, 'budget/worker controls drift')
    require(lead['mode'] == 'game' and lead['targets'] == targets, 'target/mode controls drift')
    require(approval['approved'] is True and approval['targets'] == targets and
            approval['task_id'] == lead['task_id'] and approval['deadline'] == lead['deadline'] and
            approval['authorization_sha256'] == auth, 'stale owner authorization')
    require(lead['deadline'] == '2026-10-18T21:00:00Z' and
            lead['dispatch_stop_at'] == '2026-10-18T20:30:00Z', 'deadline controls drift')
    require(now.date().isoformat() == '2026-10-18' and
            now < datetime(2026, 10, 18, 20, 30, tzinfo=timezone.utc), 'stale/late controls')
    require(not (store / 'STOP').exists(), 'store stopped')
    return {name: digest(store / name) for name in ('RUN_OBJECTIVE.md', 'AUTHORIZATION.md', 'config.json', 'lead-config.json')}


def review_record(store, run_id):
    require(re.fullmatch('[A-Za-z0-9_-]+', run_id) is not None, 'invalid review run identity')
    path = store / 'reports' / (run_id + '.review.json')
    if path.exists():
        return read(path), {path.name: digest(path)}
    # A normally finalized CLI review uses separate scheduler metadata and final
    # result; recovered reviews may instead have the combined .review record.
    metadata = store / 'runs' / (run_id + '.json')
    final = store / 'reports' / (run_id + '.final.json')
    meta, report = read(metadata), read(final)
    require(all(meta[k] == report[k] for k in ('run_id', 'kind', 'head', 'patch')), 'review metadata/final mismatch')
    return dict(meta, verdict=report['verdict'], report=report), {metadata.name: digest(metadata), final.name: digest(final)}


def reviewed(repo, store, mandatory=None, review_bases=None, consumed=None, historical_only=False):
    """Authenticate whole historical reviews; only explicit successors explain drift.

    Default service dependencies still require every current scoped file. The
    preparation caller identifies its consumed files: those must remain exact,
    while other scoped files may evolve through independently reviewed landings.
    """
    mandatory = DEPENDENCIES if mandatory is None else mandatory
    with (store / 'units.tsv').open() as stream:
        entries = list(csv.DictReader(stream, delimiter='\t'))
    rows = {x['id']: x for x in entries}
    require(len(rows) == len(entries), 'duplicate dependency identity')
    authenticated = {}

    def authenticate(unit, landed, exact):
        require(re.fullmatch('[0-9a-f]{40}', landed) and re.fullmatch('[0-9a-f]{40}', exact), 'invalid commit identity')
        if unit in authenticated:
            value = authenticated[unit]
            require((value['landed'], value['reviewed']) == (landed, exact), 'conflicting dependency identity')
            return value
        row = rows[unit]
        require(row['state'] == 'landed' and row['head'] == landed, 'dependency not landed at expected head')
        require(row['review_run_id'] != row['run_id'], 'dependent review identity')
        review, review_digests = review_record(store, row['review_run_id'])
        require(review['kind'] == 'review' and review['verdict'] == 'pass' and
                review['model'] == 'gpt-6-astra' and review['effort'] == 'medium' and
                review['head'] == exact and review['producer_run'] == row['run_id'] and
                review['patch'] == row['patch'], 'missing exact-head Astra review')
        require(review['report']['unit'] == unit and review['report']['head'] == exact and
                review['report']['patch'] == row['patch'] and
                review['report']['verdict'] == 'pass', 'review report mismatch')
        candidates = ((review_bases[unit],) if review_bases and unit in review_bases else (row['base'], exact + '^'))
        bases = [base for base in candidates
                 if patch_identity(repo, base, exact) == row['patch']]
        require(bases, 'reviewed patch mismatch')
        review_base = bases[0]
        git(repo, 'merge-base', '--is-ancestor', review_base, exact)
        git(repo, 'merge-base', '--is-ancestor', landed, 'main')
        git(repo, 'merge-base', '--is-ancestor', landed, 'HEAD')
        paths = row['files'].split(',')
        require(len(paths) == len(set(paths)) and all(p and not Path(p).is_absolute() and
                '..' not in Path(p).parts for p in paths), 'unsafe review paths')
        changed = set(git(repo, 'diff', '--name-only', review_base, exact).splitlines())
        require(changed == set(paths), 'review scope mismatch')
        files = {}
        for path in paths:
            require(git(repo, 'rev-parse', f'{exact}:{path}') == git(repo, 'rev-parse', f'{landed}:{path}'), 'landing content mismatch')
            files[path] = hashlib.sha256(subprocess.check_output(
                ['git', '-C', str(repo), 'show', f'{landed}:{path}'])).hexdigest()
        value = {'landed': landed, 'reviewed': exact, 'patch': row['patch'],
                 'review_receipts': review_digests, 'review_base': review_base, 'files': files,
                 'supersessions': {}}
        authenticated[unit] = value
        return value

    checked = set()

    def current(unit, active=()):
        require(unit not in active, 'cyclic supersession')
        if unit in checked:
            return
        value = authenticated[unit]
        for path, expected in value['files'].items():
            if digest(repo / path)['sha256'] == expected:
                continue
            require(consumed is not None and path not in consumed, 'reviewed file drift')
            # A dependency edge is explicit evidence of succession, not a
            # blanket exemption for files outside the Mac consumption set.
            successors = [r for r in entries if r['state'] == 'landed' and
                          unit in r.get('deps', '').split(',') and path in r['files'].split(',')]
            require(len(successors) == 1, 'missing/ambiguous reviewed successor')
            successor = successors[0]
            name = successor['id']
            review, _ = review_record(store, successor['review_run_id'])
            replacement = authenticate(name, successor['head'], review['head'])
            git(repo, 'merge-base', '--is-ancestor', value['landed'], replacement['review_base'])
            git(repo, 'merge-base', '--is-ancestor', value['landed'], replacement['landed'])
            require(git(repo, 'rev-parse', f"{value['landed']}:{path}") ==
                    git(repo, 'rev-parse', f"{replacement['review_base']}:{path}"), 'successor baseline mismatch')
            current(name, (*active, unit))
            value['supersessions'][path] = name
        checked.add(unit)

    for unit, (landed, exact) in mandatory.items():
        authenticate(unit, landed, exact)
    if consumed is not None:
        require(set(consumed) <= {p for u in mandatory for p in authenticated[u]['files']},
                'consumed file outside review scope')
    if not historical_only:
        for unit in mandatory:
            current(unit)
    return authenticated


def shared_preparation(repo, store):
    """Consume exact IOS041 helper bytes; authenticate unrelated successors."""
    result = {}
    for path in SUPPORT + ['runtime/patches/' + x for x in PATCHES[:2]]:
        current = digest(repo / path)
        original = hashlib.sha256(subprocess.check_output(
            ['git', '-C', str(repo), 'show', BASE + ':' + path])).hexdigest()
        if current['sha256'] != original:
            require(path == 'tools/prepare_runtime.py', 'shared preparation/base drift')
            result['review'] = reviewed(repo, store, PREPARATION_DEPENDENCY, PREPARATION_REVIEW_BASES,
                                        consumed={'tools/prepare_runtime.py'})
            # Every historical scope is authenticated in full. Only explicitly
            # reviewed landed successors can explain non-consumed scope drift.
        result[path] = current
    return result


def parser_fragments(source):
    """Bind the exact reviewed parser text and its only mutable local constant."""
    tree = ast.parse(source)
    nodes = [n for n in tree.body if
             isinstance(n, ast.FunctionDef) and n.name == 'safe_observations' or
             isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LIMIT' for t in n.targets)]
    require(len(nodes) == 2, 'missing/duplicate parser fragments')
    return {('safe_observations' if isinstance(n, ast.FunctionDef) else 'LIMIT'):
            hashlib.sha256(ast.get_source_segment(source, n).encode()).hexdigest() for n in nodes}


def parser_provenance(repo, store):
    # The full historical review remains authenticated. This integration changes
    # supervisor/tests; only the parser and LIMIT are consumed from that review.
    history = reviewed(repo, store, PARSER_DEPENDENCY, historical_only=True)
    exact = next(iter(PARSER_DEPENDENCY.values()))[1]
    original = subprocess.check_output(['git', '-C', str(repo), 'show',
                                        exact + ':tools/service_batch_startup.py']).decode()
    fragments = parser_fragments((repo / 'tools/service_batch_startup.py').read_text())
    require(fragments == parser_fragments(original), 'reviewed parser drift')
    return {'historical_review': history, 'consumed_fragments': fragments}


def cumulative_patches(repo, store, names=None):
    names = PATCHES if names is None else names
    expected = ['apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch',
                'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch',
                'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch',
                'astral-hid.patch', 'astral-controller-support.patch']
    require(names == expected, 'cumulative overlay order mismatch')
    dependencies = reviewed(repo, store, review_bases=SERVICE_REVIEW_BASES)
    preparation = shared_preparation(repo, store)
    patches = [repo / 'runtime/patches' / name for name in names]
    # Baseline-pinned control/SQSHL/memory overlays and independently reviewed
    # service overlays jointly authenticate every consumed patch.
    authenticated = {p: h for value in dependencies.values() for p, h in value['files'].items()}
    authenticated.update({p: d['sha256'] for p, d in preparation.items() if p != 'review'})
    for path in patches:
        require(digest(path)['sha256'] == authenticated.get(str(path.relative_to(repo))),
                'unauthenticated cumulative overlay')
    return patches, dependencies, preparation


def object_identities(commands, build):
    result = {}
    for entry in commands:
        args = entry.get('arguments') or shlex.split(entry['command'])
        require(args.count('-o') == 1, 'missing/ambiguous object output')
        path = Path(args[args.index('-o') + 1])
        if not path.is_absolute():
            path = Path(entry['directory']) / path
        path = path.resolve()
        require(path.is_relative_to(build.resolve()), 'object outside fresh build')
        name = str(path.relative_to(build.resolve()))
        require(name not in result, 'duplicate object output')
        result[name] = digest(path)
    return result


def check_flags(commands, gen):
    require(commands, 'empty compilation database')
    files = [Path(x['file']) for x in commands]
    require(all(any(p.is_relative_to(gen / name) for p in files) for name in ('main', 'sdk')), 'missing real generated modules')
    for entry in commands:
        args = entry.get('arguments') or shlex.split(entry['command'])
        for macro in ('NX_APPLE_HIGH_MEMORY', 'NX_ASTRAL_STRICT'):
            values = [x for x in args if x.startswith('-D' + macro)]
            require(values == ['-D' + macro + '=1'] and not any(x.startswith('-U' + macro) for x in args), 'mixed/unsafe compiler profile')


def process_table():
    rows = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='], text=True)
    return [(int(parts[0]), int(parts[1]), int(parts[2]), ' '.join(parts[3:]))
            for row in rows.splitlines() if (parts := row.split())]


def descendants(pid):
    table = process_table()
    owned = {pid}
    while True:
        new = owned | {p for p, parent, group, born in table if parent in owned}
        if new == owned:
            return {p: (group, born) for p, parent, group, born in table if p in owned}
        owned = new


def live_owned_groups(owned):
    return {group for pid, parent, group, born in process_table()
            if owned.get(pid) == (group, born)}


def run_stage(argv, log, seconds, cwd=None, env=None):
    require(isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv), 'argv list required; shell strings refused')
    require(0 < seconds <= 1490, 'invalid stage bound')
    started = time.monotonic()
    result = {'started_utc': utc(), 'bound_seconds': seconds, 'argv': argv, 'timeout': False, 'output_limit': False}
    p = None
    owned = {}
    try:
        with log.open('xb') as output, selectors.DefaultSelector() as selector:
            p = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            result['pid'] = p.pid
            os.set_blocking(p.stdout.fileno(), False)
            selector.register(p.stdout, selectors.EVENT_READ)
            count = 0
            while time.monotonic() - started < seconds:
                owned.update(descendants(p.pid))
                if any(x.is_file() and x.stat().st_size > LIMIT for x in log.parent.glob('*trace.log')):
                    result['output_limit'] = True
                    break
                for key, _ in selector.select(0.05):
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                    else:
                        output.write(block[:max(0, LIMIT-count)])
                        count += len(block)
                        if count > LIMIT:
                            result['output_limit'] = True
                if result['output_limit'] or (p.poll() is not None and not selector.get_map()):
                    break
            else:
                result['timeout'] = True
    finally:
        if p is not None:
            # Ninja may create separate child process groups: retain every observed
            # owned group, including after the root exits. Never use global pkill.
            owned.update(descendants(p.pid))
            # A finished compiler PID/PGID may be reused during a long build.
            # Only signal groups containing an observed PID with the same birth
            # identity; a cached numeric group alone never authorizes a signal.
            groups = live_owned_groups(owned)
            result['observed_owned_groups'] = len({group for group, born in owned.values()})
            result['cleanup_groups'] = sorted(groups)
            for sig in (signal.SIGTERM, signal.SIGKILL):
                for group in groups:
                    if group == os.getpgrp():
                        continue
                    try:
                        os.killpg(group, sig)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        p.poll()
                        live = subprocess.check_output(['/bin/ps', '-axo', 'pgid=,stat='], text=True)
                        require(not any(int(row.split()[0]) == group and not row.split()[1].startswith('Z')
                                        for row in live.splitlines() if row.strip()), 'owned group cleanup denied')
                if sig == signal.SIGTERM:
                    time.sleep(0.2)
                    p.poll()
            result['exit_code'] = p.wait(timeout=3)
            p.stdout.close()
        result['finished_utc'] = utc()
        result['elapsed_seconds'] = time.monotonic() - started
        result['log'] = digest(log) if log.exists() else None
        save(log.with_suffix('.json'), result)
    return result


def safe_observations(logs):
    """Extract fixed fields from complete LF lines within LIMIT bytes per log.

    Caller log order, then physical line order, selects the first fatal. A final
    unterminated line counts only at observed EOF; unread tails are unverified.
    """
    observations, boundary = set(), None
    for path in logs:
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            data = stream.read(LIMIT)
            # One bounded lookahead distinguishes true EOF from a cut physical
            # line, including when a valid-looking prefix ends exactly at LIMIT.
            # Never parse that trailing fragment if any bytes remain unread.
            if stream.read(1):
                data = data[:data.rfind(b'\n') + 1]
            text = data.decode(errors='replace')
        for line in text.split('\n'):
            match = re.search(r'ipc: (?:tipc )?([A-Za-z][A-Za-z0-9_:]{0,80}) cmd ([0-9]{1,10})\b', line)
            if match:
                observations.add((match[1], int(match[2])))
            if 'logger: accepted packet bytes=' in line:
                observations.add(('ILogger accepted packet', 0))
            match = re.fullmatch(r'FATAL: strict IPC missing command: service=([A-Za-z][A-Za-z0-9_:]{0,80}) command=(0|[1-9][0-9]{0,9})', line)
            if match and int(match[2]) <= 0xffffffff and boundary is None:
                boundary = {'kind': 'strict IPC missing command', 'service': match[1], 'command': int(match[2])}
            match = re.fullmatch(r'FATAL: strict IPC missing service: ([A-Za-z][A-Za-z0-9_:]{0,80})', line)
            if match and boundary is None:
                boundary = {'kind': 'strict IPC missing service', 'service': match[1]}
    return {'first_unsupported_boundary': boundary, 'observed_service_dispatches': sorted(observations),
            'dispatch_is_not_handler_correctness': True, 'unobserved_handlers': 'unverified',
            'actual_frames': 'unverified; no visual capture inspected', 'gameplay_verified': False}


def worker(a):
    """All expensive hashing, composition, build and launch run under the parent timer."""
    repo, store, out = a.repo, a.store, a.out
    receipt = {'schema': 1, 'unit': 'MAC-CONTROLLER-CORE-064', 'started_utc': utc(), 'stages': {}, 'gameplay_verified': False,
               'supervisor_source': digest(Path(__file__)), 'input_validation': 'pending'}
    def checkpoint():
        save(out / 'measurement.json', receipt)
    try:
        receipt['controls'] = controls(store)
        require(sys.platform == 'darwin' and os.uname().machine == 'arm64', 'native Apple Silicon macOS required')
        require(not git(repo, 'status', '--porcelain'), 'clean committed worktree required')
        receipt['head'] = git(repo, 'rev-parse', 'HEAD')
        receipt['parser_provenance'] = parser_provenance(repo, store)
        patches, receipt['dependencies'], receipt['shared_preparation'] = cumulative_patches(repo, store)
        receipt['patch_order'] = [p.name for p in patches]
        receipt['patches'] = {p.name: digest(p) for p in patches}
        inputs, gen, control = [prepare.private(a.root, p) for p in (a.inputs, a.gen, a.control_metadata)]
        for path in (inputs, gen, a.reference, control.parent):
            require(not out.is_relative_to(path) and not path.is_relative_to(out), 'output/input overlap')
        manifest, mh = prepare.validate_inputs(inputs)
        binding, ch = prepare.validate_control(control, manifest, mh)
        generated = prepare.generated_evidence(gen, manifest)
        receipt['identity'] = {'manifest_sha256': mh, 'control_sha256': ch, 'generated': generated, 'wonder_pin': prepare.PIN}
        source = out / 'source'
        prepare.prepare_source(a.reference, source, patches)
        (source / 'runtime/src/astral_control_context.h').write_text(prepare.control_header(binding, ch))
        receipt['source'] = prepare.source_fingerprint(source)
        checkpoint()
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'SDKROOT', 'DEVELOPER_DIR')}
        env.update(CC='clang', CXX='clang++', PYTHONDONTWRITEBYTECODE='1')
        def stage(name, argv, seconds=1200, **kwargs):
            receipt['active_stage'] = name
            checkpoint()
            value = run_stage(list(map(str, argv)), out / (name + '.log'), seconds, env=env, **kwargs)
            receipt['stages'][name] = value
            checkpoint()
            return value
        build = out / 'build'
        value = stage('configure', [a.cmake, '-S', source, '-B', build, '-G', 'Ninja', '-DNX_GAME=astral',
            '-DNX_GEN_DIR=' + str(gen), '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
            '-DCMAKE_MAKE_PROGRAM=' + str(a.ninja), '-DCMAKE_PREFIX_PATH=' + str(a.prefix),
            '-DNX_VULKAN_INCLUDE=' + str(a.vulkan_include)])
        require(value['exit_code'] == 0 and not value['timeout'] and not value['output_limit'], 'configure blocked')
        commands = read(build / 'compile_commands.json')
        check_flags(commands, gen)
        receipt['compile_commands'] = digest(build / 'compile_commands.json')
        receipt['translation_units'] = len(commands)
        value = stage('build', [a.cmake, '--build', build, '--parallel', str(a.jobs), '--target', 'astral'])
        require(value['exit_code'] == 0 and not value['timeout'] and not value['output_limit'], 'build blocked')
        receipt['objects'] = object_identities(commands, build)
        executable = build / 'astral'
        receipt['executable'] = digest(executable)
        require(controls(store) == receipt['controls'], 'controls changed before launch')
        _, dependencies, preparation = cumulative_patches(repo, store)
        require(dependencies == receipt['dependencies'] and preparation == receipt['shared_preparation'] and
                parser_provenance(repo, store) == receipt['parser_provenance'], 'review/preparation identity drift')
        require(prepare.source_fingerprint(source) == receipt['source'], 'prepared source drift')
        manifest2, mh2 = prepare.validate_inputs(inputs)
        require(mh2 == mh and prepare.generated_evidence(gen, manifest2) == generated and
                prepare.validate_control(control, manifest2, mh2)[1] == ch, 'private input drift')
        require({p.name: digest(p) for p in patches} == receipt['patches'], 'patch drift')
        env.update(NX_TRACE='1', NX_DATA_ROOT=str(inputs), NX_LOG=str(out / 'guest-trace.log'))
        stage('startup', [executable], seconds=60, cwd=out)
        require(digest(executable) == receipt['executable'] and
                object_identities(commands, build) == receipt['objects'], 'post-run build drift')
        receipt['post_run_source_unchanged'] = prepare.source_fingerprint(source) == receipt['source']
        manifest3, mh3 = prepare.validate_inputs(inputs)
        receipt['post_run_inputs_unchanged'] = (mh3 == mh and prepare.generated_evidence(gen, manifest3) == generated)
        require(receipt['post_run_source_unchanged'] and receipt['post_run_inputs_unchanged'], 'post-run identity drift')
        receipt.update(safe_observations([out / 'guest-trace.log', out / 'startup.log']))
        require((out / 'guest-trace.log').is_file() and (out / 'guest-trace.log').stat().st_size > 0, 'runtime trace missing')
        require(receipt['first_unsupported_boundary'] is not None, 'unsupported boundary unverified; inspect private evidence')
        receipt['input_validation'] = 'verified before and after launch'
        receipt['runtime_measurement'] = 'measured; platform acceptance remains partial/blocked'
    except Exception as exc:
        # Exception messages can contain private guest content: keep only the type.
        receipt['blocked'] = type(exc).__name__
    finally:
        receipt['finished_utc'] = utc()
        receipt['retained_private_files'] = {str(p.relative_to(out)): digest(p) for p in out.rglob('*')
            if p.is_file() and not p.is_symlink() and '.git' not in p.parts and p.name not in ('measurement.json', 'supervisor.log', 'supervisor.json')}
        receipt['finished_utc'] = utc()
        checkpoint()
    return 1 if receipt.get('blocked') else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'repo', 'store', 'reference', 'inputs', 'gen', 'control-metadata', 'out', 'cmake', 'ninja', 'prefix', 'vulkan-include'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=2)
    parser.add_argument('--seconds', type=float, default=1500)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    a = parser.parse_args()
    try:
        require(10 < a.seconds <= 1500, 'total budget must be <=25 minutes')
        for key, value in vars(a).items():
            if isinstance(value, Path):
                require(value.is_absolute(), 'absolute paths required')
                setattr(a, key, Path(os.path.abspath(value)))
        require(a.repo == ROOT and a.store == a.root / '.local/orchestrate/2026-10-18-afternoon', 'wrong repository/store')
        controls(a.store)
        prepare.private(a.repo, a.out)
        if a.worker:
            require(os.environ.get('SERVICE_BATCH_SUPERVISOR_PID') == str(os.getppid()),
                    'internal worker requires its owning supervisor')
            return worker(a)
        require(not a.out.exists(), 'fresh output required')
        a.out.mkdir(parents=True, mode=0o700)
        os.umask(0o077)
        result = run_stage([sys.executable, str(Path(__file__).absolute()), *sys.argv[1:], '--worker'],
                           a.out / 'supervisor.log', a.seconds - 10,
                           env=dict(os.environ, SERVICE_BATCH_SUPERVISOR_PID=str(os.getpid())))
        print(json.dumps({'receipt': str(a.out / 'measurement.json'), 'supervisor': str(a.out / 'supervisor.json'),
                          'exit_code': result['exit_code'], 'timeout': result['timeout'], 'gameplay_verified': False}))
        return int(result['timeout'] or result['output_limit'] or result['exit_code'] != 0)
    except Exception as exc:
        parser.exit(1, 'service batch refused: ' + type(exc).__name__ + '\n')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    sys.exit(main())
