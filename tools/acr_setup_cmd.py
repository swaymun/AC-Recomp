#!/usr/bin/env python3
"""Helper for AC-Recomp Setup: prerequisite checks and the tools/acr_build.py command line.

    acr_setup_cmd.py check                      JSON list of prerequisite rows (id, title, ok, detail, fix)
    acr_setup_cmd.py command [build options]    JSON {"argv": [...], "env": {...}} for the build
    acr_setup_cmd.py run [build options]        copy the kit out of the app if needed, then exec the build
    acr_setup_cmd.py kit --dest DIR             copy this kit (the folder holding tools/) to DIR

Build options: --nsp FILE --keys FILE [--title-keys FILE] [--fonts DIR] --out DIR [--fps 60]
[--render-res WxH] [--kit DIR] [--python EXE] [--dry-run].

Windows: check --windows [--reuse-shaders], or run --windows --nsp FILE --keys FILE
--out DIR [--title-keys FILE] [--spirv-dir DIR] [--fonts DIR] [--jobs N] [--no-desktop-shortcut].
Alternatively reuse --import-dir DIR --control-receipt FILE. --to-stage control checks inputs only.
The dump and keys are imported locally on Windows; a successful Windows build is followed by local icon/launcher
compilation and per-user shortcut creation. A failed or dry-run build never creates shortcuts.

The setup app passes file paths only; this helper never opens, prints, copies or hashes key files. It must run on
the Python 3.9 that ships with the Xcode command-line tools, because it is what finds a newer Python for the build.
Standard library only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

KIT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 11)
BREW_PREFIXES = ('/opt/homebrew', '/usr/local')
# Homebrew formulae tools/acr_build.py's preflight requires (cmake and ninja fall back to the build venv, and the
# Vulkan headers to a pinned checkout, but installing them is faster and is what the docs recommend).
FORMULAE = ('cmake', 'ninja', 'pkg-config', 'sdl3', 'opus', 'molten-vk', 'vulkan-headers', 'spirv-tools', 'zstd')
OPTIONAL_FORMULAE = {'cmake', 'ninja', 'vulkan-headers'}
BREW_INSTALL = ('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
DOTNET_DIRS = ('/usr/local/share/dotnet', '~/.dotnet')
# Microsoft's installer into the user's home: no administrator password (the Homebrew cask needs one).
DOTNET_INSTALL = 'curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0 --install-dir ~/.dotnet'
PYTHON_CANDIDATES = ('{brew}/bin/python3', '{brew}/bin/python3.14', '{brew}/bin/python3.13', '{brew}/bin/python3.12',
                     '{brew}/bin/python3.11', '/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
                     '/usr/bin/python3')
RES = re.compile(r'^\d{3,4}x\d{3,4}$')


def brew_prefix(prefixes=BREW_PREFIXES):
    for p in prefixes:
        if os.path.isfile(os.path.join(p, 'bin', 'brew')):
            return p
    return None


def python_version(exe, runner=subprocess.run):
    try:
        p = runner([exe, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], capture_output=True, text=True,
                   timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r'^(\d+)\.(\d+)', p.stdout.strip()) if p.returncode == 0 else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def find_python(prefixes=BREW_PREFIXES, runner=subprocess.run, exists=os.path.isfile):
    """The first Python 3.11+ found (Homebrew first), as (path, (major, minor)), or (None, None)."""
    seen = set()
    for template in PYTHON_CANDIDATES:
        for prefix in (prefixes if '{brew}' in template else ('',)):
            exe = template.format(brew=prefix)
            if exe in seen or not exists(exe):
                continue
            seen.add(exe)
            v = python_version(exe, runner)
            if v and v >= MIN_PYTHON:
                return exe, v
    return None, None


def dotnet_has_10(prefixes=BREW_PREFIXES, runner=subprocess.run):
    cands = [os.path.join(p, 'bin', 'dotnet') for p in prefixes]
    cands += [os.path.join(os.path.expanduser(d), 'dotnet') for d in DOTNET_DIRS]
    for exe in cands:
        if not os.path.isfile(exe):
            continue
        try:
            out = runner([exe, '--list-sdks'], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if re.search(r'^10\.', out, re.M):
            return exe
    return None


def clt_installed(runner=subprocess.run):
    try:
        return runner(['/usr/bin/xcode-select', '-p'], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check(prefixes=BREW_PREFIXES, runner=subprocess.run, exists=os.path.isfile, isdir=os.path.isdir):
    """Prerequisite rows. 'fix' is a shell command to run in Terminal ('' when there is nothing to run)."""
    rows = []
    clt = clt_installed(runner)
    rows.append({'id': 'clt', 'title': 'Xcode Command Line Tools', 'ok': clt, 'required': True,
                 'detail': 'compilers, git and patch' if clt else 'not installed',
                 'fix': 'xcode-select --install'})
    brew = brew_prefix(prefixes)
    rows.append({'id': 'brew', 'title': 'Homebrew', 'ok': bool(brew), 'required': True,
                 'detail': brew or 'not installed (https://brew.sh)', 'fix': BREW_INSTALL})
    py, v = find_python(prefixes, runner, exists)
    rows.append({'id': 'python', 'title': 'Python 3.11 or newer', 'ok': bool(py), 'required': True,
                 'detail': '%s (%d.%d)' % (py, v[0], v[1]) if py else 'not found',
                 'fix': brew_cmd(brew, 'install python')})
    missing = [f for f in FORMULAE if not (brew and isdir(os.path.join(brew, 'opt', f)))]
    needed = [f for f in missing if f not in OPTIONAL_FORMULAE]
    rows.append({'id': 'formulae', 'title': 'Build libraries (Homebrew)', 'ok': not needed, 'required': True,
                 'detail': ('missing: ' + ', '.join(missing)) if missing else ', '.join(FORMULAE),
                 'fix': brew_cmd(brew, 'install ' + ' '.join(missing or FORMULAE))})
    dotnet = dotnet_has_10(prefixes, runner)
    rows.append({'id': 'dotnet', 'title': '.NET 10 SDK (shader translator)', 'ok': bool(dotnet), 'required': True,
                 'detail': dotnet or 'not found (installs into ~/.dotnet, no administrator password)',
                 'fix': DOTNET_INSTALL})
    return rows


def brew_cmd(prefix, args):
    return '%s %s' % (os.path.join(prefix, 'bin', 'brew') if prefix else 'brew', args)


def nested(a, b):
    """True when a and b are the same folder or one is inside the other (after resolving links and '..')."""
    a, b = (os.path.normcase(os.path.realpath(os.path.expanduser(p))) for p in (a, b))
    try:
        return os.path.commonpath((a, b)) in (a, b)
    except ValueError:  # Different drives on Windows.
        return False


def check_out(out, kits):
    """The build folder must not be, contain or sit inside a kit folder: refreshing the kit deletes that folder."""
    for kit in kits:
        if kit and nested(out, kit):
            raise ValueError('the build folder %s overlaps the build kit at %s; choose another folder' % (out, kit))


def build_argv(python, kit, nsp, keys, out, title_keys=None, fonts=None, fps=None, render_res=None,
               import_dir=None, control_receipt=None, spirv_dir=None, jobs=None):
    """The tools/acr_build.py command line. Every input is a path; nothing is read here."""
    inputs = ((import_dir, 'import folder'), (control_receipt, 'control receipt')) if import_dir else (
        (nsp, 'NSP'), (keys, 'keys'))
    for value, what in (*inputs, (out, 'build folder')):
        if not value:
            raise ValueError(what + ' is required')
    argv = [python, '-u', os.path.join(kit, 'tools', 'acr_build.py')]
    if import_dir:
        if nsp or keys or title_keys:
            raise ValueError('an imported folder cannot be combined with dump/key options')
        argv += ['--import-dir', import_dir, '--control-receipt', control_receipt]
    else:
        if control_receipt:
            raise ValueError('control receipt requires an import folder')
        argv += ['--nsp', nsp, '--keys', keys]
    if title_keys:
        argv += ['--title-keys', title_keys]
    if fonts:
        argv += ['--fonts', fonts]
    argv += ['--out', out]
    if fps:
        if str(fps) not in ('30', '60'):
            raise ValueError('fps must be 30 or 60')
        argv += ['--fps', str(fps)]
    if render_res:
        if not RES.match(render_res):
            raise ValueError('render resolution must look like 2560x1440')
        argv += ['--render-res', render_res]
    if spirv_dir:
        argv += ['--spirv-dir', spirv_dir]
    if jobs is not None:
        if int(jobs) < 1:
            raise ValueError('jobs must be positive')
        argv += ['--jobs', str(jobs)]
    return argv


def windows_check(reuse_shaders=False):
    """Read-only Windows checks; installers are offered separately by Setup.ps1."""
    import windows_native
    rows = []
    def row(name, title, ok, detail, required=True):
        rows.append(dict(id=name, title=title, ok=bool(ok), detail=detail, required=required))
    row('python', '64-bit Python 3.11 or newer', sys.version_info >= MIN_PYTHON and sys.maxsize > 2**32, sys.executable)
    row('git', 'Git for Windows', shutil.which('git'), shutil.which('git') or 'not found')
    try:
        env = windows_native.developer_environment()
        missing = [n for n in ('clang-cl', 'clang++', 'rc', 'cmake', 'ninja') if not shutil.which(n, path=env['PATH'])]
        row('vs', 'Visual Studio C++ Build Tools', not missing,
            'missing: ' + ', '.join(missing) if missing else 'C++ compiler, Clang, Windows SDK, CMake and Ninja found')
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        row('vs', 'Visual Studio C++ Build Tools', False, str(e))
    dotnet = shutil.which('dotnet')
    try:
        sdks = subprocess.run([dotnet, '--list-sdks'], capture_output=True, text=True, timeout=30).stdout if dotnet else ''
    except (OSError, subprocess.SubprocessError):
        sdks = ''
    row('dotnet', '.NET 10 SDK', re.search(r'^10\.', sdks, re.M),
        'not needed with translated shaders' if reuse_shaders else '.NET 10 SDK needed for shader translation',
        not reuse_shaders)
    import ctypes.util
    row('shaders', 'Shader tools (spirv-val and zstd.dll)',
        shutil.which('spirv-val') and ctypes.util.find_library('zstd'),
        'not needed with translated shaders' if reuse_shaders else
        'Install SPIRV-Tools and zstd.dll on PATH, or supply translated shaders from your Mac build',
        not reuse_shaders)
    return rows


def windows_install(argv, kit, out, desktop=True, runner=subprocess.run):
    """Run the real build first; a failed build must never create a success shortcut."""
    env = windows_build_env(os.environ)
    result = runner(argv, env=env)
    if result.returncode:
        return result.returncode
    finish = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
              str(Path(kit) / 'ports/windows/FinishInstall.ps1'), '-InstallDir', str(out)]
    if not desktop:
        finish.append('-NoDesktopShortcut')
    return runner(finish, env=env).returncode


def windows_build_env(base):
    """Python writes UTF-8 to pipes/logs and uses UTF-8 for default text files."""
    return dict(base, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
                DOTNET_CLI_TELEMETRY_OPTOUT='1')


def build_env(base, prefixes=BREW_PREFIXES):
    """Apps start with a bare PATH; put Homebrew and the .NET SDK first so the build finds its tools."""
    env = dict(base)
    extra = [os.path.join(p, d) for p in prefixes for d in ('bin', 'sbin')] + ['/usr/local/share/dotnet',
                                                                                  os.path.expanduser('~/.dotnet')]
    path = [p for p in env.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin').split(':') if p]
    env['PATH'] = ':'.join(extra + [p for p in path if p not in extra])
    env['PYTHONUNBUFFERED'] = '1'
    env.setdefault('DOTNET_CLI_TELEMETRY_OPTOUT', '1')
    return env


def kit_version(kit):
    p = Path(kit) / 'KIT_VERSION'
    return p.read_text().strip() if p.is_file() else ''


def copy_kit(src, dest):
    """Copy the kit to a writable folder (the app may run read-only from the DMG). Skipped when it is current."""
    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve():
        return dest
    if dest.is_dir() and kit_version(dest) and kit_version(dest) == kit_version(src):
        return dest
    tmp = dest.with_name(dest.name + '.tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    return dest


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd')
    sub.required = True
    c = sub.add_parser('check')
    c.add_argument('--windows', action='store_true')
    c.add_argument('--reuse-shaders', action='store_true')
    k = sub.add_parser('kit')
    k.add_argument('--dest', required=True)
    for name in ('command', 'run'):
        s = sub.add_parser(name)
        s.add_argument('--nsp')
        s.add_argument('--keys')
        s.add_argument('--title-keys')
        s.add_argument('--fonts')
        s.add_argument('--out', required=True)
        s.add_argument('--fps', choices=('30', '60'))
        s.add_argument('--render-res')
        s.add_argument('--kit', help='writable copy of the kit to build from (copied from this one if needed)')
        s.add_argument('--python', help='Python 3.11+ for the build (default: found automatically)')
        s.add_argument('--dry-run', action='store_true', help='pass --dry-run to the build (nothing is changed)')
        s.add_argument('--import-dir')
        s.add_argument('--control-receipt')
        s.add_argument('--spirv-dir')
        s.add_argument('--jobs', type=int)
        s.add_argument('--to-stage', choices=('control',))
        s.add_argument('--windows', action='store_true', help='finish a Windows install with icon and shortcuts')
        s.add_argument('--no-desktop-shortcut', action='store_true')
    return p.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    windows = getattr(a, 'windows', False) or sys.platform == 'win32'
    if windows:
        # Environment flags affect child interpreters, not this already-running
        # helper. Its own redirected output must also handle Unicode paths.
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
    if a.cmd == 'check':
        print(json.dumps(windows_check(a.reuse_shaders) if a.windows or sys.platform == 'win32' else check(), indent=1))
        return 0
    if a.cmd == 'kit':
        print(copy_kit(KIT, a.dest))
        return 0
    python = a.python or (sys.executable if windows else find_python()[0])
    if not python:
        print('error: Python 3.11 or newer was not found; install it with: brew install python', file=sys.stderr)
        return 2
    kit = str(KIT)
    try:
        check_out(a.out, (str(KIT), a.kit))
        if a.import_dir and nested(a.out, a.import_dir):
            raise ValueError('the install folder must not overlap the imported game folder')
    except ValueError as e:
        print('error: ' + str(e), file=sys.stderr)
        return 2
    if a.kit:
        kit = str(a.kit)
    try:
        argv = build_argv(python, kit, a.nsp, a.keys, a.out, a.title_keys, a.fonts, a.fps, a.render_res,
                          a.import_dir, a.control_receipt, a.spirv_dir, a.jobs)
    except ValueError as e:
        print('error: ' + str(e), file=sys.stderr)
        return 2
    if a.to_stage:
        argv += ['--to-stage', a.to_stage]
    if a.dry_run:
        argv.append('--dry-run')
    env = windows_build_env(os.environ) if windows else build_env(os.environ)
    if a.cmd == 'command':
        names = ('PATH', 'PYTHONUTF8', 'PYTHONIOENCODING') if windows else ('PATH',)
        exported = {k: env[k] for k in names}
        print(json.dumps({'argv': argv, 'env': exported}, indent=1))
        return 0
    if a.kit and not a.dry_run:
        copy_kit(KIT, a.kit)
    if windows:
        if a.dry_run or a.to_stage:
            return subprocess.run(argv, env=env).returncode
        return windows_install(argv, kit, a.out, not a.no_desktop_shortcut)
    if not a.dry_run:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    print('$ ' + ' '.join(argv[2:]), flush=True)
    try:
        os.setpgrp()  # the setup app signals the whole build (compilers too) when the player cancels
    except OSError:
        pass
    os.execve(argv[0], argv, env)


if __name__ == '__main__':
    sys.exit(main())
