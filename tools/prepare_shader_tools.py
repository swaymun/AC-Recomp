#!/usr/bin/env python3
"""Prepare the pinned offline translator; all third-party state stays ignored.

No game inventory is inferred. Batch accepts only an explicit extracted manifest tree.
"""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

WONDER = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
RYUBING = 'a82350bb774f70fcbd41c9987bf67a3775409963'
SDK_VERSION = '10.0.401'
SDK_URL = 'https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.401/dotnet-sdk-10.0.401-linux-x64.tar.gz'
SDK_SHA512 = '51c8b999af9e8dd9998c9edc5944e19a90788862068acd38694e098889054ce8c23d4f0c5cccfa16bf187d044562359e5ee69a9f8ad0bbe913ba90311fbce25b'
METADATA = 'https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json'
NUGET = 'https://api.nuget.org/v3/index.json'
HARNESS = 'tools/maxwell/spirv_harness/SpirvHarness.csproj'
DLL = 'private/build/spirv_harness/bin/Release/net10.0/spirv_harness.dll'
PATCHES = {'spirv-else-if.patch': 'CodeGen/Spirv/SpirvGenerator.cs',
           'spirv-fmz.patch': 'Instructions/InstEmitFloatArithmetic.cs'}
HEADER = ['id', 'stage', 'code_off', 'code_size', 'ctrl_off', 'ctrl_size',
          'program_start', 'program_bytes', 'const_off', 'const_size',
          'code_sha1_16', 'code_file', 'ctrl_file']


def run(argv, cwd=None, env=None, log=None, allowed=(0,)):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if log:
        Path(log).write_text(result.stdout)
    if result.returncode not in allowed:
        raise ValueError(f'command exited {result.returncode}: {argv}\n{result.stdout[-6000:]}')
    return result


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def private_path(repo, path):
    repo, path = Path(repo).resolve(), Path(path).resolve()
    if not any(path.is_relative_to(repo / name) and path != repo / name
               for name in ('.local', 'private')):
        raise ValueError(f'path must be below repository .local/ or private/: {path}')
    relative = path.relative_to(repo)
    run(['git', 'check-ignore', '--quiet', '--', str(relative)], cwd=repo)
    tracked = run(['git', 'ls-files', '--', str(relative)], cwd=repo).stdout.strip()
    if tracked:
        raise ValueError('private output includes tracked files')
    return path


def verify_pin(path, pin):
    if run(['git', 'rev-parse', 'HEAD'], cwd=path).stdout.strip() != pin:
        raise ValueError(f'wrong source pin: {path}')
    if run(['git', 'diff', 'HEAD', '--'], cwd=path).stdout:
        raise ValueError(f'modified pinned source: {path}')
    untracked = run(['git', 'ls-files', '--others', '--exclude-standard'], cwd=path).stdout.splitlines()
    if any(Path(p).name != 'packages.lock.json' for p in untracked):
        raise ValueError(f'untracked source in pinned checkout: {path}')


def checkout(path, url, pin):
    if not path.exists():
        run(['git', 'clone', '--quiet', '--no-checkout', url, path])
        run(['git', 'checkout', '--quiet', '--detach', pin], cwd=path)
    verify_pin(path, pin)


def verify_lock(repo):
    lock = json.loads((repo / 'dependencies.lock').read_text())
    w = next(x for x in lock['references'] if x['name'] == 'SuperMarioWonderRecomp')
    r = next(x for x in lock['dependencies'] if x['name'] == 'Ryubing')
    if w['revision'] != WONDER or r['revision'] != RYUBING:
        raise ValueError('dependency lock does not match supported source pins')
    return w, r


def download(url, path):
    with urllib.request.urlopen(url, timeout=120) as response, path.open('wb') as out:
        shutil.copyfileobj(response, out)


def sdk(prefix):
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        raise ValueError('this SDK bootstrap supports Linux x64 only; run over SSH')
    metadata = prefix / 'dotnet-releases.json'
    download(METADATA, metadata)
    data = json.loads(metadata.read_text())
    selected = [f for release in data['releases']
                for s in release.get('sdks', [release.get('sdk', {})])
                if s.get('version') == SDK_VERSION for f in s['files']
                if f['rid'] == 'linux-x64' and f['name'].endswith('.tar.gz')]
    if not any(f['url'] == SDK_URL and f['hash'].lower() == SDK_SHA512 for f in selected):
        raise ValueError('vendor SDK metadata differs from pinned archive/hash')
    archive = prefix / 'dotnet-sdk-10.0.401-linux-x64.tar.gz'
    if not archive.exists():
        download(SDK_URL, archive)
    if digest(archive, 'sha512') != SDK_SHA512:
        raise ValueError('SDK archive SHA-512 mismatch')
    root = prefix / 'dotnet'
    if not (root / 'dotnet').exists():
        root.mkdir(exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter='data')
    return root, {'version': SDK_VERSION, 'url': SDK_URL, 'sha512': SDK_SHA512,
                  'metadata_url': METADATA, 'metadata_sha256': digest(metadata)}


