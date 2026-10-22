#!/usr/bin/env python3
"""Private Mac staging and bounded Windows x64 native Astral build/launch.

No network, authentication, provisioning, input transfer or dependency installers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
import zipfile

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
UNIT = 'WINDOWS-NATIVE-025'
CUMULATIVE_UNIT = 'WINDOWS-CUMULATIVE-047'

DEFAULT_PROFILE = 'windows-native-v1'
CUMULATIVE_PROFILE = 'windows-cumulative-v1'
PROFILES = {
    DEFAULT_PROFILE: ('apple-memory.patch', 'astral-bootstrap.patch', 'windows-native.patch'),
    CUMULATIVE_PROFILE: ('apple-memory.patch', 'astral-bootstrap.patch',
        'astral-control-import.patch', 'astral-sqshl.patch', 'astral-notifications.patch',
        'astral-apm.patch', 'astral-audio.patch', 'astral-ipc-buffer.patch',
        'astral-hid.patch', 'astral-applet.patch', 'windows-native.patch'),
}
# Frozen after independent HID045 and AM044 passes and landing on main.
# A successor composition requires a new independently reviewed profile identity.
CUMULATIVE_HASHES = {
    'apple-memory.patch': 'a3d5225648bb88cae4dfa9647950745ac3f3de742c39fafe5c24387b2e741104',
    'astral-bootstrap.patch': '05f84f0025cc7074f157232e066288fae8f8b5c9ada535820cf2c5a2adff2f7c',
    'astral-control-import.patch': '106c66596d6c3f52a25bc222cf367ed4a7b561ce4f28095098bdcf776c58a63f',
    'astral-sqshl.patch': 'e0e90c230e2a4c50eb2885a7d1298b24020158c67360303e2e36660fd44e4035',
    'astral-notifications.patch': 'bb7e30290e0058bf4754e4f0c2e4f9f96ae955f564fb052c858c4ab9bc29fcea',
    'astral-apm.patch': '670ac4698ee7333b99ce3a5bc990be2f005359ea6076f45f69c56af3a1df9744',
    'astral-audio.patch': '19b27662567bdb1ef10f51e661e0c69798ae2b19bcdf81c96d76f1add2fcc121',
    'astral-ipc-buffer.patch': '6818e4f6d1aebc2c242601a7ec0736eb95062d7e53c6895f49c0ebc76d8e5808',
    'astral-hid.patch': '8a1b7a1b4a8b2c979a8a7bdeb1208075a2be0a09935b725841db0e152c4534fb',
    'astral-applet.patch': 'b9cda5617da673c458fba6f36c9480d52cca2ab6cd9a9260e60b8ebd01f527ed',
    'windows-native.patch': 'a10a948a55ddfdeb558d44fde0a6c68e69e5ea09c300b0d1ff2cde1389fb8b2c',
}


def no_symlinks(path):
    path = Path(path).absolute()
    require(all(not p.is_symlink() and not getattr(p, 'is_junction', lambda: False)()
                for p in (path, *path.parents)), 'symbolic path refused')
    return path


def profile_patches(profile, repo):
    require(profile in PROFILES, 'unknown Windows profile')
    paths = [regular(repo / 'runtime/patches' / n) for n in PROFILES[profile]]
    if profile == CUMULATIVE_PROFILE:
        require({p.name: sha(p) for p in paths} == CUMULATIVE_HASHES,
                'landed Windows patch identity mismatch')
    return paths


def validate_regeneration(receipt, generated, manifest_hash):
    require(receipt['schema'] == 1 and receipt['state'] == 'accepted' and
            receipt['pin'] == PIN and receipt['manifest_sha256'] == manifest_hash and
            receipt['patch_sha256'] == CUMULATIVE_HASHES['astral-sqshl.patch'],
            'regeneration receipt identity mismatch')
    actual = {mod + '/' + name: digest for mod, rec in generated.items()
              for name, digest in rec['files'].items()}
    require(actual == {name: rec['after'] for name, rec in receipt['files'].items()},
            'accepted regeneration hash mismatch')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def regular(path):
    path = no_symlinks(path)
    require(path.is_file() and path.stat().st_nlink == 1, 'missing or linked file: ' + str(path))
    return path


def tree(root):
    root = no_symlinks(root)
    require(root.is_dir(), 'missing directory')
    result = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'symbolic member refused')
        require(p.is_dir() or stat.S_ISREG(p.stat().st_mode), 'special member refused')
        if p.is_file():
            regular(p)
            result[p.relative_to(root).as_posix()] = {'size': p.stat().st_size, 'sha256': sha(p)}
    return result


def safe_member(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and '..' not in p.parts and
            '\\' not in name and ':' not in name and p.as_posix() == name,
            'unsafe package member')
    return p


def validate_package(root, manifest):
    profile = manifest.get('profile', DEFAULT_PROFILE)
    require(profile in PROFILES, 'unknown Windows profile')
    unit = CUMULATIVE_UNIT if profile == CUMULATIVE_PROFILE else UNIT
    require(manifest['schema'] == 1 and manifest['unit'] == unit and manifest['pin'] == PIN,
            'wrong package identity')
    require(len(manifest['revision']) == 40, 'missing source revision')
    actual = tree(root)
    actual.pop('manifest.json', None)
    require(actual == manifest['files'], 'package inventory/hash mismatch')
    require({'source/CMakeLists.txt', 'source/games/astral/game.cpp', 'gen/main/table.cpp',
             'gen/sdk/table.cpp', 'data/analysis/main.bin', 'data/analysis/sdk.bin',
             'driver/windows_native.py'} <= set(actual), 'incomplete actual guest package')
    require(any(n.startswith('gen/main/') and n.endswith('.cpp') for n in actual) and
            any(n.startswith('gen/sdk/') and n.endswith('.cpp') for n in actual), 'missing generated sources')
    for n in actual:
        safe_member(n)
        require(not any(x.lower() in ('.git', '.ssh', '.codex', '.claude') for x in PurePosixPath(n).parts)
                and not n.lower().endswith(('.keys', '.nsp', '.nca', '.p12')), 'forbidden package member')
    if profile == CUMULATIVE_PROFILE:
        require(manifest['patch_order'] == list(PROFILES[profile]) and
                manifest['patches'] == CUMULATIVE_HASHES, 'cumulative profile identity mismatch')
        require({n: sha(regular(root / 'overlays' / n)) for n in PROFILES[profile]} ==
                CUMULATIVE_HASHES, 'packaged overlay mismatch')
        require(manifest['prepared_sources'] == {n[7:]: v['sha256'] for n, v in actual.items()
                if n.startswith('source/')}, 'prepared source identity mismatch')
        generated = {n: v['sha256'] for n, v in actual.items() if n.startswith('gen/')}
        require(generated == {'gen/' + mod + '/' + n: digest
                for mod, rec in manifest['generated'].items() for n, digest in rec['files'].items()},
                'generated package identity mismatch')
        require(sha(regular(root / 'receipts/regeneration.json')) == manifest['generated_receipt_sha256'],
                'regeneration receipt hash mismatch')
        validate_regeneration(json.loads((root / 'receipts/regeneration.json').read_text()),
                              manifest['generated'], manifest['input_manifest_sha256'])
    return actual


def stage(a):
    # Import the existing validator only on Mac/Unix (it imports fcntl).
    import prepare_runtime as prep
    require(os.name != 'nt', 'stage on Mac; no input import or account work on Windows')
    repo = no_symlinks(a.repo).resolve(strict=True)
    profile = getattr(a, 'profile', DEFAULT_PROFILE)
    patches = profile_patches(profile, repo)
    for path in (a.inputs, a.gen, a.reference):
        no_symlinks(path)
    tree(a.gen)  # Reject linked/special generated inputs before the shared validator reads them.
    out = prep.private(repo, a.out)
    require(not out.exists(), 'fresh private output required')
    for path in (a.inputs, a.gen, a.reference):
        path = path.resolve(strict=True)
        require(not out.is_relative_to(path) and not path.is_relative_to(out), 'stage overlaps inputs')
    out.mkdir(parents=True, mode=0o700)
    source = out / 'prepared'
    regular(a.inputs / '.wrapper/manifest.json')
    manifest, mh = prep.validate_inputs(a.inputs.resolve(strict=True))
    control_hash = None
    if hasattr(prep, 'validate_control'):
        require(a.control_metadata is not None, 'reviewed runtime requires validated control metadata receipt')
        binding, control_hash = prep.validate_control(regular(a.control_metadata), manifest, mh)
    else:
        require(a.control_metadata is None, 'control validator unavailable in this runtime revision')
    generated = prep.generated_evidence(a.gen.resolve(strict=True), manifest)
    generated_receipt = None
    if profile == CUMULATIVE_PROFILE:
        require(getattr(a, 'generated_receipt', None) is not None, 'accepted regeneration receipt required')
        generated_receipt = regular(a.generated_receipt)
        validate_regeneration(json.loads(generated_receipt.read_text()), generated, mh)
    prep.prepare_source(a.reference.resolve(strict=True), source, patches)
    if control_hash is not None:
        (source / 'runtime/src/astral_control_context.h').write_text(prep.control_header(binding, control_hash))
    package = out / 'package'
    package.mkdir()
    fingerprint = prep.source_fingerprint(source)
    require(control_hash is None or 'runtime/src/astral_control_context.h' in fingerprint,
            'validated private control header missing from source inventory')
    for name in fingerprint:
        target = package / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(regular(source / name), target)
    for mod, rec in generated.items():
        for name in rec['files']:
            target = package / 'gen' / mod / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular(a.gen / mod / name), target)
    for mod in manifest['modules']:
        target = package / 'data/analysis' / (mod['name'] + '.bin')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prep.check_file(a.inputs, mod['flat']), target)
    (package / 'driver').mkdir()
    shutil.copyfile(Path(__file__), package / 'driver/windows_native.py')
    if profile == CUMULATIVE_PROFILE:
        (package / 'overlays').mkdir()
        for patch in patches:
            shutil.copyfile(regular(patch), package / 'overlays' / patch.name)
        (package / 'receipts').mkdir()
        shutil.copyfile(generated_receipt, package / 'receipts/regeneration.json')
    unit = CUMULATIVE_UNIT if profile == CUMULATIVE_PROFILE else UNIT
    record = {'schema': 1, 'unit': unit, 'pin': PIN, 'revision': prep.git(repo, 'rev-parse', 'HEAD'),
              'profile': profile, 'patch_order': [p.name for p in patches],
              'prepared_sources': fingerprint, 'generated': generated,
              'generated_receipt_sha256': sha(generated_receipt) if generated_receipt else None,
              'staged_utc': utc(), 'input_manifest_sha256': mh,
              'control_receipt_sha256': control_hash,
              'patches': {p.name: sha(p) for p in patches}, 'files': tree(package),
              'limitations': ['RomFS not included in startup package', 'No gameplay acceptance']}
    validate_package(package, record)
    save(package / 'manifest.json', record)
    with zipfile.ZipFile(out / 'windows-native.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(package).as_posix())
    save(out / 'transfer-request.json', {'schema': 1, 'unit': unit, 'archive': str(out / 'windows-native.zip'),
         'sha256': sha(out / 'windows-native.zip'), 'bytes': (out / 'windows-native.zip').stat().st_size,
         'destination': 'C:/acs-units/' + unit + '/package', 'manifest': str(package / 'manifest.json'),
         'members': len(record['files']) + 1, 'manifest_sha256': sha(package / 'manifest.json'),
         'member_manifest': record['files'], 'profile': profile, 'credentials_included': False,
         'input_paths': [str(a.inputs / m['flat']['path']) for m in manifest['modules']],
         'generated_path': str(a.gen.resolve()), 'prepared_source': str(source)})
    print(str(out / 'transfer-request.json'))


def run_stage(argv, log, seconds, *, env=None, cwd=None, max_bytes=32 << 20):
    """Bound a command and retain its exact arguments, result and log hash."""
    require(seconds > 0, 'stage deadline elapsed')
    rec = {'argv': list(map(str, argv)), 'started_utc': utc(), 'timeout_seconds': seconds,
           'timed_out': False, 'log_limit': False}
    start = time.monotonic()
    with log.open('wb') as f:
        p = subprocess.Popen(rec['argv'], stdout=f, stderr=subprocess.STDOUT, env=env, cwd=cwd,
                             start_new_session=(os.name != 'nt'))
        rec['pid'] = p.pid
        while p.poll() is None:
            rec['timed_out'] = time.monotonic() - start >= seconds
            rec['log_limit'] = log.stat().st_size >= max_bytes
            if rec['timed_out'] or rec['log_limit']:
                if os.name == 'nt':
                    # Only this invocation's tree. No image-name/global termination.
                    subprocess.run(['taskkill.exe', '/PID', str(p.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                else:
                    os.killpg(p.pid, signal.SIGKILL)
                break
            time.sleep(.05)
        try:
            rec['exit_code'] = p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            rec['exit_code'] = p.wait(timeout=5)
        if os.name != 'nt':
            # Reap a background child even if its direct parent exited normally.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    rec.update(finished_utc=utc(), elapsed_seconds=time.monotonic() - start,
               log_sha256=sha(log), log_bytes=log.stat().st_size)
    rec['ok'] = rec['exit_code'] == 0 and not rec['timed_out'] and not rec['log_limit']
    return rec


def pe_identity(path):
    """Reject a wrong-architecture/non-EXE artifact before guest launch."""
    with regular(path).open('rb') as f:
        dos = f.read(64)
        require(len(dos) == 64 and dos[:2] == b'MZ', 'missing PE DOS header')
        offset = struct.unpack_from('<I', dos, 60)[0]
        require(64 <= offset <= path.stat().st_size - 26, 'invalid PE header offset')
        f.seek(offset)
        header = f.read(26)
    require(header[:4] == b'PE\0\0', 'missing PE signature')
    machine, sections = struct.unpack_from('<HH', header, 4)
    characteristics = struct.unpack_from('<H', header, 22)[0]
    magic = struct.unpack_from('<H', header, 24)[0]
    require(machine == 0x8664 and magic == 0x20b and sections > 0 and
            characteristics & 2 and not characteristics & 0x2000, 'artifact is not a Windows x64 executable')
    return {'format': 'PE32+', 'machine': 'AMD64', 'sections': sections}


def discover():
    result = {n: shutil.which(n) for n in ('clang-cl', 'cl', 'cmake', 'ninja', 'python', 'git')}
    sdk = os.environ.get('VULKAN_SDK')
    candidates = ([Path(sdk)] if sdk else []) + sorted(Path('C:/VulkanSDK').glob('*'), reverse=True)
    result['vulkan_sdk'] = next((str(p) for p in candidates if (p / 'Include/vulkan/vulkan.h').is_file()), None)
    result['windows_sdk_include'] = os.environ.get('INCLUDE')
    result['vswhere'] = str(Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) /
                            'Microsoft Visual Studio/Installer/vswhere.exe')
    return result


# Native player build helpers. The older bounded package CLI below remains unchanged.
OPUS_URL = 'https://github.com/xiph/opus.git'
OPUS_PIN = 'ddbe48383984d56acd9e1ab6a090c54ca6b735a6'  # v1.5.2


def parse_environment(text):
    """cmd's `set` output can contain banner lines and drive pseudo-variables."""
    env = {}
    for line in text.splitlines():
        if '=' in line and not line.startswith('='):
            key, value = line.split('=', 1)
            env[key.upper()] = value
    return env


