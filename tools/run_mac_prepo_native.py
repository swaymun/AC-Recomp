#!/usr/bin/env python3
"""Bound one trusted, non-daemonizing POSIX executable and its owned group.

Output is private evidence, not a rendering or gameplay assertion. No shell is used.
"""
import argparse
import json
import math
import hashlib
import shutil
import stat
import os
from pathlib import Path
import signal
import subprocess
import time


def process_table():
    """A failed/truncated inspection must never certify cleanup."""
    result = subprocess.run(
        ['ps', '-axo', 'pid=,ppid=,pgid=,stat='], capture_output=True,
        text=True, timeout=1, check=True)
    rows = {}
    for line in result.stdout.splitlines():
        pid, parent, group, state = line.split()
        rows[int(pid)] = (int(parent), int(group), state)
    if os.getpid() not in rows:
        raise RuntimeError('incomplete process inventory')
    return rows


# (guest, total) seconds per mode: a bounded measurement, a longer play session (cutscenes, reaching gameplay) and
# an incremental build. Every mode keeps the same owned-group supervision, cleanup and 10 s reserve.
LIMITS = {'guest': (40, 60), 'session': (600, 630), 'build': (890, 900)}


def supervise(command, directory, *, cwd=None, env=None, guest_seconds=40,
              total_seconds=60, term_grace=2, kill_grace=3, mode="guest"):
    """Run once; terminate leftover group even after the leader exits.

    Requires a trusted program which does not daemonize. Observed descendants
    escaping the group must also be absent before cleanup can be verified;
    never signal a different group.
    All waits and inspections have finite deadlines. Ten seconds are reserved for
    startup, inspections, reaping and evidence in addition to the cleanup graces.
    """
    budgets = (guest_seconds, total_seconds, term_grace, kill_grace)
    if (not all(math.isfinite(x) and x > 0 for x in budgets)
            or mode not in LIMITS
            or guest_seconds > LIMITS[mode][0]
            or total_seconds > LIMITS[mode][1]
            or sum((guest_seconds, term_grace, kill_grace, 10)) > total_seconds):
        raise ValueError('invalid supervision budgets')
    if not command:
        raise ValueError('empty command')
    directory = fresh_path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    receipt = dict(schema=1, command=list(command), mode=mode, cwd=str(cwd),
                   guest_seconds=guest_seconds,
                   total_seconds=total_seconds, pid=None, pgid=None,
                   timed_out=False, returncode=None, signal=None,
                   cleanup_verified=False, escaped_descendants=[],
                   signals=[], errors=[], inventory_timeouts=0)
    process = None
    known = set()
    escaped = set()
    inspection_ok = True
    members = set()
    alive_known = set()

    def inventory():
        # A `ps` slower than its own timeout under host load is not evidence about the owned group: retry it, at
        # most three attempts and only while the whole-run bound keeps its final reserve. Any other failure, or
        # exhausted retries, still raises and so can never certify cleanup.
        for attempt in range(3):
            try:
                return process_table()
            except subprocess.TimeoutExpired:
                receipt['inventory_timeouts'] += 1
                # Keep 4 s for the cleanup deadlines' last inspection, the final inventory and the evidence write.
                if attempt == 2 or time.monotonic() + 1 > start + total_seconds - 4:
                    raise

    def inspect():
        nonlocal inspection_ok, members, alive_known
        try:
            rows = inventory()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            inspection_ok = False
            receipt['errors'].append('process inventory unavailable: ' + type(error).__name__)
            return False
        # Closure catches descendants still attached to a known parent.
        changed = True
        while changed:
            changed = False
            for pid, (parent, group, _) in rows.items():
                if (group == process.pid or parent in known) and pid not in known:
                    known.add(pid)
                    changed = True
        escaped.update(pid for pid in known if pid in rows
                       and rows[pid][1] != process.pid)
        members = {pid for pid, (_, group, _) in rows.items()
                   if group == process.pid}
        alive_known = known.intersection(rows)
        return True

    def owned_session(pid):
        # macOS reports ESRCH from getpgid/getsid once a fast guest has exited,
        # even before it is reaped. The unreaped zombie still occupies its table
        # row, so its group identity is checked there instead. Popen raises if
        # the child's setsid() failed, so a group leader is the new session.
        try:
            return os.getpgid(pid) == pid and os.getsid(pid) == pid
        except ProcessLookupError:
            row = inventory().get(pid)
            if row is None:
                return False
            receipt['session_checked_via'] = 'process table (guest already exited)'
            return row[0] == os.getpid() and row[1] == pid and row[2].startswith('Z')

    def send(sig):
        # Only the session/group created by this invocation may be signalled.
        process.poll()
        if inspect() and members:
            try:
                os.killpg(process.pid, sig)
                receipt['signals'].append(sig.name)
            except ProcessLookupError:
                pass
            except PermissionError:
                # macOS refuses killpg when the group holds only our exited,
                # unreaped leader (it can exit between poll and inventory).
                # Reap and accept only if no member then remains.
                process.poll()
                if not (inspect() and not members):
                    receipt['errors'].append('owned group signal failed')
            except OSError:
                receipt['errors'].append('owned group signal failed')

    try:
        inventory()  # Fail closed before launching if inventory is unavailable.
        with (directory / 'stdout.log').open('xb') as out, (directory / 'stderr.log').open('xb') as err:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err, start_new_session=True)
            receipt['pid'] = receipt['pgid'] = process.pid
            known.add(process.pid)
            if not owned_session(process.pid):
                raise RuntimeError('owned session creation failed')
            guest_deadline = min(start + guest_seconds, start + total_seconds - 10 - term_grace - kill_grace)
            while process.poll() is None:
                if not inspect():
                    break
                remaining = guest_deadline - time.monotonic()
                if remaining <= 0:
                    receipt['timed_out'] = True
                    break
                time.sleep(min(0.05, remaining))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        receipt['errors'].append('launch or supervision failed')
    finally:
        if process is not None:
            # Reap an exited leader first; its zombie is not a signalable member.
            process.poll()
            # On inspection failure we still own this freshly created session.
            # Kill the owned group, but cannot certify cleanup without inventory.
            if not inspection_ok:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    receipt['signals'].append('SIGTERM')
                except ProcessLookupError:
                    pass
                except OSError:
                    receipt['errors'].append('owned group signal failed')
            else:
                send(signal.SIGTERM)
            for sig, grace in ((signal.SIGKILL, term_grace), (None, kill_grace)):
                deadline = min(time.monotonic() + grace, start + total_seconds - 2)
                while time.monotonic() < deadline:
                    process.poll()
                    if inspect() and not members:
                        break
                    time.sleep(min(0.025, max(0, deadline - time.monotonic())))
                if sig is not None:
                    if inspection_ok:
                        send(sig)
                    else:
                        try:
                            os.killpg(process.pid, sig)
                            receipt['signals'].append(sig.name)
                        except ProcessLookupError:
                            pass
                        except OSError:
                            receipt['errors'].append('owned group signal failed')
            process.poll()
            final_ok = inspect()
            receipt['returncode'] = process.returncode
            if process.returncode is not None and process.returncode < 0:
                receipt['signal'] = -process.returncode
            receipt['escaped_descendants'] = sorted(escaped)
            receipt['remaining_group_members'] = sorted(members)
            receipt['observed_owned_pids'] = sorted(known)
            receipt['remaining_observed_descendants'] = sorted(alive_known)
            receipt['cleanup_verified'] = bool(final_ok and inspection_ok and not members
                                                and not alive_known and process.returncode is not None)
        receipt['elapsed_seconds'] = time.monotonic() - start
        receipt['within_bound'] = receipt['elapsed_seconds'] <= total_seconds
        receipt['control_passed'] = bool(receipt['within_bound'] and receipt['cleanup_verified']
                                         and not receipt['errors'])
        # Completion includes the evidence write; update once more before returning.
        path = directory / 'receipt.json'
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        receipt['elapsed_seconds'] = time.monotonic() - start
        receipt['within_bound'] = receipt['elapsed_seconds'] <= total_seconds
        receipt['control_passed'] &= receipt['within_bound']
        path.write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt



