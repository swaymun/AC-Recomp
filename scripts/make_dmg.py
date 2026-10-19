#!/usr/bin/env python3
"""Build 'AC-Recomp Setup.app' and the macOS disk image that ships it.

Usage: scripts/make_dmg.py [--version v0.1.0] [--out dist] [--repo REPO] [--ref HEAD] [--kit DIR] [--app-only]

The setup app is compiled from ports/macos-setup/*.swift with swiftc (no Xcode project), gets an icon made from
assets/launcher/AC-Recomp.png with sips and iconutil, and carries the release build kit (the files
scripts/package_release.py puts in the zip) in Contents/Resources/kit. It is signed ad hoc only: it is not notarized,
so the first launch is blocked: on macOS 15+ the player tries once, then uses System Settings > Privacy & Security >
Open Anyway; on macOS 13-14, right-click > Open (docs/SETUP_APP.md). The image (UDZO, made with hdiutil) holds the
app, an Applications link and 'Read Me First.txt'. Standard library only; nothing is uploaded or published.
"""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = 'AC-Recomp Setup.app'
EXECUTABLE = 'ACRecompSetup'
BUNDLE_ID = 'local.ac-recomp.setup'
DEFAULT_VERSION = 'v0.1.0'
MIN_MACOS = '13.0'
ICON_SIZES = (16, 32, 128, 256, 512)

READ_ME = """AC-Recomp - read this first
===========================

1. Drag "AC-Recomp Setup" to Applications (or open it right here).
2. Open it. The first time, macOS refuses because the app is not notarized:
     - macOS 15 and later: try to open it once, then go to System Settings > Privacy & Security and click
       "Open Anyway" (then Open).
     - macOS 13 and 14: right-click (or Control-click) "AC-Recomp Setup", choose Open, then Open again.
     - Or, only after dragging it to Applications, in Terminal:
         xattr -dr com.apple.quarantine "/Applications/AC-Recomp Setup.app"
3. Follow the steps: it checks the build tools, asks for your own Astral Chain 1.0.0 NSP and keys, and builds
   AC-Recomp.app on your Mac (about 25 GB of free space, 30 to 90 minutes the first time).

This image contains NO game code, data, shaders, fonts or keys: only the open-source build tools, runtime patches,
launcher art and documentation. You need your own legally dumped copy of Astral Chain and your own console's keys,
and you are responsible for them. Everything the build produces comes from your dump; do not share it.

Prefer the command line? The same build kit is inside the app (Contents/Resources/kit) and in the release zip;
see docs/BUILDING.md.

This project is not affiliated with Nintendo or PlatinumGames. See README.md, LICENSE and THIRD_PARTY_NOTICES.md.
"""


class DmgError(Exception):
    pass


def run(cmd, **kw):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.returncode:
        raise DmgError(f'{Path(str(cmd[0])).name} failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}')
    return p.stdout


def dmg_name(version):
    return f'AC-Recomp-{version}-macos.dmg'


