#!/usr/bin/env python3
"""Package a macOS source-only release zip: the build tools, runtime patches, launcher assets and docs.

Usage: scripts/package_release.py [--version v0.1.0-preview] [--out dist] [--repo REPO] [--ref HEAD] [--dmg]

A release holds no game code, data, shaders or fonts, and no generated code: players run tools/acr_build.py on their
own dump and the game is recompiled on their machine. Files come from the committed tree only. When the private
exporter (scripts/export_public.py) is present the release is cut from its public export, so the same redactions
and the same scan apply; in a public checkout the committed files already are the public versions. The staged tree
is checked again before zipping: every file must be on the allowlist below (with the Python modules acr_build.py
needs, found by following its imports), and no binary other than the launcher art and OFL fonts may appear.
Standard library only; nothing is uploaded or published.
"""
import argparse
import ast
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'AC-Recomp'
DEFAULT_VERSION = 'v0.1.0-preview'
# Fixed members; tools/*.py dependencies of acr_build.py and the patches named in the series are added to these.
FIXED = ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'dependencies.lock', 'README.md',
         'tools/acr_build.py', 'tools/import_owned_dump.py', 'tools/astral_shader_full_inventory.py',
         'runtime/patches/series.macos',
         'tools/astral_spirv_harness/AstralSpirvHarness.csproj', 'tools/astral_spirv_harness/Directory.Build.props',
         'tools/astral_spirv_harness/README.md', 'tools/astral_spirv_harness/astral-headerless-compute.patch',
         'docs/BUILDING.md', 'docs/ASTRAL_SHARED_FONT_SWKBD.md', 'docs/ASTRAL_LAUNCHER.md',
         'docs/ASTRAL_SHADER_FULL_INVENTORY.md', 'docs/MAC_NVN_TEXTURE.md', 'docs/ASTRAL_PERF_HUD.md', 'docs/CONTROLLER_SUPPORT.md',
         'docs/ASTRAL_60FPS.md', 'docs/ASTRAL_RENDER_RES.md',
         'release/README-FIRST.txt', 'tools/acr_setup_cmd.py', 'docs/SETUP_APP.md')
FIXED_DIRS = ('assets/launcher/',)
NOTICE_GLOB = 'runtime/patches/*.NOTICE'
BINARY_OK = re.compile(r'^assets/launcher/[^/]+\.(?:ttf|otf|jpg|jpeg|png)$')
FORBIDDEN_SUFFIXES = {'.nsp', '.xci', '.nca', '.nso', '.nro', '.keys', '.bfttf', '.spv', '.metallib', '.dylib',
                      '.so', '.dll', '.exe', '.o', '.a', '.cpp', '.h', '.cs', '.npdm', '.bin', '.ipa', '.p12'}
# Original files are allowed to be C/C++ only as patches; no generated or extracted sources ship.
MAX_BYTES = 2 << 20


class PackageError(Exception):
    pass


def git_tree(repo, ref, out):
    data = subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', ref], check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            p = PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts:
                raise PackageError('unsafe archive path: ' + m.name)
            if m.isfile():
                target = out / m.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
                target.chmod(0o755 if m.mode & 0o111 else 0o644)


def source_tree(repo, ref, scratch):
    """The committed tree as the public sees it, and the export's verification findings (if the exporter exists)."""
    tree = scratch / 'tree'
    exporter = repo / 'scripts/export_public.py'
    if exporter.is_file():
        sys.path.insert(0, str(exporter.parent))
        import export_public
        findings = export_public.export(tree, repo, ref)[0]
        if findings:
            raise PackageError('the public export has findings; run scripts/export_public.py first:\n' +
                               '\n'.join(f'{r}:{n}: {rule}' for r, n, rule, _ in findings[:20]))
        return tree, True
    tree.mkdir(parents=True)
    git_tree(repo, ref, tree)
    return tree, False


# Entry points: acr_build.py, and the tools it runs as scripts.
ENTRY = ('tools/acr_build.py', 'tools/import_owned_dump.py', 'tools/astral_shader_full_inventory.py')


