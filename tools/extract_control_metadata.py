#!/usr/bin/env python3
"""Targeted verified control metadata extraction and fail-closed provenance audit.

Only the scoped native importer may open keys. This tool has no key arguments.
It verifies retained import provenance and bounds dump reads in an owned child.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
BASE = 'android/wonder/importer/'
SOURCES = ('nximport.cpp', 'nxcrypto.cpp', 'nximport_cli.cpp', 'nximport.h', 'nxcrypto.h')
UNIT_DIR = '.local/control-runtime-024/metadata'
OWNER = Path(__file__).resolve().parents[1]
MAX_SMALL = 4 << 20
WINDOWS = sys.platform == 'win32'


class Failure(Exception):
    pass


def require(ok, code):
    if not ok:
        raise Failure(code)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def is_link(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def regular(path):
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'unsafe_input_file')
    require(not any(is_link(p) for p in (path, *path.parents)), 'input_symlink')
    return s


def small(path):
    before = regular(path)
    require(before.st_size <= MAX_SMALL, 'input_too_large')
    with path.open('rb') as f:
        raw = f.read(MAX_SMALL + 1)
    after = regular(path)
    require(len(raw) <= MAX_SMALL, 'input_too_large')
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'input_changed')
    return raw


def identity(raw):
    return {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def hash_file(path):
    before = regular(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 << 20), b''):
            h.update(chunk)
    after = regular(path)
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'input_changed')
    return {'size': after.st_size, 'sha256': h.hexdigest()}


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.receipt-')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        os.chmod(tmp, 0o600)
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def terminate_tree(p):
    if WINDOWS:
        # Include owned descendants; never terminate unrelated compiler/game jobs.
        subprocess.run(['taskkill.exe', '/PID', str(p.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if p.poll() is None:
            p.kill()
    else:
        os.killpg(p.pid, signal.SIGKILL)


def child(argv, cwd, seconds, deadline, capture=False, *, env=None):
    """Each invocation owns a new process group; no raw diagnostics escape."""
    limit = min(seconds, deadline - time.monotonic())
    require(limit > 0, 'total_deadline')
    receipt = {'argv': list(map(str, argv)), 'cwd': str(cwd), 'start_utc': utc(),
               'timeout_seconds': limit, 'timed_out': False}
    start = time.monotonic()
    # Capturing is restricted to bounded Git source/hash-helper output by callers.
    with tempfile.TemporaryFile() as output:
        p = subprocess.Popen(receipt['argv'], cwd=cwd, env=env, start_new_session=not WINDOWS,
                             stdout=output if capture else subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {}))
        try:
            try:
                rc = p.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                receipt['timed_out'] = True
                terminate_tree(p)
                rc = p.wait(timeout=5)
        except BaseException:
            try:
                terminate_tree(p)
            except ProcessLookupError:
                pass
            p.wait(timeout=5)
            raise
        receipt.update(end_utc=utc(), exit_code=rc,
                       elapsed_seconds=round(time.monotonic() - start, 6))
        output.seek(0)
        data = output.read(MAX_SMALL + 1) if capture else b''
        require(len(data) <= MAX_SMALL, 'child_output_too_large')
    return receipt, data


def git(repo, args, deadline, receipts):
    record, raw = child(['git', '-C', str(repo), *args], repo, 10, deadline, True)
    receipts.append(record)
    require(record['exit_code'] == 0, 'git_failed')
    return raw


def private_output(repo, deadline, receipts):
    repo = repo.absolute()
    require(repo == OWNER, 'output_not_owning_worktree')
    root = repo / UNIT_DIR
    require(not any(is_link(p) for p in (root, *root.parents)), 'output_symlink')
    require(not git(repo, ['ls-files', '--', UNIT_DIR], deadline, receipts), 'output_tracked')
    record, _ = child(['git', '-C', str(repo), 'check-ignore', '--no-index', '-q', UNIT_DIR + '/receipt.json'],
                      repo, 10, deadline)
    receipts.append(record)
    require(record['exit_code'] == 0, 'output_not_ignored')
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def npdm_program(raw):
    require(len(raw) >= 0x80 and raw[:4] == b'META', 'npdm_header')
    offset, length = struct.unpack_from('<II', raw, 0x70)
    require(offset >= 0x80 and length >= 0x40 and offset + length <= len(raw), 'npdm_extent')
    require(raw[offset:offset + 4] == b'ACI0', 'npdm_aci0')
    program = struct.unpack_from('<Q', raw, offset + 0x10)[0]
    require(program != 0, 'npdm_program')
    return f'{program:016X}'


def verify_sources(ref, manifest, deadline, receipts):
    require(git(ref, ['rev-parse', 'HEAD'], deadline, receipts).decode().strip() == PIN,
            'reference_revision')
    require(manifest['importer']['revision'] == PIN, 'receipt_revision')
    result = {}
    for name in SOURCES:
        raw = small(ref / (BASE + name))
        require(raw == git(ref, ['show', PIN + ':' + BASE + name], deadline, receipts), 'reference_modified')
        result[name] = identity(raw)
        require(result[name]['sha256'] == manifest['importer']['sources_sha256'][name], 'source_receipt_mismatch')
    return result


def retained_inputs(import_dir, manifest):
    raw = small(import_dir / 'analysis/main.npdm')
    actual = identity(raw)
    require(actual['sha256'] == manifest['npdm']['sha256'] and
            actual['size'] == manifest['npdm']['size'], 'npdm_identity_mismatch')
    program = npdm_program(raw)
    require(program == manifest['title_id'] == manifest['npdm']['title_id'], 'program_mismatch')
    old = json.loads(small(import_dir / '.wrapper/input.json'))
    require(all(old[k] == manifest['dump'][k] for k in ('sha256', 'size')), 'dump_receipt_mismatch')
    return {'program_id': program, 'npdm': actual,
            'dump_expected': {k: manifest['dump'][k] for k in ('size', 'sha256')},
            'original_binding_limit': (manifest.get('parent') or {}).get('binding_limit')}


def audit(args):
    os.umask(0o077)
    deadline = time.monotonic() + 60
    receipts = []
    root = private_output(args.repo, deadline, receipts)
    # A new receipt directory preserves earlier partial evidence and avoids reuse.
    run = Path(tempfile.mkdtemp(prefix='audit-', dir=root))
    report = {'schema': 1, 'unit': 'CONTROL-METADATA-015', 'start_utc': utc(),
              'status': 'blocked', 'metadata_produced': False, 'application_id': None,
              'control_content_id': None, 'ratings': None, 'parental_flags': None,
              'linkage_verified': False, 'commands': receipts,
              'tool': identity(small(Path(__file__))),
              'reference_path': str(args.reference), 'import_path': str(args.import_dir)}
    atomic_json(run / 'receipt.json', report)
    try:
        manifest_raw = small(args.import_dir / '.wrapper/manifest.json')
        manifest = json.loads(manifest_raw)
        report['manifest'] = identity(manifest_raw)
        report['phase'] = 'source_provenance'
        atomic_json(run / 'receipt.json', report)
        report['sources'] = verify_sources(args.reference, manifest, deadline, receipts)
        report['inputs'] = retained_inputs(args.import_dir, manifest)
        report['phase'] = 'dump_identity'
        atomic_json(run / 'receipt.json', report)
        dump = Path(manifest['dump']['path'])
        require(dump.is_absolute() and dump.suffix.lower() == '.nsp', 'dump_path')
        require(dump not in (args.import_dir, args.reference), 'dump_path')
        # The helper has no key paths and never reads keys. All dump operations,
        # including potentially blocking open/stat, occur in the bounded child.
        record, raw = child([sys.executable, str(Path(__file__).resolve()), '--_hash-dump', str(dump)],
                            args.repo, 20, deadline, True)
        receipts.append(record)
        if record['timed_out']:
            raise Failure('dump_read_timeout')
        require(record['exit_code'] == 0, 'dump_read_failed')
        observed = json.loads(raw)
        report['inputs']['dump_observed'] = observed
        require(observed == report['inputs']['dump_expected'], 'dump_identity_mismatch')
        # Header probing cannot establish a CNMT association or emit policy.
        raise Failure('targeted_cnmt_control_producer_required')
    except Failure as e:
        report['diagnostic'] = str(e)
    except (OSError, ValueError, KeyError, TypeError, struct.error):
        report['diagnostic'] = 'invalid_or_unavailable_input'
    report['end_utc'] = utc()
    atomic_json(run / 'receipt.json', report)
    print(json.dumps({'status': 'blocked', 'diagnostic': report['diagnostic'],
                      'receipt': str(run / 'receipt.json'), 'receipt_identity': hash_file(run / 'receipt.json')}))
    return 2


def link_metadata(directory, manifest, *, layout):
    """Reparse verified native outputs; require exactly one base application pair.

    The native receipt describes encrypted content hashes, not raw metadata hashes.
    It is a producer receipt, not a cryptographic publisher signature.
    """
    try:
        from cnmt_metadata import parse_cnmt, NCM_PROGRAM, NCM_CONTROL
        from nacp_metadata import parse_nacp
    except ImportError:
        from tools.cnmt_metadata import parse_cnmt, NCM_PROGRAM, NCM_CONTROL
        from tools.nacp_metadata import parse_nacp
    native = json.loads(small(directory / 'native.json'))
    require(native['schema'] == 1 and len(native['contents']) == 3, 'ambiguous_native_contents')
    records = {}
    raw = {}
    for rec in native['contents']:
        kind = rec['type']
        require(type(kind) is int and kind in (0, 1, 2) and kind not in records,
                'ambiguous_native_contents')
        suffix = {0: 'npdm', 1: 'cnmt', 2: 'nacp'}[kind]
        require(type(rec['raw']) is str and re.fullmatch(r'[0-9]+\.' + suffix, rec['raw']),
                'unsafe_native_member')
        require(type(rec['size']) is int and rec['size'] > 0 and
                type(rec['sha256']) is str and re.fullmatch('[0-9a-f]{64}', rec['sha256']),
                'invalid_content_identity')
        raw[kind] = small(directory / rec['raw'])
        records[kind] = rec
    cnmt = parse_cnmt(raw[1], layout=layout)
    nacp = parse_nacp(raw[2])
    app = f'{cnmt.application_id:016X}'
    require(all(r['program_id'] == app for r in records.values()), 'content_program_mismatch')
    require(app == manifest['title_id'] == npdm_program(raw[0]), 'program_mismatch')
    require(identity(raw[0]) == {k: manifest['npdm'][k] for k in ('size', 'sha256')},
            'npdm_identity_mismatch')
    selected = {}
    for kind, ncm in ((0, NCM_PROGRAM), (2, NCM_CONTROL)):
        refs = [r for r in cnmt.contents if r.content_type == ncm]
        require(len(refs) == 1 and refs[0].id_offset == 0, 'ambiguous_program_control')
        ref = refs[0]
        require(ref.byte_size == records[kind]['size'] and
                ref.expected_sha256.hex() == records[kind]['sha256'], 'content_identity_mismatch')
        selected['program' if kind == 0 else 'control'] = {
            'content_id': ref.content_id.hex(), 'size': ref.byte_size,
            'sha256': ref.expected_sha256.hex()}
    return {'application_id': app, 'program_id': app, 'version': cnmt.version,
            'cnmt_layout': layout, 'contents': selected,
            'parental_flags': nacp.parental_flags, 'ratings': [r.signed for r in nacp.ratings],
            'raw': {str(k): {'path': records[k]['raw'], **identity(raw[k])} for k in records},
            'native_receipt': identity(small(directory / 'native.json'))}


def produce(args):
    """Only the native pinned reader opens the staged keys. Never capture its log."""
    os.umask(0o077)
    deadline = time.monotonic() + 600
    receipts = []
    root = private_output(args.repo, deadline, receipts)
    run = Path(tempfile.mkdtemp(prefix='producer-', dir=root))
    report = {'schema': 1, 'unit': 'CONTROL-RUNTIME-024', 'start_utc': utc(),
              'tool': identity(small(Path(__file__))),
              'status': 'blocked', 'metadata_produced': False, 'commands': receipts}
    try:
        manifest_raw = small(args.import_dir / '.wrapper/manifest.json')
        manifest = json.loads(manifest_raw)
        report['sources'] = verify_sources(args.reference, manifest, deadline, receipts)
        report['inputs'] = retained_inputs(args.import_dir, manifest)
        report['manifest'] = identity(manifest_raw)
        stage = args.source_stage.absolute()
        require(not any(is_link(p) for p in (stage, *stage.parents)), 'stage_symlink')
        require(WINDOWS or stage.stat().st_mode & 0o077 == 0, 'stage_permissions')
        receipt_raw = small(stage / 'receipt.json')
        staged = json.loads(receipt_raw)['Astral Chain.nsp']
        dump = stage / 'Astral Chain.nsp'
        observed = hash_file(dump)
        require(observed == {'size': staged['bytes'], 'sha256': staged['sha256']} ==
                report['inputs']['dump_expected'], 'dump_identity_mismatch')
        report['inputs']['dump_observed'] = observed
        report['staging_receipt'] = identity(receipt_raw)
        shutil.copyfile(stage / 'receipt.json', run / 'staging-receipt.json')
        shutil.copyfile(args.import_dir / '.wrapper/manifest.json', run / 'original-manifest.json')
        source = run / 'native-source'
        directory = source / BASE
        directory.mkdir(parents=True)
        for name in SOURCES:
            (directory / name).write_bytes(small(args.reference / (BASE + name)))
        for command in (['git', 'init', '-q', str(source)],
                        ['git', '-c', 'core.autocrlf=false', '-C', str(source), 'apply',
                         str(OWNER / 'runtime/patches/astral-control-import.patch')]):
            rec, _ = child(command, args.repo, 90, deadline)
            receipts.append(rec)
            require(rec['exit_code'] == 0, 'native_preparation_failed')
        tool = run / ('nxcontrol.exe' if WINDOWS else 'nxcontrol')
        import import_owned_dump as owned
        try:
            command = owned.native_compile_command(source, tool, control=True)
        except owned.ImportFailure:
            raise Failure('native_preparation_failed') from None
        env = None
        if WINDOWS:
            import windows_native
            env = windows_native.developer_environment()
        else:
            command[0] = 'c++'
        rec, _ = child(command, args.repo, 90, deadline, env=env)
        receipts.append(rec)
        require(rec['exit_code'] == 0, 'native_preparation_failed')
        report['native_binary'] = hash_file(tool)
        report['native_sources'] = {name: identity(small(directory / name)) for name in SOURCES}
        for name in ('prod.keys', 'title.keys'):
            # Metadata only: Python never opens, reads, hashes or copies keys.
            info = regular(stage / name)
            require(info.st_size > 0 and (WINDOWS or info.st_mode & 0o077 == 0), 'key_permissions')
        rec, _ = child([tool, '--out', run, '--control-metadata',
                        stage / 'prod.keys', stage / 'title.keys', dump], args.repo, 360, deadline)
        receipts.append(rec)
        require(rec['exit_code'] == 0, 'native_metadata_failed')
        require(hash_file(dump) == observed, 'dump_changed')
        report['binding'] = link_metadata(run, manifest, layout=args.cnmt_layout)
        report.update(status='produced', metadata_produced=True, linkage_verified=True)
        report['producer_patch'] = identity(small(OWNER / 'runtime/patches/astral-control-import.patch'))
    except (Failure, OSError, ValueError, KeyError, TypeError, struct.error) as e:
        report['diagnostic'] = str(e) if isinstance(e, Failure) else 'invalid_or_unavailable_metadata'
    report['end_utc'] = utc()
    atomic_json(run / 'receipt.json', report)
    print(json.dumps({'status': report['status'], 'receipt': str(run / 'receipt.json'),
                      'diagnostic': report.get('diagnostic')}))
    return 0 if report['metadata_produced'] else 2


def total_timeout(_signum, _frame):
    raise Failure('total_deadline')


def main():
    # Private internal helper: only used for a non-key NSP named in the receipt.
    if len(sys.argv) == 3 and sys.argv[1] == '--_hash-dump':
        try:
            p = Path(sys.argv[2])
            require(p.suffix.lower() == '.nsp', 'only_nsp')
            print(json.dumps(hash_file(p)))
            return 0
        except (Failure, OSError):
            return 2
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-stage', type=Path)
    p.add_argument('--cnmt-layout', choices=('application-1.0.0-14.1.2-size48', 'application-15.0.0-16.1.0-size40-attributes0'))
    p.add_argument('--repo', type=Path, default=Path.cwd())
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--import-dir', type=Path, required=True)
    args = p.parse_args()
    if not WINDOWS:
        signal.signal(signal.SIGALRM, total_timeout)
        signal.setitimer(signal.ITIMER_REAL, 600 if args.source_stage else 60)
    try:
        if args.source_stage:
            require(args.cnmt_layout is not None, 'explicit_cnmt_layout_required')
            return produce(args)
        return audit(args)
    except (Failure, OSError, ValueError):
        print('{"status":"blocked","diagnostic":"audit_preflight_failed"}')
        return 2
    finally:
        if not WINDOWS:
            signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == '__main__':
    sys.exit(main())