def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def fresh_path(path):
    """Refuse existing leaves and every symlink ancestor, including dangling links."""
    path = Path(os.path.abspath(path))
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('symlink in destination')
    if path.exists():
        raise FileExistsError('destination must be fresh')
    return path


def copy_inputs(inputs, destination):
    """Dereference selected inputs into independent files, never links.

    Only explicit top-level input trees are copied; old output names are never
    imported. Internal links/special files fail closed. Top-level canonical input
    links may be resolved by the caller after checking their receipt identity.
    """
    destination = fresh_path(destination)
    for name, source in inputs.items():
        if name not in ('analysis', 'extract', 'spirv'):
            raise ValueError('unapproved input tree')
        source = Path(source)
        if source.absolute() != source.resolve() or destination.is_relative_to(source.resolve()):
            raise ValueError('input must be resolved and separate from output')
        if source.is_symlink() or not source.is_dir():
            raise ValueError('expected resolved input directory')
        for current, dirs, files in os.walk(source, followlinks=False):
            for item in dirs + files:
                p = Path(current) / item
                if p.is_symlink() or not (p.is_dir() or p.is_file()):
                    raise ValueError('input contains link or special file')
    destination.mkdir(parents=True)
    data = destination / 'data'
    data.mkdir()
    for name, source in inputs.items():
        shutil.copytree(source, data / name, symlinks=False)
    for name in ('user', 'frames', 'shader_misses'):
        (data / name).mkdir()
    for name in ('trace', 'cwd', 'home', 'tmp'):
        (destination / name).mkdir()
    assert_isolated(destination)
    return destination