def developer_environment():
    """Discover VS Build Tools without requiring an interactive developer prompt."""
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / \
        'Microsoft Visual Studio/Installer/vswhere.exe'
    require(vswhere.is_file(), 'vswhere missing; install Visual Studio 2022 C++ Build Tools')
    installation = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
        text=True, timeout=30).strip()
    require(installation and '\n' not in installation, 'Visual Studio C++ tools not installed')
    bat = Path(installation) / 'Common7/Tools/VsDevCmd.bat'
    require(bat.is_file(), 'VsDevCmd.bat missing')
    # A single command line is intentional: cmd /s /c strips its outer quote pair.
    command = f'cmd.exe /d /s /c ""{bat}" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
    env = parse_environment(subprocess.check_output(command, text=True, timeout=60))
    require(env.get('INCLUDE') and env.get('LIB') and env.get('PATH'), 'VsDevCmd did not set INCLUDE/LIB/PATH')
    llvm = Path(installation) / 'VC/Tools/Llvm/x64/bin'
    cmake = Path(installation) / 'Common7/IDE/CommonExtensions/Microsoft/CMake'
    env['PATH'] = os.pathsep.join(map(str, (llvm, cmake / 'CMake/bin', cmake / 'Ninja'))) + os.pathsep + env['PATH']
    require(shutil.which('clang-cl', path=env['PATH']), 'clang-cl missing; install VS C++ Clang tools')
    return env