def package_receipts(wonder, packages):
    receipts = {}
    assets_paths = list((wonder / 'private/build').rglob('project.assets.json'))
    assets_paths += list((wonder / 'private/third_party/ryubing/src').glob('*/obj/project.assets.json'))
    for assets in assets_paths:
        data = json.loads(assets.read_text())
        sources = set(data.get('project', {}).get('restore', {}).get('sources', {}))
        if sources != {NUGET}:
            raise ValueError(f'unexpected NuGet sources: {sources}')
        for name, info in data['libraries'].items():
            if info['type'] != 'package':
                continue
            directory = packages / info['path']
            archives = list(directory.glob('*.nupkg'))
            if len(archives) != 1:
                raise ValueError(f'missing package archive: {name}')
            actual = base64.b64encode(bytes.fromhex(digest(archives[0], 'sha512'))).decode()
            sidecar = archives[0].with_name(archives[0].name + '.sha512')
            metadata = json.loads((directory / '.nupkg.metadata').read_text())
            if actual != sidecar.read_text().strip():
                raise ValueError(f'NuGet package archive hash mismatch: {name}')
            if metadata['contentHash'] != info['sha512'] or metadata['source'] != NUGET:
                raise ValueError(f'NuGet package content hash/source mismatch: {name}')
            with zipfile.ZipFile(archives[0]) as archive:
                for member in archive.infolist():
                    local = directory / member.filename
                    # NuGet normalizes the root nuspec name to lowercase.
                    if local.suffix == '.nuspec' and local.parent == directory:
                        local = directory / local.name.lower()
                    if member.is_dir():
                        continue
                    if not local.resolve().is_relative_to(directory.resolve()):
                        raise ValueError('package file escapes cache')
                    # NuGet omits ZIP packaging metadata when expanding the cache.
                    required = local.suffix.lower() in ('.dll', '.props', '.targets', '.cs', '.nuspec')
                    if required and not local.is_file():
                        raise ValueError(f'missing expanded package file: {name}')
                    if local.is_file() and hashlib.sha256(archive.read(member)).hexdigest() != digest(local):
                        raise ValueError(f'expanded package differs from archive: {name}')
            nuspecs = list(directory.glob('*.nuspec'))
            xml = ET.parse(nuspecs[0])
            provenance = {}
            for node in xml.iter():
                tag = node.tag.rsplit('}', 1)[-1]
                if tag in ('license', 'licenseUrl', 'repository', 'projectUrl', 'authors'):
                    provenance[tag] = {'text': node.text, 'attributes': node.attrib}
            receipts[name] = {'archive_sha512_base64': actual, 'sha256': digest(archives[0]),
                              'content_sha512_base64': info['sha512'],
                              'source': NUGET, 'nuspec_sha256': digest(nuspecs[0]),
                              'declared_provenance': provenance}
    if not receipts:
        raise ValueError('no resolved package provenance')
    return receipts


def validate_manifest(repo, root):
    root = private_path(repo, root)
    manifests = sorted(root.rglob('manifest.tsv'))
    if not manifests:
        raise ValueError('no extracted manifest.tsv; PKZ requires separate format inventory')
    count = 0
    for manifest in manifests:
        private_path(repo, manifest)
        with manifest.open(newline='') as stream:
            rows = csv.DictReader(stream, delimiter='\t')
            if rows.fieldnames != HEADER:
                raise ValueError('unexpected extracted manifest schema')
            for row in rows:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError('malformed manifest row')
                h = row['code_sha1_16']
                if not re.fullmatch('[0-9a-f]{16}', h):
                    raise ValueError('unsafe code hash')
                paths = []
                for column in ('code_file', 'ctrl_file'):
                    path = (manifest.parent / row[column]).resolve()
                    if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
                        raise ValueError('manifest file escapes its group or is missing')
                    private_path(repo, path)
                    paths.append(path)
                code, ctrl = (p.read_bytes() for p in paths)
                if hashlib.sha1(code).hexdigest()[:16] != h:
                    raise ValueError('code hash differs from manifest')
                if len(code) != int(row['code_size'], 0) or len(ctrl) != int(row['ctrl_size'], 0):
                    raise ValueError('manifest size mismatch')
                if len(ctrl) < 0x754 or len(code) < 4:
                    raise ValueError('truncated code/control')
                start = int.from_bytes(ctrl[0x708:0x70c], 'little')
                if start != int(row['program_start'], 0) or start >= len(code):
                    raise ValueError('invalid program start')
                count += 1
    if not count:
        raise ValueError('empty manifest inventory')
    return count