def assert_isolated(root):
    """Every run file is an ordinary single-link file; all paths stay local."""
    root = Path(root)
    for p in (root, *root.parents):
        if p.is_symlink():
            raise ValueError('linked run ancestor')
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(current) / name
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or
                    stat.S_ISREG(st.st_mode) and st.st_nlink == 1):
                raise ValueError('run path escapes isolation')


def frozen_environment(root, loader, profile, inherited=None, dump_every=1):
    """Discard inherited NX_*, capture, debugger and loader injection settings.

    Preserve PATH only. HOME/TMPDIR and XDG caches are private; explicit NX
    settings use only fresh paths. Presence-based debug switches are omitted,
    rather than set to zero (which can still enable them).
    """
    if isinstance(dump_every, bool) or not isinstance(dump_every, int) or not 1 <= dump_every <= 600:
        raise ValueError('frame dump interval must be an integer 1..600')
    root = Path(root).absolute()
    assert_isolated(root)
    inherited = os.environ if inherited is None else inherited
    env = {'PATH': inherited.get('PATH', os.defpath),
           'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'),
           'XDG_CACHE_HOME': str(root / 'home'),
           'NX_DATA_ROOT': str(root / 'data'),
           'NX_LOG': str(root / 'trace/guest.log'),
           'NX_TRACE': '1', 'NX_NVN_REAL': '1', 'NX_DUMP_FRAMES': str(dump_every),
           'NX_DUMP_SHADER_MISSES': '1', 'NX_TRACE_PROGRAMS': '1',
           'NX_TRACE_PIPELINES': '1',
           'NX_NVN_FORMAT_PROFILE': str(Path(profile).absolute()),
           'SDL_VULKAN_LIBRARY': str(Path(loader).absolute())}
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--loader', required=True, type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--guest-seconds', type=float, default=40)
    parser.add_argument('--dump-frames', type=int, default=1,
                        help='read back every Nth presented frame (1..600; ~4.3 MB each at 1600x900)')
    parser.add_argument('--session', action='store_true',
                        help='session mode: guest up to 600 s, total up to 630 s')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    root = Path(os.path.abspath(args.run_root))
    evidence = Path(os.path.abspath(args.evidence))
    if not evidence.is_relative_to(root):
        parser.error('evidence must be inside the isolated run root')
    env = frozen_environment(root, args.loader, args.profile, dump_every=args.dump_frames)
    receipt = supervise(command, evidence, cwd=root / 'cwd', env=env,
                        guest_seconds=args.guest_seconds,
                        **(dict(mode='session', total_seconds=args.guest_seconds + 30) if args.session else {}))
    assert_isolated(root)
    print(json.dumps(receipt))
    return 0 if receipt['control_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