def tool_closure(tree, starts=ENTRY):
    """tools/*.py modules reachable from the entry points through imports."""
    seen, todo = set(), list(starts)
    local = {p.stem for p in (tree / 'tools').glob('*.py')}
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        for node in ast.walk(ast.parse((tree / rel).read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split('.')
                if parts == ['tools']:
                    names = [a.name for a in node.names]
                else:
                    names = [parts[1] if parts[0] == 'tools' else parts[0]]
            todo += [f'tools/{n}.py' for n in names if n in local and f'tools/{n}.py' not in seen]
    return sorted(seen)


def series(tree):
    names = []
    for line in (tree / 'runtime/patches/series.macos').read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            names.append('runtime/patches/' + line)
    return names


def members(tree):
    wanted = set(FIXED) | set(tool_closure(tree)) | set(series(tree))
    wanted |= {p.relative_to(tree).as_posix() for p in tree.glob(NOTICE_GLOB)}
    for d in FIXED_DIRS:
        wanted |= {p.relative_to(tree).as_posix() for p in (tree / d).rglob('*') if p.is_file()}
    missing = sorted(w for w in wanted if not (tree / w).is_file())
    if missing:
        raise PackageError('release members missing from the committed tree: ' + ', '.join(missing))
    return sorted(wanted)


def check(stage, names):
    problems = []
    for rel in names:
        path = stage / rel
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            problems.append(f'{rel}: forbidden file type {suffix}')
        if path.stat().st_size > MAX_BYTES:
            problems.append(f'{rel}: larger than {MAX_BYTES} bytes')
        data = path.read_bytes()
        if BINARY_OK.match(rel):
            continue
        if b'\0' in data:
            problems.append(f'{rel}: binary file')
            continue
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            problems.append(f'{rel}: not UTF-8 text')
    if problems:
        raise PackageError('release check failed:\n' + '\n'.join('  ' + p for p in problems))


def check_version(version):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version):
        raise PackageError('version must look like v0.1.0-preview')


def stage_release(version, repo, ref, scratch):
    """Stage and check the release members under scratch/<top>. Returns (stage, source tree)."""
    check_version(version)
    tree, exported = source_tree(Path(repo), ref, scratch)
    names = members(tree)
    stage = scratch / f'{NAME}-{version}'
    for rel in names:
        dest = stage / ('README-FIRST.txt' if rel == 'release/README-FIRST.txt' else rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tree / rel, dest)
    (stage / 'tools/acr_build.py').chmod(0o755)
    staged = sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file())
    check(stage, staged)
    if exported:
        import export_public
        findings = export_public.verify(stage)[0]
        if findings:
            raise PackageError('release scan findings:\n' +
                               '\n'.join(f'{r}:{n}: {rule}: {x}' for r, n, rule, x in findings[:20]))
    return stage, tree


def package(version=DEFAULT_VERSION, out=ROOT / 'dist', repo=ROOT, ref='HEAD', dmg=False):
    """Write <out>/AC-Recomp-<version>-macos.zip, and with dmg=True also the disk image with AC-Recomp Setup.app
    (scripts/make_dmg.py) built from the same staged kit."""
    check_version(version)
    top = f'{NAME}-{version}'
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f'{top}-macos.zip'
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        stage, tree = stage_release(version, repo, ref, scratch)
        staged = sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file())
        tmp = target.with_name(target.name + '.tmp')
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            for rel in staged:
                info = zipfile.ZipInfo(f'{top}/{rel}', date_time=(2026, 1, 1, 0, 0, 0))
                info.external_attr = ((0o755 if os.access(stage / rel, os.X_OK) else 0o644) | 0o100000) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, (stage / rel).read_bytes())
        tmp.replace(target)
        if dmg:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import make_dmg
            try:
                make_dmg.build_dmg(stage, out, version, tree / 'ports/macos-setup')
            except make_dmg.DmgError as e:
                raise PackageError('disk image: ' + str(e))
    return target, staged


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', default=DEFAULT_VERSION)
    p.add_argument('--out', type=Path, default=ROOT / 'dist')
    p.add_argument('--repo', type=Path, default=ROOT)
    p.add_argument('--ref', default='HEAD')
    p.add_argument('--dmg', action='store_true',
                   help='also build AC-Recomp-<version>-macos.dmg with AC-Recomp Setup.app (scripts/make_dmg.py)')
    a = p.parse_args(argv)
    try:
        target, staged = package(a.version, a.out, a.repo, a.ref, a.dmg)
    except (PackageError, subprocess.CalledProcessError, OSError) as e:
        print('package failed: ' + str(e), file=sys.stderr)
        return 1
    print(f'{target}: {len(staged)} files')
    if a.dmg:
        print(a.out / f'{NAME}-{a.version}-macos.dmg')
    return 0


if __name__ == '__main__':
    sys.exit(main())
