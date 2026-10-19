#!/usr/bin/env python3
"""Prepare a private, strict Astral runtime; no downloads, credentials or regeneration.

Existing verified main/sdk lifting is reused. All derived evidence stays ignored.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import struct
import sys

import import_owned_dump as inventory
import extract_control_metadata as control

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
TITLE = '01007300020FA000'
ROOT = Path(__file__).resolve().parents[1]
IOS_DEFAULT = 'ios-simulator-high-v1'
IOS_CUMULATIVE = 'ios-simulator-cumulative-v1'
IOS_PROFILES = {
    IOS_DEFAULT: ('apple-memory.patch', 'astral-bootstrap.patch',
                  'ios-runtime.patch', 'ios-nvn-compile.patch'),
    IOS_CUMULATIVE: ('apple-memory.patch', 'astral-bootstrap.patch',
                     'astral-control-import.patch', 'astral-audio.patch',
                     'astral-notifications.patch', 'astral-apm.patch',
                     'ios-runtime.patch', 'ios-nvn-compile.patch'),
}


# Exact landed contents at main 2d27411abb2bb8d8b0e489c76893fd5e6352d42e.
# Updating this profile requires a new independently reviewed composition.
IOS_CUMULATIVE_HASHES = {
    'apple-memory.patch': 'a3d5225648bb88cae4dfa9647950745ac3f3de742c39fafe5c24387b2e741104',
    'astral-bootstrap.patch': '05f84f0025cc7074f157232e066288fae8f8b5c9ada535820cf2c5a2adff2f7c',
    'astral-control-import.patch': '106c66596d6c3f52a25bc222cf367ed4a7b561ce4f28095098bdcf776c58a63f',
    'astral-audio.patch': '19b27662567bdb1ef10f51e661e0c69798ae2b19bcdf81c96d76f1add2fcc121',
    'astral-notifications.patch': 'bb7e30290e0058bf4754e4f0c2e4f9f96ae955f564fb052c858c4ab9bc29fcea',
    'astral-apm.patch': '670ac4698ee7333b99ce3a5bc990be2f005359ea6076f45f69c56af3a1df9744',
    'ios-runtime.patch': '4c5ad6a4168c8ea9f6f762ceb18459d2d4ce65e212cbaaf122980e44ffb5d834',
    'ios-nvn-compile.patch': 'aa73ab4a780aff5a20d96a65d7b2dea22d1e478836a316427c4790296cab165e',
}


def ios_patches(profile, root=ROOT):
    require(profile in IOS_PROFILES, 'unknown simulator profile')
    paths = [root / 'runtime/patches' / n for n in IOS_PROFILES[profile]]
    for path in paths:
        require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
                'unsafe or missing simulator patch')
        if profile == IOS_CUMULATIVE:
            require(sha(path) == IOS_CUMULATIVE_HASHES[path.name], 'landed simulator patch identity mismatch')
    return paths



def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.PIPE, timeout=30).decode().strip()


def private(repo, path):
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(repo / '.local'), 'path must be inside repository .local')
    for p in (path, *path.parents):
        require(not p.is_symlink(), 'symlink private path refused')
        if p == repo:
            break
    require(not git(repo, 'ls-files', '--', str(path)), 'tracked private input/output refused')
    require(subprocess.run(['git', '-C', str(repo), 'check-ignore', '-q', str(path)], timeout=10).returncode == 0,
            'private path must be gitignored')
    return path


def check_file(root, rec):
    p = root / rec['path']
    require(p.resolve().is_relative_to(root), 'unsafe manifest member')
    require(all(not q.is_symlink() for q in (p, *p.parents) if q.is_relative_to(root)),
            'unsafe manifest symlink')
    require(p.is_file() and p.stat().st_nlink == 1, 'missing or linked manifest file')
    require(p.stat().st_size == rec['size'] and sha(p) == rec['sha256'], 'manifest hash/size mismatch')
    return p


def patched_source(patch_path, name):
    """Extract a full-context shipped source for offline executable fixtures.

    Reject partial hunks rather than silently testing a source fragment.
    """
    marker = f'diff --git a/{name} b/{name}\n'
    sections = patch_path.read_text().split(marker)
    require(len(sections) == 2, 'missing or duplicate source section')
    section = sections[1].split('diff --git ', 1)[0]
    lines = section.splitlines(keepends=True)
    hunks = [i for i, line in enumerate(lines) if line.startswith('@@')]
    require(len(hunks) == 1, 'fixture requires one full-context hunk')
    match = re.fullmatch(r'@@ -1,(\d+) \+1,(\d+) @@[^\n]*\n', lines[hunks[0]])
    require(match is not None, 'fixture requires full source from line one')
    body = lines[hunks[0] + 1:]
    require(all(line.startswith((' ', '+', '-')) or line == '\n' for line in body),
            'invalid fixture patch body')
    old_count = sum(line == '\n' or line.startswith((' ', '-')) for line in body)
    output = ''.join('\n' if line == '\n' else line[1:] for line in body
                     if line == '\n' or line.startswith((' ', '+')))
    require((old_count, len(output.splitlines())) == tuple(map(int, match.groups())),
            'incomplete fixture source')
    return output


def boot_metadata(raw, flat, mod):
    mod0 = struct.unpack_from('<I', flat, 4)[0]
    require(flat[mod0:mod0 + 4] == b'MOD0', 'missing MOD0')
    start, end = [mod0 + struct.unpack_from('<i', flat, mod0 + x)[0] for x in (8, 12)]
    require(len(flat) <= start <= end <= min(0x10000000, len(flat) + mod['bss_size'] + 4096),
            'invalid MOD0 BSS')
    bss = [start, end - start]
    dynamic = mod0 + struct.unpack_from('<i', flat, mod0 + 4)[0]
    tags = {}
    for offset in range(dynamic, len(flat) - 15, 16):
        tag, value = struct.unpack_from('<qQ', flat, offset)
        if tag == 0:
            break
        tags[tag] = value
    else:
        raise ValueError('unterminated boot dynamic table')
    require(tags.get(12) == 0x30, 'boot requires DT_INIT at 0x30')
    symrel, symsize = struct.unpack_from('<II', raw, 0x98)
    symbols = mod['segments'][1]['memory_offset'] + symrel
    exports = {}
    for offset in range(symbols, symbols + symsize, 24):
        name, info, _, section, value, size = struct.unpack_from('<IBBHQQ', flat, offset)
        if name and section:
            end = flat.index(b'\0', tags[5] + name, tags[5] + tags[10])
            exports[flat[tags[5] + name:end].decode()] = value
    wanted = 'nnMain' if mod['name'] == 'main' else '_ZN2nn4init5StartEmmPFvvES2_'
    require(wanted in exports and exports[wanted] < mod['segments'][0]['size'],
            'required boot export missing')
    return {'dt_init': tags[12], 'entry_symbol': wanted, 'entry_offset': exports[wanted],
                    'init_array_size': tags.get(27, 0), 'mod0_bss': bss}


def validate_inputs(root):
    mpath = root / '.wrapper/manifest.json'
    require(not mpath.is_symlink() and mpath.stat().st_nlink == 1, 'linked manifest refused')
    m = json.loads(mpath.read_text())
    require(m['schema'] == 1 and m['title_id'] == TITLE and m['importer']['revision'] == PIN,
            'wrong input title/schema/importer revision')
    require([x['name'] for x in m['modules']] == ['main', 'sdk'], 'unsupported module inventory')
    require({p.name for p in (root / 'exefs').iterdir()} == {'main', 'sdk'}, 'extra retained module')
    for mod in m['modules']:
        raw = check_file(root, mod['nso']).read_bytes()
        flat = check_file(root, mod['flat']).read_bytes()
        actual = inventory.nso_inventory(raw, flat, mod['name'])
        require(all(mod[k] == v for k, v in actual.items()), 'NSO metadata/build ID/import mismatch')
        require(mod['imports_unavailable_reason'] is None, 'imports unavailable')
        mod['_boot'] = boot_metadata(raw, flat, mod)
        mod['_mod0_bss'] = mod['_boot']['mod0_bss']
        require(max(x['memory_offset'] + x['size'] for x in mod['segments']) + mod['bss_size'] < 0x10000000,
                'module exceeds 256 MiB slot')
    npdm = m['npdm']
    npdm_raw = check_file(root, npdm).read_bytes()
    actual = inventory.npdm_inventory(npdm_raw)
    require(npdm_raw[0xe:0x10] == bytes([44, 0]), 'unsupported main-thread priority/core')
    require(all(npdm[k] == v for k, v in actual.items()), 'NPDM mismatch')
    require(actual == {'title_id': TITLE, 'system_resource_size': 0, 'main_thread_stack_size': 1048576},
            'adapter metadata differs from NPDM')
    return m, sha(mpath)


def generated_evidence(gen, manifest):
    result = {}
    for n, mod in enumerate(manifest['modules']):
        d = gen / mod['name']
        hdr = (d / 'funcs.h').read_text()
        require(f'#define NXB (NX_BASE + 0x{n * 0x10000000:x}ull)' in hdr, 'wrong generated base')
        table = (d / 'table.cpp').read_text()
        seg = mod['segments']
        expected = [v for x in seg for v in (x['memory_offset'], x['size'])]
        expected += mod['_mod0_bss']
        match = re.search(r'"' + mod['name'] + r'", NX_BASE[^\n]*\n\s*([^\n]+)', table)
        require(match and [int(x, 16) for x in re.findall(r'0x([0-9a-f]+)', match[1])] == expected,
                'generated module extent mismatch')
        report = (d / 'report.txt').read_text()
        require(re.match(r'functions \d+, handled \d+, unhandled \d+', report), 'missing lift report')
        files = sorted(d.glob('*'))
        require(all(p.is_file() and not p.is_symlink() for p in files), 'unsafe generated files')
        result[mod['name']] = {'report': report, 'files': {p.name: sha(p) for p in files}}
    return result


def source_fingerprint(source):
    # Includes untracked adapter and catches edits to both patched and untouched tracked files.
    paths = git(source, 'ls-files').splitlines()
    paths += git(source, 'ls-files', '--others', '--exclude-standard').splitlines()
    return {p: sha(source / p) for p in paths}


def prepare_source(reference, source, patches, pin=PIN):
    require(git(reference, 'rev-parse', 'HEAD') == pin, 'wrong reference pin')
    require(not git(reference, 'status', '--porcelain'), 'dirty reference refused')
    require(not source.exists(), 'source already exists without a preparation receipt')
    subprocess.run(['git', 'clone', '--no-hardlinks', '--no-checkout', str(reference), str(source)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', pin], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    for patch in patches:  # Apple memory MUST precede bootstrap, including on Linux.
        subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], check=True, timeout=30)
        subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True, timeout=30)
    return source_fingerprint(source)


def run_logged(command, log, cwd=None, env=None, timeout=600):
    with log.open('w') as f:
        f.write(json.dumps({'argv': [str(x) for x in command], 'cwd': str(cwd)}) + '\n')
        f.flush()
        child = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                                 stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=10)
            raise ValueError(f'child timeout {timeout}; see {log}')
    require(code == 0, f'child exit {code}; see {log}')


def validate_reviewed_generated(reviewed, generated, manifest_hash):
    require(reviewed['identity']['pin'] == PIN and
            reviewed['identity']['manifest_sha256'] == manifest_hash and
            reviewed['identity']['generated'] == generated, 'reviewed generated identity mismatch')


def validate_ios_identity(identity, root=ROOT):
    require(identity['pin'] == PIN and identity['profile'] in IOS_PROFILES,
            'wrong simulator runtime identity')
    paths = ios_patches(identity['profile'], root)
    if identity['profile'] == IOS_CUMULATIVE:
        require(identity.get('patch_order') == [p.name for p in paths], 'simulator patch order mismatch')
    require(identity['patches'] == {p.name: sha(p) for p in paths},
            'simulator runtime patch identity mismatch')
    require(identity['host'] == {p.name: sha(p) for p in (root / 'ports/ios').iterdir() if p.is_file()},
            'simulator UIKit adapter identity mismatch')


def validate_ios_commands(commands, gen):
    require(commands, 'empty simulator build')
    require(any(str(gen / 'main') in x['file'] for x in commands) and
            any(str(gen / 'sdk') in x['file'] for x in commands), 'missing generated simulator TUs')
    for item in commands:
        cmd = item['command']
        require('-DNX_APPLE_HIGH_MEMORY=1' in cmd and '-DNX_ASTRAL_STRICT=1' in cmd,
                'mixed simulator memory/strict profiles')
        require('iPhoneSimulator' in cmd or 'iphonesimulator' in cmd, 'non-simulator compile refused')
        require(re.search(r'-arch\s+arm64(?:\s|$)', cmd), 'non-arm64 simulator compile refused')
        require('-mios-simulator-version-min=26.0' in cmd, 'wrong simulator minimum target')
        require('platform_mac.cpp' not in item['file'], 'desktop platform refused')
    require(any(x['file'].endswith('platform_ios.mm') for x in commands), 'missing simulator adapter')


def simulator_build_identity(out):
    return {'pin': PIN, 'executable_sha256': sha(out / 'build/astral.app/astral'),
            'prepared_sha256': sha(out / 'prepared.json'),
            'compile_commands_sha256': sha(out / 'build/compile_commands.json')}


def validate_simulator_build(out):
    require(json.loads((out / 'built.json').read_text()) == simulator_build_identity(out),
            'stale or mismatched simulator build identity')


def simulator_app_inventory(text, path):
    # simctl emits an OpenStep text plist, unsupported by Python plistlib.
    # Keep the exact response privately and use the platform's bounded parser.
    with path.open('x') as stream:
        stream.write(text)
    result = subprocess.run(['plutil', '-convert', 'json', '-o', '-', str(path)],
                            capture_output=True, text=True, timeout=10, check=True)
    apps = json.loads(result.stdout)
    require(isinstance(apps, dict), 'invalid simulator app inventory')
    return apps


def validate_simulator_library(path):
    # Mach-O architecture alone cannot distinguish macOS/device/simulator arm64.
    require(path.is_file() and not path.is_symlink(), 'unsafe simulator library')
    result = subprocess.run(['xcrun', 'vtool', '-show-build', str(path)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    require(result.returncode == 0, 'uninspectable simulator library')
    platforms = re.findall(r'^\s*platform\s+(\S+)', result.stdout, re.M)
    require(platforms and set(platforms) == {'IOSSIMULATOR'}, 'wrong-platform library refused')
    return {'sha256': sha(path), 'build_version': result.stdout}


def jobs(requested):
    require(1 <= requested <= 3, 'jobs must be 1..3')
    # Conservative 2 GiB per compiler; never exceed three even on a large worker.
    if sys.platform == 'darwin':
        memory = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], timeout=10))
    else:
        memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    return max(1, min(requested, os.cpu_count() or 1, memory // (2 << 30)))


def validate_control(receipt, manifest, manifest_hash):
    raw = control.small(receipt)
    report = json.loads(raw)
    require(report['schema'] == 1 and report['status'] == 'produced' and
            report['metadata_produced'] is True and report['linkage_verified'] is True,
            'control metadata not produced')
    require(report['manifest']['sha256'] == manifest_hash, 'control import manifest mismatch')
    require(report['inputs']['dump_observed'] ==
            {k: manifest['dump'][k] for k in ('size', 'sha256')}, 'control dump identity mismatch')
    actual = control.link_metadata(receipt.parent, manifest, layout=report['binding']['cnmt_layout'])
    require(actual == report['binding'], 'control metadata binding drift')
    require(report['producer_patch'] == control.identity(control.small(
        ROOT / 'runtime/patches/astral-control-import.patch')), 'control producer patch drift')
    return actual, hashlib.sha256(raw).hexdigest()


def control_header(binding, receipt_hash):
    require(re.fullmatch('[0-9a-f]{64}', receipt_hash) is not None, 'invalid control receipt identity')
    app, program = (int(binding[k], 16) for k in ('application_id', 'program_id'))
    require(app and program == app and binding['parental_flags'] in (0, 1), 'unsupported control policy')
    ratings = binding['ratings']
    require(len(ratings) == 32 and all(type(v) is int and -128 <= v <= 127 for v in ratings),
            'invalid control ratings')
    # Private generated input: never shipped in Git or read from a guest buffer.
    return ('#pragma once\n#define NX_CONTROL_CONTEXT {' +
            f'0x{app:016x}ull,0x{program:016x}ull,{binding["parental_flags"]}u,{{' +
            ','.join(map(str, ratings)) + '},"' + receipt_hash + '"}\n')


def execute(a):
    require(not getattr(a, 'ios_profile', None) or getattr(a, 'ios_simulator', False),
            'simulator profile requires --ios-simulator')
    repo = a.repo.resolve()
    inputs, gen, out = [private(repo, p) for p in (a.inputs, a.gen, a.out)]
    require(not out.is_relative_to(inputs) and not out.is_relative_to(gen), 'output overlaps inputs')
    require(not inputs.is_relative_to(out) and not gen.is_relative_to(out), 'output contains inputs')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (out / 'prepare.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        m, manifest_hash = validate_inputs(inputs)
        require(a.control_metadata is not None, 'validated control metadata receipt required')
        control, control_hash = validate_control(private(repo, a.control_metadata), m, manifest_hash)
        generated = generated_evidence(gen, m)
        ios = getattr(a, 'ios_simulator', False)
        if ios:
            require(sys.platform == 'darwin' and 1 <= a.jobs <= 2, 'simulator requires Mac and max2compilejobs')
            require(a.generated_receipt is not None, 'reviewed generated receipt required')
            reviewed = json.loads(private(repo, a.generated_receipt).read_text())
            validate_reviewed_generated(reviewed, generated, manifest_hash)
        patches = [ROOT / 'runtime/patches/apple-memory.patch', ROOT / 'runtime/patches/astral-bootstrap.patch']
        if ios:
            patches = ios_patches(getattr(a, 'ios_profile', None) or IOS_DEFAULT)
        identity = {'control_receipt_sha256': control_hash, 'control': control, 'manifest_sha256': manifest_hash, 'patches': {p.name: sha(p) for p in patches},
                    'generated': generated, 'boot': {x['name']: x['_boot'] for x in m['modules']}, 'pin': PIN, 'profile': (getattr(a, 'ios_profile', None) or IOS_DEFAULT) if ios else ('apple-high-v1' if sys.platform == 'darwin' else 'default')}
        if ios:
            if identity['profile'] == IOS_CUMULATIVE:
                identity['patch_order'] = [p.name for p in patches]
            identity['host'] = {p.name: sha(p) for p in (ROOT / 'ports/ios').iterdir() if p.is_file()}
        receipt = out / 'prepared.json'
        source = out / 'source'
        if receipt.exists():
            old = json.loads(receipt.read_text())
            require(old['identity'] == identity, 'preparation inputs/patch drift; use a fresh output')
            require(git(source, 'rev-parse', 'HEAD') == PIN and old['source'] == source_fingerprint(source),
                    'prepared source drift')
        else:
            require(not (out / 'build').exists(), 'clean build required')
            prepare_source(a.reference.resolve(), source, patches)
            (source / 'runtime/src/astral_control_context.h').write_text(control_header(control, control_hash))
            fingerprint = source_fingerprint(source)
            receipt.write_text(json.dumps({'identity': identity, 'source': fingerprint}, indent=2) + '\n')
        if a.configure or a.build:
            require(a.cmake and a.ninja and a.prefix and a.vulkan_include, 'configure requires cmake/ninja/prefix/vulkan-include')
            command = [a.cmake, '-S', source, '-B', out / 'build', '-G', 'Ninja',
                       '-DNX_GAME=astral', '-DNX_GEN_DIR=' + str(gen), '-DCMAKE_BUILD_TYPE=Release',
                       '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_MAKE_PROGRAM=' + str(a.ninja.resolve()),
                       '-DCMAKE_PREFIX_PATH=' + str(a.prefix.resolve()), '-DNX_VULKAN_INCLUDE=' + str(a.vulkan_include.resolve())]
            if ios:
                sdk = subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'], timeout=20).decode().strip()
                command += ['-DCMAKE_SYSTEM_NAME=iOS', '-DCMAKE_OSX_SYSROOT=' + sdk,
                            '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_OSX_DEPLOYMENT_TARGET=26.0',
                            '-DNX_IOS_HOST_DIR=' + str(ROOT / 'ports/ios')]
            run_logged(command, out / 'configure.log', timeout=90)
            commands = json.loads((out / 'build/compile_commands.json').read_text())
            require(commands and any('/gen/main/' in x['file'] or str(gen / 'main') in x['file'] for x in commands),
                    'empty early-return build refused')
            if ios:
                validate_ios_commands(commands, gen)
            if sys.platform == 'darwin':
                require(all('-DNX_APPLE_HIGH_MEMORY=1' in x['command'] for x in commands), 'mixed Apple profiles')
        if a.build:
            run_logged([a.cmake, '--build', out / 'build', '--parallel', jobs(a.jobs), '--target', 'astral'], out / 'build.log')
            require((out / ('build/astral.app/astral' if ios else 'build/astral')).is_file(), 'no executable produced')
            if ios:
                require(json.loads(receipt.read_text())['source'] == source_fingerprint(source), 'source changed during build')
                (out / 'built.json').write_text(json.dumps(simulator_build_identity(out), indent=2) + '\n')
        print(json.dumps({'state': 'built' if a.build else 'prepared', 'receipt': str(receipt),
                          'runtime_unverified': True, 'reports': {k: v['report'] for k, v in generated.items()}}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'reference', 'inputs', 'gen', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('cmake', 'ninja', 'prefix', 'vulkan-include'):
        p.add_argument('--' + name, type=Path)
    p.add_argument('--ios-simulator', action='store_true')
    p.add_argument('--ios-profile', choices=tuple(IOS_PROFILES))
    p.add_argument('--generated-receipt', type=Path)
    p.add_argument('--control-metadata', type=Path)
    p.add_argument('--configure', action='store_true')
    p.add_argument('--build', action='store_true')
    p.add_argument('--jobs', type=int, default=3)
    try:
        execute(p.parse_args())
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError, struct.error, inventory.ImportFailure, control.Failure) as e:
        p.exit(1, f'prepare blocked: {e}\n')


if __name__ == '__main__':
    main()
