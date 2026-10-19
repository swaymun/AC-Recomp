#!/usr/bin/env python3
"""One-shot POSIX diagnostic; keys receive metadata operations only."""
import argparse
import datetime
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

# Owner-configured folder holding the personal dump and keys (never committed).
SOURCE_DIR = Path(os.environ.get('ACS_DUMP_DIR') or Path.home() / 'ACS-dumps')
EXPECTED_SIZE = 10344357116
MAX_READ = 4096


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parent_fd(path, emit=lambda event: None):
    """Walk every ancestor using pinned directory descriptors, never symlinks."""
    path = os.fspath(path)
    parts = path.split('/')
    if not path.startswith('/') or any(p in ('.', '..') for p in parts):
        raise ValueError('unsafe_path')
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError('unsafe_path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(parts[:-1]):
            emit({'stage': 'ancestor_open', 'ancestor_index': index})
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def path_metadata(path, emit):
    """Alternative path-only lstat observations, not authorization for a read."""
    try:
        parts = Path(path).parts
        if not Path(path).is_absolute() or '..' in parts or '.' in str(path).split('/'):
            raise ValueError()
        current = Path('/')
        for index, part in enumerate(parts[1:]):
            current = current / part
            emit({'stage': 'path_stat', 'ancestor_index': index})
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                emit({'status': 'unsafe_file'})
                return 2
            if index < len(parts) - 2 and not stat.S_ISDIR(info.st_mode):
                emit({'status': 'unsafe_file'})
                return 2
        emit({'metadata': {'type': 'regular' if stat.S_ISREG(info.st_mode) else 'other',
              'size': info.st_size, 'mode': oct(stat.S_IMODE(info.st_mode)),
              'uid': info.st_uid, 'gid': info.st_gid, 'device': info.st_dev,
              'flags': getattr(info, 'st_flags', None),
              'blocks': getattr(info, 'st_blocks', None)}})
        emit({'status': 'metadata_only'})
        return 0
    except (OSError, ValueError) as exc:
        emit({'status': 'metadata_failure', 'errno': getattr(exc, 'errno', None)})
        return 2


def inspect(path, read, expected_size, emit):
    stage = 'metadata'
    directory = fd = None
    try:
        emit({'stage': stage})
        directory, name = parent_fd(path, emit)
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            emit({'status': 'unsafe_file'})
            return 2
        emit({'metadata': {'type': 'regular', 'size': before.st_size,
              'mode': oct(stat.S_IMODE(before.st_mode)), 'uid': before.st_uid,
              'gid': before.st_gid, 'device': before.st_dev,
              'flags': getattr(before, 'st_flags', None),
              'blocks': getattr(before, 'st_blocks', None),
              'read_access_hint': os.access(name, os.R_OK, dir_fd=directory,
                                            follow_symlinks=False)}})
        if expected_size is not None and before.st_size != expected_size:
            emit({'status': 'size_failure'})
            return 2
        if not read:
            emit({'status': 'metadata_only'})
            return 0
        # Only the private supervisor selects read mode, never for key paths.
        if Path(path).suffix != '.nsp':
            emit({'status': 'unsafe_read_path'})
            return 2
        stage = 'open'
        emit({'stage': stage})
        started = time.monotonic()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        emit({'open_seconds': time.monotonic() - started})
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or not stat.S_ISREG(after.st_mode) or after.st_nlink != 1:
            emit({'status': 'changed_file'})
            return 2
        stage = 'read'
        emit({'stage': stage})
        started = time.monotonic()
        data = os.read(fd, MAX_READ)  # Exactly one call, never retried.
        emit({'count': len(data), 'read_seconds': time.monotonic() - started,
              'signature': 'PFS0' if data[:4] == b'PFS0' else 'other',
              'status': 'read_ok' if len(data) == min(MAX_READ, after.st_size) else 'short_read'})
        return 0 if len(data) == min(MAX_READ, after.st_size) else 2
    except (OSError, ValueError) as exc:
        emit({'status': stage + '_failure', 'errno': getattr(exc, 'errno', None)})
        return 2
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def valid_event(event):
    if not isinstance(event, dict) or not event:
        return False
    for key, value in event.items():
        if key == 'stage':
            if value not in ('metadata', 'ancestor_open', 'path_stat', 'open', 'read'):
                return False
        elif key == 'status':
            if value not in ('unsafe_file', 'size_failure', 'metadata_only', 'unsafe_read_path',
                             'changed_file', 'read_ok', 'short_read', 'metadata_failure',
                             'open_failure', 'read_failure'):
                return False
        elif key == 'signature':
            if value not in ('PFS0', 'other'):
                return False
        elif key == 'metadata':
            if not isinstance(value, dict) or not set(value) <= {'type', 'size', 'mode', 'uid', 'gid', 'device', 'flags', 'blocks', 'read_access_hint'}:
                return False
            for field, item in value.items():
                if field == 'type':
                    if item not in ('regular', 'other'):
                        return False
                elif field == 'mode':
                    if not isinstance(item, str) or len(item) > 7 or not item.startswith('0o') or any(c not in '01234567' for c in item[2:]):
                        return False
                elif item is not None and not isinstance(item, (int, bool)):
                    return False
        elif key in ('errno', 'ancestor_index', 'count'):
            if value is not None and (type(value) is not int or value < 0):
                return False
            if key == 'count' and (value is None or value > MAX_READ):
                return False
        elif key in ('open_seconds', 'read_seconds'):
            if type(value) not in (int, float) or not 0 <= value <= 10:
                return False
        else:
            return False
    return True


def supervise(argv, timeout=8.0):
    """Discard stdout/stderr. A separate bounded pipe carries safe fixed events.

    Kill only the newly created session/process group, even after leader exit.
    Descendants that deliberately escape that group are not claimed reaped.
    """
    if not 0 < timeout <= 8:
        raise ValueError('invalid_timeout')
    start = time.monotonic()
    record = {'argv': argv, 'start_utc': utc(), 'timeout_seconds': timeout,
              'stdout_stderr': 'discarded', 'events': []}
    rfd, wfd = os.pipe()
    env = dict(os.environ, OWNED_PROBE_FD=str(wfd), PYTHONDONTWRITEBYTECODE='1')
    proc = None
    buf = b''
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, pass_fds=(wfd,), env=env,
                                start_new_session=True)
        os.close(wfd)
        wfd = None
        os.set_blocking(rfd, False)
        with selectors.DefaultSelector() as sel:
            sel.register(rfd, selectors.EVENT_READ)
            while time.monotonic() - start < timeout:
                for _, _ in sel.select(min(.025, max(0, timeout - (time.monotonic() - start)))):
                    chunk = os.read(rfd, 4096)
                    buf += chunk
                    if len(buf) > 16384:
                        record['protocol_failure'] = True
                        break
                if len(buf) > 16384 or proc.poll() is not None:
                    # Drain remaining protocol bytes after exit, bounded.
                    try:
                        buf += os.read(rfd, 16385 - min(len(buf), 16385))
                    except BlockingIOError:
                        pass
                    break
        record['timed_out'] = proc.poll() is None and not record.get('protocol_failure', False)
    finally:
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                record['group_kill'] = 'sent'
            except ProcessLookupError:
                record['group_kill'] = 'already_absent'
            try:
                proc.wait(timeout=.5)
                record['leader_reaped'] = True
            except subprocess.TimeoutExpired:
                record['leader_reaped'] = False
            record['exit_code'] = proc.returncode
            record['descendant_reaping'] = 'not_observable; group kill only'
        os.close(rfd)
        if wfd is not None:
            os.close(wfd)
    # Only this tool's fixed protocol is retained. Never include malformed text.
    try:
        events = [json.loads(line) for line in buf.splitlines()]
        if len(buf) > 16384 or any(not valid_event(e) for e in events):
            raise ValueError()
        record['events'] = events
    except (ValueError, TypeError):
        record['protocol_failure'] = True
    record['elapsed_seconds'] = time.monotonic() - start
    record['end_utc'] = utc()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='one authorized diagnostic suite')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required')
    root = Path(__file__).resolve().parents[1]
    # Refuse symlinked output ancestors; no external output argument exists.
    output = root / '.local' / 'input-read-016'
    for directory in (root / '.local', output):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if directory.is_symlink() or not directory.is_dir():
            raise SystemExit('unsafe output directory')
    run = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    synthetic = run / 'synthetic.nsp'
    synthetic.write_bytes(b'PFS0' + b'local synthetic fixture' * 200)
    suite_start = time.monotonic()
    records = []
    for label, path, read, size in (
        ('synthetic', synthetic, True, synthetic.stat().st_size),
        ('production_key', SOURCE_DIR / 'prod.keys', 'path-metadata', None),
        ('title_key', SOURCE_DIR / 'title.keys', 'path-metadata', None),
        ('nsp_metadata', SOURCE_DIR / 'Astral Chain.nsp', 'path-metadata', None),
        ('nsp', SOURCE_DIR / 'Astral Chain.nsp', True, EXPECTED_SIZE),
    ):
        # Five operations at <=8.5 seconds each; no retries, <60 seconds total.
        argv = [sys.executable, str(Path(__file__).resolve()), '--child',
                str(path), 'path-metadata' if read == 'path-metadata' else ('read' if read else 'metadata'), str(size)]
        item = supervise(argv)
        item['label'] = label
        records.append(item)
        if not item.get('leader_reaped'):
            break
    receipt = {'schema': 1, 'commands': records, 'elapsed_seconds': time.monotonic() - suite_start,
               'cause': 'unknown', 'key_contents_accessed': False, 'max_nsp_read_bytes': MAX_READ}
    dest = run / 'receipt.json'
    with dest.open('x') as out:
        json.dump(receipt, out, indent=2)
    print(dest.relative_to(root))
    return 0 if len(records) == 5 and all(r['exit_code'] == 0 and not r.get('protocol_failure') for r in records) else 2


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--child':
        # Private supervisor protocol; no byte values or exception text emitted.
        out = int(os.environ['OWNED_PROBE_FD'])
        def emit(event):
            os.write(out, (json.dumps(event) + '\n').encode())
        if sys.argv[3] == 'path-metadata':
            sys.exit(path_metadata(sys.argv[2], emit))
        sys.exit(inspect(sys.argv[2], sys.argv[3] == 'read',
                         None if sys.argv[4] == 'None' else int(sys.argv[4]), emit))
    sys.exit(main())