def available_memory():
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ('total_phys', 'avail_phys', 'total_page', 'avail_page',
                                             'total_virtual', 'avail_virtual', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    require(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)), 'GlobalMemoryStatusEx failed')
    return status.avail_phys


def is_junction(path):
    """Path.is_junction was added in Python 3.12; support Python 3.11 too."""
    try:
        return path.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    except (OSError, AttributeError):
        return False


def terminate_tree(process):
    """Only terminate the compiler tree created by this build invocation."""
    subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    process.wait(timeout=30)


def windows_regular_open(path):
    """Binary archive input without Unix-only O_NOFOLLOW/O_NONBLOCK flags.

    Refuse reparse paths and hard links, then bind the opened handle to the same
    regular file checked before and after open. Never accept a redirected path.
    """
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink() and not is_junction(part), 'symbolic archive path refused')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
            not getattr(before, 'st_reparse_tag', 0), 'archive must be a single-link regular file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    try:
        opened, after = os.fstat(fd), path.lstat()
        require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and
                not getattr(after, 'st_reparse_tag', 0) and
                os.path.samestat(before, opened) and os.path.samestat(opened, after) and
                before.st_size == opened.st_size == after.st_size,
                'archive changed while opening')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def install_windows_archive_reader():
    # Also called in every spawned worker: patching only the parent would leave
    # the Unix reader active in Windows multiprocessing's fresh interpreters.
    directory = str(Path(__file__).resolve().parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import inventory_astral_pkz as pkz
    pkz.regular_open = windows_regular_open


def extract_shader_inventory(input_root, out, jobs):
    """Reuse the shared extractor with a Windows file reader in spawned workers."""
    import concurrent.futures
    from functools import partial
    import multiprocessing
    from types import SimpleNamespace
    install_windows_archive_reader()
    import astral_shader_full_inventory as inventory
    require(1 <= jobs <= 8, 'shader jobs must be 1..8')
    original = inventory.concurrent
    # Only shadow this module's executor namespace, not the global futures API.
    inventory.concurrent = SimpleNamespace(futures=SimpleNamespace(
        ProcessPoolExecutor=partial(concurrent.futures.ProcessPoolExecutor,
            mp_context=multiprocessing.get_context('spawn'), initializer=install_windows_archive_reader),
        as_completed=concurrent.futures.as_completed))
    try:
        return inventory.extract(input_root, out, jobs=jobs)
    except inventory.Invalid as e:
        raise ValueError(str(e)) from e
    finally:
        inventory.concurrent = original


def compile_objects(commands, build, package):
    require(commands, 'empty compile graph')
    objects = []
    files = []
    for c in commands:
        cmd = c.get('command', '')
        require('NX_ASTRAL_STRICT=1' in cmd and 'ffp-contract=off' in cmd, 'strict/compiler flags missing')
        files.append(Path(c['file']).resolve())
        output = c.get('output')
        if not output:
            import re
            m = re.search(r'(?:^|\s)(?:/Fo|-o\s*)(?:"([^"]+)"|([^\s]+))', cmd)
            require(m, 'object output missing')
            output = m.group(1) or m.group(2)
        p = Path(output)
        p = p if p.is_absolute() else Path(c['directory']) / p
        require(p.resolve().is_relative_to(build.resolve()), 'object outside owned build')
        objects.append(p)
    require(any(p.is_relative_to((package / 'gen/main').resolve()) for p in files) and
            any(p.is_relative_to((package / 'gen/sdk').resolve()) for p in files) and
            any(p.is_relative_to((package / 'source/runtime').resolve()) for p in files), 'incomplete actual target')
    require(len(set(objects)) == len(objects), 'duplicate objects')
    return objects


def native(a):
    require(os.name == 'nt', 'native build must execute on Windows')
    package = no_symlinks(a.package).resolve(strict=True)
    manifest = json.loads(regular(package / 'manifest.json').read_text(encoding='utf-8'))
    before = validate_package(package, manifest)
    cumulative = manifest.get('profile') == CUMULATIVE_PROFILE
    if cumulative:
        require(1 <= a.seconds <= 1200 and 1 <= a.launch_seconds <= 30, 'cumulative build/launch bounds exceeded')
    out = no_symlinks(a.out).resolve()
    require(not out.exists() and not out.is_relative_to(package) and not package.is_relative_to(out),
            'fresh separate output required')
    require(1 <= a.jobs <= 3 and 1 <= a.launch_seconds <= 60 and 1 <= a.seconds <= 2700, 'invalid bounds')
    deadline = datetime.fromisoformat(a.deadline.replace('Z', '+00:00'))
    require(deadline.tzinfo is not None, 'UTC/offset deadline required')
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    require(remaining > 30, 'paid window deadline elapsed')
    end = time.monotonic() + min(a.seconds, remaining - 15)
    out.mkdir(parents=True)
    rec = {'schema': 1, 'unit': manifest['unit'], 'revision': manifest['revision'], 'started_utc': utc(),
           'profile': manifest.get('profile', DEFAULT_PROFILE),
           'deadline': a.deadline, 'manifest_sha256': sha(package / 'manifest.json'),
           'platform': sys.platform, 'toolchain': discover(), 'stages': {}, 'guest_executed': False,
           'gameplay_verified': False, 'presentation': 'unverified', 'input': 'unverified',
           'audio': 'unverified', 'capture': 'unverified'}
    save(out / 'receipt.json', rec)
    def run(name, argv, limit=None, **kw):
        bound = max(0, end - time.monotonic())
        r = run_stage(argv, out / (name + '.log'), min(bound, limit or bound), **kw)
        rec['stages'][name] = r
        save(out / 'receipt.json', rec)
        return r
    try:
        tools = rec['toolchain']
        require(all(tools[k] for k in ('clang-cl', 'cmake', 'ninja', 'vulkan_sdk')), 'compiler/CMake/Ninja/Vulkan SDK missing; see detection')
        rec['tool_hashes'] = {n: sha(tools[n]) for n in ('clang-cl', 'cmake', 'ninja')}
        for n in ('clang-cl', 'cmake', 'ninja'):
            require(run(n, [tools[n], '--version'], 20)['ok'], n + ' version probe failed')
        build = out / 'build'
        argv = [tools['cmake'], '-S', package / 'source', '-B', build, '-G', 'Ninja',
                '-DNX_GAME=astral', '-DNX_GEN_DIR=' + str(package / 'gen'), '-DCMAKE_BUILD_TYPE=Release',
                '-DCMAKE_C_COMPILER=' + tools['clang-cl'], '-DCMAKE_CXX_COMPILER=' + tools['clang-cl'],
                '-DCMAKE_MAKE_PROGRAM=' + tools['ninja'], '-DNX_VULKAN_SDK=' + tools['vulkan_sdk'],
                '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_CXX_COMPILER_LAUNCHER=',
                '-DCMAKE_C_COMPILER_LAUNCHER=']
        require(run('configure', argv)['ok'], 'configure failed')
        commands = json.loads((build / 'compile_commands.json').read_text())
        objects = compile_objects(commands, build, package)
        if cumulative:
            for command in commands:
                source_file = regular(Path(command['file']))
                require(source_file.is_relative_to(package), 'compile source outside package')
                name = source_file.relative_to(package).as_posix()
                require(name in before and sha(source_file) == before[name]['sha256'],
                        'compile source/package identity mismatch')
                require(not any(cache in command['command'].lower() for cache in ('ccache', 'sccache')),
                        'unreviewed compiler cache refused')
        require(not any(p.exists() for p in objects), 'object reuse refused')
        rec['compile_commands_sha256'] = sha(build / 'compile_commands.json')
        require(run('build', [tools['cmake'], '--build', build, '--parallel', str(a.jobs), '--target', 'astral'])['ok'], 'actual native build failed')
        exe = regular(build / 'astral.exe')
        rec['executable'] = {'path': str(exe), 'sha256': sha(exe), 'bytes': exe.stat().st_size,
                             'pe': pe_identity(exe)}
        rec['objects'] = {str(p.relative_to(build)): sha(regular(p)) for p in objects}
        rec['object_count'] = len(objects)
        env = dict(os.environ, NX_TRACE='1', NX_DATA_ROOT=str(package / 'data'),
                   NX_MEM_LIMIT_GB='8', NX_LOG=str(out / 'guest-trace.log'))
        rec['launch_environment'] = {k: env[k] for k in ('NX_TRACE', 'NX_DATA_ROOT', 'NX_MEM_LIMIT_GB', 'NX_LOG')}
        r = run('guest', [exe], a.launch_seconds, env=env, cwd=out)
        trace = (out / 'guest.log').read_text(encoding='utf-8', errors='replace')
        rec['guest_executed'] = 'entering nn::init::Start at ' in trace
        rec['startup_boundary'] = next((l for l in reversed(trace.splitlines()) if 'FATAL:' in l),
                                      'bounded guest launch; inspect full private trace')
        rec['guest_exit_code'] = r['exit_code']
        rec['state'] = 'guest-started' if rec['guest_executed'] else 'host-startup-blocked'
    except BaseException as e:
        rec.update(state='blocked', blocker=type(e).__name__ + ': ' + str(e))
        raise
    finally:
        rec['inputs_unchanged'] = tree(package) == dict(before, **{'manifest.json':
            {'size': (package / 'manifest.json').stat().st_size, 'sha256': rec['manifest_sha256']}})
        rec['finished_utc'] = utc()
        rec['cleanup_limitations'] = 'Windows taskkill bounds the owned tree on timeout; detached descendants after normal exit are not independently enumerated.'
        save(out / 'receipt.json', rec)
    require(rec['inputs_unchanged'], 'post-run input drift')
    require(rec['guest_executed'], 'guest entry not reached')
    print(json.dumps({'receipt': str(out / 'receipt.json'), 'state': rec['state'], 'startup_boundary': rec['startup_boundary']}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    s = sub.add_parser('stage')
    for n in ('repo', 'reference', 'inputs', 'gen', 'out'):
        s.add_argument('--' + n, type=Path, required=True)
    s.add_argument('--control-metadata', type=Path)
    s.add_argument('--profile', choices=tuple(PROFILES), default=DEFAULT_PROFILE)
    s.add_argument('--generated-receipt', type=Path)
    sub.add_parser('probe')
    x = sub.add_parser('extract-shaders')
    x.add_argument('--input', type=Path, required=True)
    x.add_argument('--out', type=Path, required=True)
    x.add_argument('--jobs', type=int, default=4)
    w = sub.add_parser('run')
    for n in ('package', 'out'):
        w.add_argument('--' + n, type=Path, required=True)
    w.add_argument('--deadline', required=True)
    w.add_argument('--seconds', type=int, default=1800)
    w.add_argument('--jobs', type=int, default=3)
    w.add_argument('--launch-seconds', type=int, default=30)
    a = p.parse_args()
    try:
        if a.mode == 'stage': stage(a)
        elif a.mode == 'probe': print(json.dumps(discover(), indent=2))
        elif a.mode == 'extract-shaders':
            require(os.name == 'nt', 'native shader extraction must execute on Windows')
            report = extract_shader_inventory(a.input, a.out, a.jobs)
            print(json.dumps({k: report[k] for k in
                ('archives', 'members', 'decoded_bytes', 'distinct_code_blocks', 'variant_batches')} |
                {'inventory': str(a.out / 'inventory.json')}))
        else: native(a)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as e:
        p.exit(1, 'windows native blocked: ' + str(e) + '\n')


if __name__ == '__main__':
    main()