def kit_digest(kit):
    h = hashlib.sha256()
    for p in sorted(Path(kit).rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.name != 'KIT_VERSION':
            h.update(p.relative_to(kit).as_posix().encode() + b'\0' + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def info_plist(version):
    short = version.lstrip('v').split('-')[0]
    return {'CFBundleName': 'AC-Recomp Setup', 'CFBundleDisplayName': 'AC-Recomp Setup',
            'CFBundleExecutable': EXECUTABLE, 'CFBundleIdentifier': BUNDLE_ID, 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'AppIcon', 'CFBundleShortVersionString': short, 'CFBundleVersion': short,
            'LSMinimumSystemVersion': MIN_MACOS, 'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.games', 'NSPrincipalClass': 'NSApplication'}


def make_icns(png, dest):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / 'AppIcon.iconset'
        iconset.mkdir()
        for size in ICON_SIZES:
            for scale in (1, 2):
                px = size * scale
                name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
                run(['sips', '-z', px, px, png, '--out', iconset / name])
        run(['iconutil', '-c', 'icns', iconset, '-o', dest])


def swift_sources(swift_dir):
    sources = sorted(Path(swift_dir).glob('*.swift'))
    if not sources:
        raise DmgError(f'no Swift sources in {swift_dir}')
    return sources


def compile_swift(swift_dir, exe, swiftc=None):
    swiftc = swiftc or (['xcrun', 'swiftc'] if shutil.which('xcrun') else [shutil.which('swiftc') or 'swiftc'])
    if isinstance(swiftc, str):
        swiftc = [swiftc]
    run([*swiftc, '-O', '-parse-as-library', '-target', f'arm64-apple-macos{MIN_MACOS}', '-o', exe,
         *swift_sources(swift_dir)])


def build_app(kit, dest, version=DEFAULT_VERSION, swift_dir=ROOT / 'ports/macos-setup', sign=True, compile=True):
    """Write dest ('.../AC-Recomp Setup.app') with the kit inside. Returns dest."""
    kit, dest = Path(kit), Path(dest)
    if not (kit / 'tools/acr_build.py').is_file() or not (kit / 'tools/acr_setup_cmd.py').is_file():
        raise DmgError(f'{kit} is not a build kit (no tools/acr_build.py or tools/acr_setup_cmd.py)')
    if dest.exists():
        shutil.rmtree(dest)
    contents = dest / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    resources = contents / 'Resources'
    shutil.copytree(kit, resources / 'kit', ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    (resources / 'kit/KIT_VERSION').write_text(f'{version}+{kit_digest(resources / "kit")}\n')
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info_plist(version)))
    (contents / 'PkgInfo').write_text('APPL????')
    if compile:
        compile_swift(swift_dir, contents / 'MacOS' / EXECUTABLE)
        make_icns(kit / 'assets/launcher/AC-Recomp.png', resources / 'AppIcon.icns')
    if sign and shutil.which('codesign'):
        run(['codesign', '--force', '--deep', '--sign', '-', dest])
    return dest


def layout(app, stage):
    """The image's contents: the app, an Applications link and the read-me."""
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    target = stage / APP_NAME
    if Path(app).resolve() != target.resolve():
        if target.exists():
            shutil.rmtree(target)
        # symlinks=True keeps the bundle exactly as signed.
        shutil.copytree(app, target, symlinks=True)
    link = stage / 'Applications'
    if link.is_symlink() or link.exists():
        link.unlink()
    os.symlink('/Applications', link)
    (stage / 'Read Me First.txt').write_text(READ_ME)
    return stage


def create_image(stage, target, volname='AC-Recomp Setup'):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + '.tmp.dmg')
    if tmp.exists():
        tmp.unlink()
    run(['hdiutil', 'create', '-volname', volname, '-srcfolder', stage, '-fs', 'HFS+', '-format', 'UDZO',
         '-imagekey', 'zlib-level=9', '-ov', tmp])
    tmp.replace(target)
    return target


def build_dmg(kit, out, version=DEFAULT_VERSION, swift_dir=ROOT / 'ports/macos-setup', app_only=False):
    """Kit directory -> out/AC-Recomp Setup.app (app_only) or out/AC-Recomp-<version>-macos.dmg."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if app_only:
        return build_app(kit, out / APP_NAME, version, swift_dir)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / 'stage'
        build_app(kit, stage / APP_NAME, version, swift_dir)
        layout(stage / APP_NAME, stage)
        return create_image(stage, out / dmg_name(version))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', default=DEFAULT_VERSION)
    p.add_argument('--out', type=Path, default=ROOT / 'dist')
    p.add_argument('--repo', type=Path, default=ROOT)
    p.add_argument('--ref', default='HEAD')
    p.add_argument('--kit', type=Path, help='an unpacked build kit to use instead of staging one from --ref')
    p.add_argument('--app-only', action='store_true', help='write only the .app into --out')
    a = p.parse_args(argv)
    try:
        if a.kit:
            target = build_dmg(a.kit, a.out, a.version, app_only=a.app_only)
        else:
            sys.path.insert(0, str(ROOT / 'scripts'))
            import package_release
            with tempfile.TemporaryDirectory() as scratch:
                stage, tree = package_release.stage_release(a.version, a.repo, a.ref, Path(scratch))
                target = build_dmg(stage, a.out, a.version, tree / 'ports/macos-setup', a.app_only)
    except (DmgError, subprocess.CalledProcessError, OSError) as e:
        print('make_dmg failed: ' + str(e), file=sys.stderr)
        return 1
    except Exception as e:  # package_release.PackageError
        if type(e).__name__ != 'PackageError':
            raise
        print('make_dmg failed: ' + str(e), file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