def check_results(path, expected=None):
    with Path(path).open(newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    if not rows or any(row.get('status') not in ('ok', 'ok-retry') for row in rows):
        raise ValueError('batch contains failed/invalid shaders or no results; inspect results.tsv')
    hashes = [row.get('hash') for row in rows]
    if len(set(hashes)) != len(hashes) or (expected is not None and set(hashes) != expected):
        raise ValueError('batch result hashes do not match complete input inventory')
    return len(rows)


def prepare(repo, prefix, validator):
    w, r = verify_lock(repo)
    prefix.mkdir(parents=True, exist_ok=True)
    wonder = prefix / 'wonder'
    checkout(wonder, w['repository'], WONDER)
    ryubing = wonder / 'private/third_party/ryubing'
    checkout(ryubing, r['repository'], RYUBING)
    for source, entry in ((wonder, w), (ryubing, r)):
        evidence = entry['license_evidence']
        for item in evidence if isinstance(evidence, list) else [evidence]:
            if digest(source / item['path']) != item['sha256']:
                raise ValueError('source license hash mismatch')
    sdk_root, sdk_receipt = sdk(prefix)
    env = os.environ.copy()
    env.update(DOTNET_ROOT=str(sdk_root), DOTNET_CLI_HOME=str(prefix / 'dotnet-home'),
               NUGET_PACKAGES=str(prefix / 'nuget'), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false')
    dotnet = sdk_root / 'dotnet'
    if run([dotnet, '--version'], cwd=prefix, env=env).stdout.strip() != SDK_VERSION:
        raise ValueError('installed SDK version mismatch')
    patch_receipts = {}
    translator = wonder / 'tools/maxwell/spirv_harness/translator'
    for name, relative in PATCHES.items():
        patch, source = translator / name, ryubing / 'src/Ryujinx.Graphics.Shader' / relative
        run(['patch', '--dry-run', '--fuzz=0', '--forward', str(source), str(patch)])
        patch_receipts[name] = {'sha256': digest(patch), 'source_sha256': digest(source)}
    config = prefix / 'NuGet.Config'
    config.write_text('<configuration><packageSources><clear/><add key="nuget.org" '
                      'value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>\n')
    locks = [wonder / 'tools/maxwell/spirv_harness/packages.lock.json',
             translator / 'packages.lock.json',
             ryubing / 'src/Ryujinx.Common/packages.lock.json',
             ryubing / 'src/Spv.Generator/packages.lock.json']
    locked = ['--locked-mode'] if all(p.exists() for p in locks) else []
    run([dotnet, 'restore', wonder / HARNESS, '--configfile', config,
         '-p:RestorePackagesWithLockFile=true', '--disable-parallel', *locked], env=env,
        log=prefix / 'restore.log')
    build = run([dotnet, 'build', wonder / HARNESS, '-c', 'Release', '-m:3', '--no-restore'],
                env=env, log=prefix / 'build.log')
    for name, relative in PATCHES.items():
        patched = wonder / 'private/build/spirv_harness/obj/Ryujinx.Graphics.Shader/patched' / relative
        patch_receipts[name]['patched_sha256'] = digest(patched)
    validator = Path(validator).resolve(strict=True)
    version = run([validator, '--version']).stdout.strip()
    package = run(['dpkg-query', '-W', '-f=${Package} ${Version} ${Architecture}\n', 'spirv-tools']).stdout.strip()
    help_run = run([dotnet, wonder / DLL, '--help'], env=env, allowed=(2,), log=prefix / 'help.log')
    packages = package_receipts(wonder, prefix / 'nuget')
    archives = sorted((prefix / 'nuget').glob('*/*/*.nupkg'))
    signatures = run([dotnet, 'nuget', 'verify', *archives, '--all', '--configfile', config],
                     env=env, log=prefix / 'package-signatures.log')
    if any('Content hash: ' + p['content_sha512_base64'] not in signatures.stdout
           for p in packages.values()):
        raise ValueError('NuGet verified content hash differs from restore resolution')
    runtime_files = {str(p): digest(p) for p in (wonder / DLL).parent.rglob('*')
                     if p.is_file() and p.suffix in ('.dll', '.json')}
    receipt = {'schema': 1, 'wonder': WONDER, 'ryubing': RYUBING,
               'dependency_lock_sha256': digest(repo / 'dependencies.lock'), 'sdk': sdk_receipt,
               'patches': patch_receipts, 'packages': packages,
               'package_signature_verification_exit': signatures.returncode,
               'package_signature_log_sha256': digest(prefix / 'package-signatures.log'),
               'runtime_files': runtime_files,
               'restore_locks': {str(p): digest(p) for p in locks},
               'validator': {'path': str(validator), 'sha256': digest(validator),
                             'version': version, 'distro_package': package},
               'build_exit': build.returncode, 'help_exit': help_run.returncode,
               'dll': str(wonder / DLL), 'dll_sha256': digest(wonder / DLL),
               'dotnet': str(dotnet), 'dotnet_sha256': digest(dotnet)}
    (prefix / 'toolchain.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def batch(repo, prefix, root, output, jobs):
    receipt = json.loads((prefix / 'toolchain.json').read_text())
    verify_lock(repo)
    verify_pin(prefix / 'wonder', WONDER)
    verify_pin(prefix / 'wonder/private/third_party/ryubing', RYUBING)
    if receipt['schema'] != 1 or receipt['wonder'] != WONDER or receipt['ryubing'] != RYUBING:
        raise ValueError('invalid toolchain manifest pins/schema')
    if receipt['dependency_lock_sha256'] != digest(repo / 'dependencies.lock'):
        raise ValueError('dependency lock changed; prepare again')
    for name in ('dotnet', 'dll'):
        private_path(repo, receipt[name])
        if digest(receipt[name]) != receipt[name + '_sha256']:
            raise ValueError(f'{name} hash changed')
    for path, expected in receipt['runtime_files'].items():
        private_path(repo, path)
        if digest(path) != expected:
            raise ValueError('runtime dependency hash changed')
    for path, expected in receipt['restore_locks'].items():
        private_path(repo, path)
        if digest(path) != expected:
            raise ValueError('restore lock hash changed')
    if package_receipts(prefix / 'wonder', prefix / 'nuget') != receipt['packages']:
        raise ValueError('resolved package hashes changed')
    if digest(receipt['validator']['path']) != receipt['validator']['sha256']:
        raise ValueError('validator hash changed')
    count = validate_manifest(repo, root)
    expected = set()
    for manifest in Path(root).rglob('manifest.tsv'):
        with manifest.open(newline='') as stream:
            expected.update(row['code_sha1_16'] for row in csv.DictReader(stream, delimiter='\t'))
    output = private_path(repo, output)
    if output.exists():
        raise ValueError('batch output must be a new directory (preserve previous evidence)')
    output.mkdir(parents=True)
    command = [receipt['dotnet'], receipt['dll'], '--batch', str(Path(root).resolve()),
               '--out', str(output), '--jobs', str(jobs), '--spirv-val', receipt['validator']['path'],
               '--target-env', 'vulkan1.2']
    result = run(command, log=output / 'batch.log')
    translated = check_results(output / 'results.tsv', expected)
    for spv in output.glob('*.spv'):
        run([receipt['validator']['path'], '--target-env', 'vulkan1.2', spv])
    if len(list(output.glob('*.spv'))) != translated:
        raise ValueError('result/product count mismatch')
    report = {'schema': 1, 'command': command, 'exit_code': result.returncode,
              'manifest_stages': count, 'translated_validated_blocks': translated}
    (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'batch', 'check-manifest'))
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--prefix', type=Path)
    parser.add_argument('--spirv-val', default='/usr/bin/spirv-val')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--jobs', type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    repo = args.repo.resolve()
    try:
        prefix = private_path(repo, args.prefix or repo / '.local/shader-tools')
        if args.action == 'prepare':
            report = prepare(repo, prefix, args.spirv_val)
        elif args.input is None:
            raise ValueError('--input is required')
        elif args.action == 'check-manifest':
            report = {'stages': validate_manifest(repo, args.input)}
        elif args.output is None:
            raise ValueError('--output is required')
        else:
            report = batch(repo, prefix, args.input, args.output, args.jobs)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(f'preflight failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
