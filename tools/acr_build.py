#!/usr/bin/env python3
"""Build AC-Recomp from your own Astral Chain dump, on your own Mac.

    python3 tools/acr_build.py --nsp "Astral Chain.nsp" --keys prod.keys [--title-keys title.keys] \
        [--fonts <dir>] --out <dir>

The release holds none of the game's code or data. This script imports your dump, lifts the game's code to C++
with the pinned recompiler, translates the game's shaders to SPIR-V, prepares the pinned runtime with every
patch in runtime/patches/series.macos, builds it, lays out a data root and writes AC-Recomp.app.
Everything it produces is game-derived and stays in --out on your machine; never share it.

Stages run in order and are resumable: a finished stage is recorded in <out>/acr-state.json and skipped on the
next run. `--from-stage NAME` reruns NAME and everything after it, `--only NAME` runs one stage, `--dry-run`
prints what would run without touching anything, and `--list-stages` describes the stages.

Key files are passed to the importer by path only. This script never opens, prints, copies or hashes them.
Standard library only.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
sys.path.insert(0, str(TOOLS))

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
WONDER_URL = 'https://github.com/BelmanteGu/SuperMarioWonderRecomp.git'
RYUBING_URL = 'https://codeberg.org/Software_arch/Ryubing.git'
RYUBING_PIN = 'a82350bb774f70fcbd41c9987bf67a3775409963'
VULKAN_HEADERS_URL = 'https://github.com/KhronosGroup/Vulkan-Headers.git'
VULKAN_HEADERS_PIN = 'e3b1eec08173d6b825cd3ac88c885a63b621504a'  # v1.4.357
TITLE = '01007300020FA000'
# The recompiler's Python dependencies, as pinned for the lift (CPU-REGEN-020 used exactly these).
LIFT_PACKAGES = ('capstone==5.0.6', 'lz4==4.4.4', 'zstandard==0.24.0')
# Module load bases used by the runtime's loader (main first, sdk next 256 MiB slot).
MODULE_BASES = (('main', '0x4000000000'), ('sdk', '0x4010000000'))
CNMT_LAYOUTS = ('application-1.0.0-14.1.2-size48', 'application-15.0.0-16.1.0-size40-attributes0')
IMPORTER_SOURCES = ('nximport.cpp', 'nxcrypto.cpp', 'nximport_cli.cpp', 'nximport.h', 'nxcrypto.h')
IMPORTER_DIR = 'android/wonder/importer'
HARNESS_FILES = ('Program.cs', 'StaticGpuAccessor.cs')
# No MSBuild/compiler servers left running, and no NuGet vulnerability audit (network round trips that can stall).
DOTNET_BUILD_FLAGS = ('-c', 'Release', '-nologo', '-nodeReuse:false', '--disable-build-servers',
                      '-p:UseSharedCompilation=false', '-p:NuGetAudit=false')
# Shader keys whose correct product comes from a control variant, not the batch's tie-break
# (docs/ASTRAL_SHADER_FULL_INVENTORY.md: the runtime was observed using the other workgroup size).
PREFERRED_VARIANT = {'d5472b1deab3dd75'}

# The six shared-font slots, in pl type order (docs/ASTRAL_SHARED_FONT_SWKBD.md).
FONT_FILES = ('nintendo_udsg-r_std_003', 'nintendo_udsg-r_org_zh-cn_003', 'nintendo_udsg-r_ext_zh-cn_003',
              'nintendo_udjxh-db_zh-tw_003', 'nintendo_udsg-r_ko_003', 'nintendo_ext_003')
BFTTF_MAGIC = 0x18029A7F
BFTTF_KEY = 0x49621806
BFTTF_ALT = {0x1A879BD9: 0xA6018502}
FONT_LIMIT = 0x1100000
# Open-licensed replacement used when no firmware fonts are given: Noto Sans Regular (SIL OFL 1.1), static hinted TTF.
NOTO_COMMIT = '28b15b4b43b7bed62b5cf6e6b0b5ff5846270535'
NOTO_BASE = 'https://raw.githubusercontent.com/notofonts/notofonts.github.io/' + NOTO_COMMIT + '/fonts/'
REPLACEMENT_FONT = (NOTO_BASE + 'NotoSans/hinted/ttf/NotoSans-Regular.ttf',
                    '478c558ea716033cd60c03438f628dfa75694dcf6b5f6d505a2f05fd2b4f3823')
REPLACEMENT_LICENSE = (NOTO_BASE + 'LICENSE', 'f2095b08bed08b23a6fe26112fcd679a2bee3f002eef077eb05d215ed1051bd8')

# Strict NVN texture-format lookup needs NX_NVN_FORMAT_PROFILE (docs/MAC_NVN_TEXTURE.md): the module-relative offset,
# record count, stride, field offsets and flag mask of the SDK's format table, plus an FNV-1a-64 fingerprint of the
# table. These are facts about the SDK layout (like the function offsets the docs cite), not game content. The data
# stage writes the profile for the supported game version after checking the fingerprint against the player's own
# SDK image; --nvn-format-profile overrides it.
KNOWN_FORMAT_PROFILES = (
    # Astral Chain 1.0.0 (title 01007300020FA000), the version this project supports.
    ('Astral Chain 1.0.0', 'NX_FORMAT_PROFILE_V1\nb9c378 a1 30 8 9 10 0 1 d1dc14f416642ffd\n'),
)
PROFILE_MAGIC = 'NX_FORMAT_PROFILE_V1'


def fnv1a64(data):
    h = 14695981039346656037
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def parse_format_profile(text):
    tokens = text.split()
    require(len(tokens) == 10 and tokens[0] == PROFILE_MAGIC, 'not an NX_FORMAT_PROFILE_V1 file')
    try:
        values = [int(t, 16) for t in tokens[1:]]
    except ValueError:
        raise BuildError('the format profile has a non-hexadecimal value')
    keys = ('offset', 'count', 'stride', 'width', 'height', 'bytes', 'flags', 'mask', 'fingerprint')
    p = dict(zip(keys, values))
    require(0 < p['count'] <= 65536 and 0 < p['stride'] <= 4096 and 0 < p['mask'] <= 255 and
            max(p['width'], p['height'], p['bytes'], p['flags']) < p['stride'], 'invalid format profile geometry')
    return p


def check_format_profile(profile, sdk_image):
    """The profile's fingerprint must match the table in this SDK image (module-relative, as the runtime reads it)."""
    end = profile['offset'] + profile['count'] * profile['stride']
    require(end <= len(sdk_image), 'the format profile points outside this SDK')
    require(fnv1a64(sdk_image[profile['offset']:end]) == profile['fingerprint'],
            'the format profile does not match this game version (fingerprint mismatch)')


BREW_HINT = 'brew install cmake ninja pkg-config sdl3 opus molten-vk vulkan-headers spirv-tools zstd'
DOTNET_HINT = ('install the .NET 10 SDK: `brew install --cask dotnet-sdk`, or the macOS Arm64 installer from '
               'https://dotnet.microsoft.com/download/dotnet/10.0 (then open a new terminal)')

STAGES = (
    ('preflight', 'check the host tools and inputs; print install hints for anything missing'),
    ('workspace', 'create the private output workspace (a git repository that ignores everything)'),
    ('upstream', 'clone the pinned SuperMarioWonderRecomp runtime, importer, recompiler and shader harness'),
    ('toolchain', 'create a Python venv with the recompiler packages (and cmake/ninja when not installed)'),
    ('import', 'import your NSP with the pinned importer (ExeFS, metadata and RomFS)'),
    ('control', 'read the application control metadata (ratings, parental flags) from your NSP'),
    ('lift', 'recompile main and sdk to C++ with the pinned recompiler plus astral-sqshl.patch'),
    ('shaders', 'extract every shader from the RomFS and translate it to SPIR-V (.NET 10 SDK)'),
    ('runtime', 'prepare the pinned runtime and apply runtime/patches/series.macos'),
    ('build', 'configure and build the astral executable (CMake, Ninja, SDL3, Vulkan headers, libopus)'),
    ('fonts', 'install the six shared fonts (yours, or open-licensed replacements)'),
    ('data', 'lay out the data root (game files, SPIR-V, fonts, saves)'),
    ('app', 'write AC-Recomp.app and run-ac-recomp.sh'),
)
STAGE_NAMES = tuple(n for n, _ in STAGES)


class BuildError(Exception):
    """A precise, user-facing failure. The message says what is wrong and what to do."""


def require(ok, message):
    if not ok:
        raise BuildError(message)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def tree_digest(root, pattern='*'):
    """One SHA-256 over the relative names and contents of every file under root."""
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob(pattern)):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + b'\0' + sha256(p).encode() + b'\n')
    return h.hexdigest()


def read_series(path):
    names = []
    for line in Path(path).read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            require(re.fullmatch(r'[a-z0-9.-]+\.patch', line) is not None, f'bad patch name in {path}: {line}')
            names.append(line)
    require(names and len(set(names)) == len(names), f'empty or duplicated patch series: {path}')
    return names


# --- BFTTF -----------------------------------------------------------------------------------------------------------
def bswap(v):
    return int.from_bytes(v.to_bytes(4, 'little'), 'big')


def encode_bfttf(ttf, key=BFTTF_KEY):
    """Wrap a TrueType/OpenType file the way the firmware stores shared fonts (and the runtime decodes them)."""
    require(ttf[:4] in (b'\0\1\0\0', b'OTTO', b'true'), 'not a TrueType/OpenType font')
    body = ttf + b'\0' * (-len(ttf) % 4)
    words = struct.unpack(f'<{len(body) // 4}I', body)
    head = struct.pack('<II', bswap(bswap(BFTTF_MAGIC) ^ key), bswap(len(ttf) ^ key))
    return head + struct.pack(f'<{len(words)}I', *(w ^ bswap(key) for w in words))


def decode_bfttf(data):
    require(len(data) >= 8, 'file too small for a BFTTF header')
    w0, w1 = struct.unpack_from('<II', data)
    key = BFTTF_ALT.get(w0, BFTTF_KEY)
    require(bswap(w0) ^ key == bswap(BFTTF_MAGIC), 'not a BFTTF font (bad magic)')
    size = bswap(w1) ^ key
    require(0 < size <= len(data) - 8, 'BFTTF size does not fit the file')
    body = data[8:8 + size + (-size % 4)]
    body += b'\0' * (-len(body) % 4)
    words = struct.unpack(f'<{len(body) // 4}I', body)
    ttf = struct.pack(f'<{len(words)}I', *(w ^ bswap(key) for w in words))[:size]
    require(ttf[:4] in (b'\0\1\0\0', b'OTTO', b'true'), 'BFTTF does not decode to a TrueType/OpenType font')
    return ttf


# --- execution context -----------------------------------------------------------------------------------------------
class Context:
    def __init__(self, args, root=ROOT, out=sys.stdout):
        self.a, self.root, self.stream = args, Path(root), out
        self.dry = args.dry_run
        o = Path(os.path.abspath(args.out))
        self.out = o
        self.private = o / '.local/game-private'
        self.import_dir = self.private / 'astral'
        self.work = o / 'work'
        self.logs = o / 'logs'
        self.upstream = self.work / 'upstream/SuperMarioWonderRecomp'
        self.venv = self.work / 'venv'
        self.lift_src = self.work / 'lift/source'
        self.gen = self.work / 'gen'
        self.gen_variant = self.work / f'gen-{VARIANT}'  # the second lift of main (both frame rates)
        self.variant_list = self.work / f'runtime/main-{VARIANT}.list'
        self.control = self.work / 'control'
        self.shader_tools = self.work / 'shader-tools'
        self.shaders = self.work / 'shaders'
        self.runtime_src = self.work / 'runtime/source'
        self.build_dir = self.work / 'runtime/build'
        self.deps = self.work / 'deps'
        self.data = o / 'data'
        self.app = o / 'AC-Recomp.app'
        self.state_path = o / 'acr-state.json'
        self.state = {}
        if self.state_path.is_file():
            self.state = json.loads(self.state_path.read_text())
        self.commands = []

    # Output -----------------------------------------------------------------------------------------------------
    def say(self, text):
        print(text, file=self.stream, flush=True)

    def step(self, text):
        self.say('  - ' + text)

    # Commands ---------------------------------------------------------------------------------------------------
    def run(self, argv, cwd=None, env=None, log=None, timeout=None, check=True, capture=False):
        argv = [str(x) for x in argv]
        self.commands.append(argv)
        shown = ' '.join(shlex.quote(x) for x in argv)
        self.say(('    would run: ' if self.dry else '    $ ') + shown + (f'   (in {cwd})' if cwd else ''))
        if self.dry:
            return ''
        full_env = None if env is None else {**os.environ, **env}
        if log:
            log = Path(log)
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('w') as f:
                f.write('$ ' + shown + '\n')
                f.flush()
                p = subprocess.run(argv, cwd=cwd, env=full_env, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                   timeout=timeout)
            if check and p.returncode:
                tail = ''.join(log.read_text(errors='replace').splitlines(True)[-25:])
                raise BuildError(f'command failed (exit {p.returncode}): {shown}\n--- last lines of {log} ---\n{tail}')
            return log.read_text(errors='replace')
        p = subprocess.run(argv, cwd=cwd, env=full_env, timeout=timeout, text=True, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.STDOUT if capture else None)
        if check and p.returncode:
            raise BuildError(f'command failed (exit {p.returncode}): {shown}' +
                             ('\n' + p.stdout[-4000:] if capture and p.stdout else ''))
        return p.stdout if capture else ''

    # Filesystem (no-ops in dry-run) ------------------------------------------------------------------------------
    def mkdir(self, path):
        if self.dry:
            self.say(f'    would create {path}/')
        else:
            Path(path).mkdir(parents=True, exist_ok=True)

    def rmtree(self, path):
        path = Path(path)
        require(path.is_relative_to(self.out) and path != self.out, f'refusing to delete outside --out: {path}')
        user = self.data / 'user'  # the player's saves: never deleted, nor anything that holds them
        require(not (user.is_relative_to(path) or path.is_relative_to(user)), f'refusing to delete saves: {path}')
        if path.is_symlink() or path.exists():
            if self.dry:
                self.say(f'    would remove {path}')
            elif path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)

    def write(self, path, data, mode=None):
        if self.dry:
            self.say(f'    would write {path}')
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name('.' + path.name + '.tmp')
        tmp.write_bytes(data.encode() if isinstance(data, str) else data)
        if mode is not None:
            tmp.chmod(mode)
        tmp.replace(path)

    def copy(self, src, dst):
        if self.dry:
            self.say(f'    would copy {src} -> {dst}')
            return
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def symlink(self, target, link):
        if self.dry:
            self.say(f'    would link {link} -> {target}')
            return
        link = Path(link)
        if link.is_symlink():
            link.unlink()
        require(not link.exists(), f'{link} exists and is not a link; move it away')
        link.symlink_to(target)

    # State ------------------------------------------------------------------------------------------------------
    def done(self, stage):
        return stage in self.state.get('stages', {})

    def record(self, stage, evidence):
        if self.dry:
            return
        stages = self.state.setdefault('stages', {})
        stages[stage] = {'done_utc': utc(), **(evidence or {})}
        self.state.update(schema=1, pin=PIN)
        self.write(self.state_path, json.dumps(self.state, indent=2, sort_keys=True) + '\n')

    def forget(self, stage):
        if self.state.get('stages', {}).pop(stage, None) is not None and not self.dry:
            self.write(self.state_path, json.dumps(self.state, indent=2, sort_keys=True) + '\n')

    # Tools ------------------------------------------------------------------------------------------------------
    def venv_python(self):
        return self.venv / 'bin/python'

    def tool(self, name):
        """A host tool from --<name>, PATH, Homebrew, or the build venv (cmake/ninja)."""
        explicit = getattr(self.a, name.replace('-', '_'), None)
        if explicit:
            return str(explicit)
        found = shutil.which(name)
        if found:
            return found
        for d in (self.venv / 'bin', Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
            if (d / name).is_file() and os.access(d / name, os.X_OK):
                return str(d / name)
        return None

    def brew_prefix(self):
        if self.a.prefix:
            return Path(self.a.prefix)
        for p in (Path('/opt/homebrew'), Path('/usr/local')):
            if (p / 'lib/cmake/SDL3').is_dir():
                return p
        return Path('/opt/homebrew')

    def vulkan_include(self):
        if self.a.vulkan_include:
            return Path(self.a.vulkan_include)
        for p in (self.brew_prefix() / 'include', self.deps / 'Vulkan-Headers/include'):
            if (p / 'vulkan/vulkan.h').is_file():
                return p
        return self.deps / 'Vulkan-Headers/include'

    def moltenvk(self):
        if self.a.moltenvk:
            return Path(self.a.moltenvk)
        candidates = [self.brew_prefix() / 'lib/libMoltenVK.dylib', Path('/usr/local/lib/libMoltenVK.dylib')]
        candidates += sorted(Path.home().glob('VulkanSDK/*/macOS/lib/libMoltenVK.dylib'), reverse=True)
        return next((p for p in candidates if p.is_file()), None)

    def dotnet(self):
        exe = self.tool('dotnet')
        if not exe:
            for p in (Path('/usr/local/share/dotnet/dotnet'), Path.home() / '.dotnet/dotnet'):
                if p.is_file():
                    return str(p)
        return exe

    def jobs(self):
        return self.a.jobs or default_jobs(host_cpus(), available_memory())


# --- host resources and the compile watchdog -------------------------------------------------------------------------
GIB = 1 << 30
JOB_MEMORY = 6 * GIB      # per compiler: the lifted translation units are large
MAX_JOBS = 8
LOW_MEMORY = 4 * GIB      # back off below this much available memory
WATCH_SECONDS = 5


def _sysctl(name):
    try:
        return int(subprocess.check_output(['sysctl', '-n', name], stderr=subprocess.DEVNULL, timeout=10))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def host_cpus():
    """Cores worth using: macOS performance cores (falling back to physical cores); elsewhere the usable CPUs."""
    if sys.platform == 'darwin':
        return _sysctl('hw.perflevel0.physicalcpu') or _sysctl('hw.physicalcpu') or os.cpu_count() or 1
    if hasattr(os, 'sched_getaffinity'):
        return len(os.sched_getaffinity(0)) or 1
    return os.cpu_count() or 1


def parse_vm_stat(text):
    page = int(re.search(r'page size of (\d+) bytes', text).group(1))
    pages = {k.strip().lower(): int(v) for k, v in re.findall(r'^([^:\n]+):\s+(\d+)\.?$', text, re.M)}
    return page * sum(pages.get(k, 0) for k in ('pages free', 'pages inactive', 'pages purgeable',
                                                 'pages speculative'))


def parse_meminfo(text):
    m = re.search(r'^MemAvailable:\s+(\d+) kB', text, re.M)
    return int(m.group(1)) * 1024 if m else None


def available_memory():
    """Memory available to new processes (macOS: free+inactive+purgeable+speculative pages; Linux: MemAvailable)."""
    try:
        if sys.platform == 'darwin':
            return parse_vm_stat(subprocess.check_output(['vm_stat'], text=True, timeout=10))
        return parse_meminfo(Path('/proc/meminfo').read_text())
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        return None


def default_jobs(cpus, memory):
    """min(half the performance cores, available memory / 6 GiB, 8), at least 1."""
    by_memory = MAX_JOBS if memory is None else memory // JOB_MEMORY
    return max(1, min((cpus or 2) // 2, by_memory, MAX_JOBS))


def memory_pressure():
    """'normal', 'warning', 'critical', or None when the host does not say."""
    if sys.platform == 'darwin':
        return {1: 'normal', 2: 'warning', 4: 'critical'}.get(_sysctl('kern.memorystatus_vm_pressure_level'))
    try:
        text = Path('/proc/pressure/memory').read_text()
    except OSError:
        return None
    m = re.search(r'^some avg10=([0-9.]+)', text, re.M)
    if not m:
        return None
    avg = float(m.group(1))
    return 'critical' if avg >= 40 else 'warning' if avg >= 10 else 'normal'


def should_back_off(pressure, available):
    return pressure in ('warning', 'critical') or (available is not None and available < LOW_MEMORY)


def low_priority(argv):
    """Run the compile at nice 10 so the desktop stays responsive."""
    return (['nice', '-n', '10'] if shutil.which('nice') else []) + list(argv)


def watched_build(ctx, make_argv, jobs, log, env=None, probe=None, interval=WATCH_SECONDS):
    """Run the build; under memory pressure (or < 4 GiB available) stop it and resume with half the jobs.

    Ninja resumes incrementally, so a restart repeats no finished work. Returns the job count it ended with.
    """
    import signal
    probe = probe or (lambda: (memory_pressure(), available_memory()))
    full_env = None if env is None else {**os.environ, **env}
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a') as f:
        while True:
            argv = [str(x) for x in low_priority(make_argv(jobs))]
            f.write('$ ' + ' '.join(shlex.quote(x) for x in argv) + '\n')
            f.flush()
            p = subprocess.Popen(argv, env=full_env, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            backed_off = False
            try:
                while True:
                    try:
                        p.wait(timeout=interval)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    pressure, available = probe()
                    if jobs > 1 and should_back_off(pressure, available):
                        shown = 'unknown' if available is None else f'{available / GIB:.1f} GiB'
                        note = (f'memory pressure {pressure or "unknown"}, {shown} available: stopping the build '
                                f'and resuming with {jobs // 2} jobs instead of {jobs}')
                        ctx.step(note)
                        f.write('acr_build: ' + note + '\n')
                        f.flush()
                        os.killpg(p.pid, signal.SIGTERM)
                        try:
                            p.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            os.killpg(p.pid, signal.SIGKILL)
                            p.wait()
                        jobs, backed_off = jobs // 2, True
                        break
            except BaseException:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                raise
            if backed_off:
                continue
            if p.returncode:
                tail = ''.join(log.read_text(errors='replace').splitlines(True)[-25:])
                raise BuildError(f'the build failed (exit {p.returncode}); last lines of {log}:\n{tail}')
            return jobs


# --- stages ----------------------------------------------------------------------------------------------------------
def git_head(path):
    p = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def stage_preflight(ctx):
    a, problems, notes = ctx.a, [], []
    if sys.version_info < (3, 11):
        problems.append(f'Python 3.11 or newer is required (this is {platform.python_version()}): '
                        'brew install python, then run the script with python3 from Homebrew.')
    if sys.platform != 'darwin':
        problems.append('Only macOS (Apple silicon) is supported by this build script for now.')
    elif platform.machine() != 'arm64':
        notes.append('This is not an Apple silicon Mac; only arm64 has been tested.')
    for path, what in ((a.nsp, '--nsp'), (a.keys, '--keys'), (a.title_keys, '--title-keys')):
        if path is None:
            continue
        p = Path(path)
        if not p.is_file():
            problems.append(f'{what}: no such file: {p}')
        elif what == '--nsp' and p.stat().st_size < 1 << 20:
            problems.append(f'{what}: {p} is too small to be a game dump.')
    if a.nsp and Path(a.nsp).suffix.lower() != '.nsp':
        problems.append('--nsp: only NSP dumps are supported (convert an XCI to NSP first).')
    if a.fonts and not Path(a.fonts).is_dir():
        problems.append(f'--fonts: not a directory: {a.fonts}')
    for name in ('git', 'clang++', 'patch', 'curl'):
        if not ctx.tool(name):
            problems.append(f'`{name}` was not found. Install the Xcode command-line tools: xcode-select --install')
    if not ctx.tool('pkg-config') and not ctx.tool('pkgconf'):
        problems.append(f'`pkg-config` was not found. {BREW_HINT}')
    else:
        pc = ctx.tool('pkg-config') or ctx.tool('pkgconf')
        if subprocess.run([pc, '--exists', 'opus >= 1.3'], capture_output=True).returncode:
            problems.append(f'libopus (pkg-config `opus >= 1.3`) was not found. {BREW_HINT}')
    prefix = ctx.brew_prefix()
    if not (prefix / 'lib/cmake/SDL3').is_dir():
        problems.append(f'SDL3 was not found under {prefix} (looked for lib/cmake/SDL3). {BREW_HINT}, '
                        'or pass --prefix <SDL3 install prefix>.')
    if not ctx.moltenvk():
        problems.append(f'MoltenVK (libMoltenVK.dylib) was not found. {BREW_HINT}, or pass --moltenvk <path>.')
    if not (ctx.vulkan_include() / 'vulkan/vulkan.h').is_file():
        notes.append('Vulkan headers not installed; the build will fetch the pinned Vulkan-Headers v1.4.357.')
    for name in ('cmake', 'ninja'):
        if not ctx.tool(name):
            notes.append(f'`{name}` not installed; it will be installed into the build venv with pip.')
    if not a.skip_shaders:
        dotnet = ctx.dotnet()
        sdks = subprocess.run([dotnet, '--list-sdks'], capture_output=True, text=True).stdout if dotnet else ''
        if not re.search(r'^10\.', sdks, re.M):
            problems.append('The .NET 10 SDK is needed to build the shader translator: ' + DOTNET_HINT + '.')
        if not a.no_shader_validation and not ctx.tool('spirv-val'):
            problems.append(f'`spirv-val` (SPIRV-Tools) was not found. {BREW_HINT}, '
                            'or pass --no-shader-validation.')
        import ctypes.util
        if not ctypes.util.find_library('zstd') and not (prefix / 'lib/libzstd.dylib').is_file():
            problems.append(f'libzstd was not found (the shader extractor needs it). {BREW_HINT}')
    out_parent = ctx.out if ctx.out.exists() else ctx.out.parent
    while not out_parent.exists():
        out_parent = out_parent.parent
    free = shutil.disk_usage(out_parent).free
    need = (Path(a.nsp).stat().st_size if a.nsp and Path(a.nsp).is_file() else 10 << 30) + (12 << 30)
    if free < need and not ctx.done('import'):
        problems.append(f'Not enough free disk space at {out_parent}: {free >> 30} GiB free, about '
                        f'{need >> 30} GiB needed.')
    for n in notes:
        ctx.step(n)
    if problems and ctx.dry:
        ctx.say('    the real run would stop here:\n' + '\n'.join('    * ' + p for p in problems))
    elif problems:
        raise BuildError('preflight found problems:\n' + '\n'.join('  * ' + p for p in problems))
    else:
        ctx.step('host tools and inputs look good')
    return {'python': platform.python_version(), 'machine': platform.machine()}


def stage_workspace(ctx):
    ctx.mkdir(ctx.out)
    ctx.mkdir(ctx.private)
    ctx.mkdir(ctx.work)
    ctx.mkdir(ctx.logs)
    if not (ctx.out / '.git').exists():
        ctx.run(['git', 'init', '-q', ctx.out])
    # The importer insists on writing below an ignored .local/game-private of a git repository; this repository
    # exists only for that check and ignores everything, so nothing here can be committed by accident.
    ctx.write(ctx.out / '.gitignore', '# AC-Recomp private build workspace: game-derived, never commit or share.\n*\n')
    ctx.write(ctx.out / 'README-PRIVATE.txt',
              'Everything in this directory is derived from your own game dump. Do not share or upload it.\n')
    return {}


def stage_upstream(ctx):
    if ctx.upstream.exists() and git_head(ctx.upstream) == PIN:
        ctx.step(f'pinned upstream already present at {ctx.upstream}')
        return {'pin': PIN}
    ctx.rmtree(ctx.upstream)
    source = ctx.a.reference or WONDER_URL
    ctx.run(['git', 'clone', '--no-checkout', source, ctx.upstream])
    ctx.run(['git', '-C', ctx.upstream, 'checkout', '-q', '--detach', PIN])
    if not ctx.dry:
        require(git_head(ctx.upstream) == PIN, f'upstream checkout is not at the pinned revision {PIN}')
    return {'pin': PIN}


def stage_toolchain(ctx):
    py = ctx.a.lift_python or sys.executable
    if not ctx.venv_python().exists():
        ctx.run([py, '-m', 'venv', ctx.venv])
    pkgs = list(LIFT_PACKAGES)
    pkgs += [n for n in ('cmake', 'ninja') if not (shutil.which(n) or getattr(ctx.a, n, None))]
    ctx.run([ctx.venv_python(), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', *pkgs],
            log=ctx.logs / 'pip.log')
    probe = ("import capstone,lz4,zstandard,json;"
             "print(json.dumps([capstone.__version__,lz4.__version__,zstandard.__version__]))")
    got = ctx.run([ctx.venv_python(), '-c', probe], capture=True)
    if not ctx.dry:
        want = [p.split('==')[1] for p in LIFT_PACKAGES]
        require(json.loads(got.strip().splitlines()[-1]) == want, f'recompiler packages are not {want}: {got}')
    return {'packages': list(LIFT_PACKAGES)}


IMPORT_ERRORS = {
    'not_single_regular_file': 'a key file or the dump is not a plain file (no symlinks or hard links)',
    'importer_failed_resume_same_command': 'the importer failed; check that prod.keys matches your console '
                                           'firmware (and pass --title-keys if your dump needs it), then rerun',
    'dump_hash_mismatch': 'the NSP changed since the import started; use the same file or a new --out',
    'dump_size_mismatch': 'the NSP changed since the import started; use the same file or a new --out',
    'reference_revision_mismatch': 'the upstream checkout is not at the pinned revision; rerun --from-stage upstream',
    'unowned_outputs_refused': 'the import directory holds files from something else; use a new --out',
    'wrapper_already_running': 'another import is running in this --out',
    'title_mismatch': 'this dump is not Astral Chain (title 01007300020FA000)',
}


def stage_import(ctx):
    a = ctx.a
    cmd = [sys.executable, ctx.root / 'tools/import_owned_dump.py', '--repo', ctx.out, '--reference', ctx.upstream,
           '--dump', Path(a.nsp).resolve(), '--prod-keys', Path(a.keys).resolve(), '--out', ctx.import_dir,
           '--expected-title', TITLE]
    if a.title_keys:
        cmd[cmd.index('--out'):cmd.index('--out')] = ['--title-keys', Path(a.title_keys).resolve()]
    ctx.step('importing (hashes and decrypts the whole NSP; several minutes)')
    p_out = ''
    try:
        p_out = ctx.run(cmd, log=ctx.logs / 'import.log')
    except BuildError:
        text = (ctx.logs / 'import.log').read_text(errors='replace') if (ctx.logs / 'import.log').exists() else ''
        m = re.search(r'"error": "([a-z_0-9]+)"', text)
        code = m.group(1) if m else 'unknown'
        raise BuildError(f'import failed ({code}): {IMPORT_ERRORS.get(code, "see " + str(ctx.logs / "import.log"))}')
    if ctx.dry:
        return {}
    import prepare_runtime as prep
    _, manifest_sha = prep.validate_inputs(ctx.import_dir)
    require((ctx.import_dir / 'extract/romfs').is_dir(), 'the import has no extract/romfs')
    return {'manifest_sha256': manifest_sha, 'log_tail': p_out.strip().splitlines()[-1][:300] if p_out else ''}


def stage_control(ctx):
    a = ctx.a
    src = ctx.control / 'src'
    run_dir = ctx.control / 'out'
    ctx.rmtree(ctx.control)
    importer = src / IMPORTER_DIR
    ctx.mkdir(importer)
    for name in IMPORTER_SOURCES:
        ctx.copy(ctx.upstream / IMPORTER_DIR / name, importer / name)
    ctx.run(['git', 'init', '-q', src])
    ctx.run(['git', '-C', src, 'apply', ctx.root / 'runtime/patches/astral-control-import.patch'])
    tool = ctx.control / 'nxcontrol'
    ctx.run(['clang++', '-std=c++17', '-O2', importer / 'nximport.cpp', importer / 'nxcrypto.cpp',
             importer / 'nximport_cli.cpp', '-o', tool], log=ctx.logs / 'control-build.log')
    ctx.mkdir(run_dir)
    keys = [Path(a.keys).resolve()] + ([Path(a.title_keys).resolve()] if a.title_keys else [])
    # Only the native reader opens the keys; its output is discarded (it may name key slots).
    ctx.say('    $ ' + str(tool) + ' --out ' + str(run_dir) + ' --control-metadata <keys> <nsp>')
    if ctx.dry:
        return {}
    with (ctx.logs / 'control.log').open('w') as f:
        rc = subprocess.run([str(tool), '--out', str(run_dir), '--control-metadata', *map(str, keys),
                             str(Path(a.nsp).resolve())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=1800).returncode
        f.write(f'exit {rc}\n')
    require(rc == 0, 'reading the control metadata failed; check prod.keys (and --title-keys) and rerun '
                     '--from-stage control')
    import extract_control_metadata as cm
    manifest = json.loads((ctx.import_dir / '.wrapper/manifest.json').read_text())
    binding, errors = None, []
    for layout in CNMT_LAYOUTS:
        try:
            binding = cm.link_metadata(run_dir, manifest, layout=layout)
            break
        except (cm.Failure, ValueError, KeyError, struct.error) as e:
            errors.append(f'{layout}: {e}')
    require(binding is not None, 'the control metadata did not parse: ' + '; '.join(errors))
    receipt = {'schema': 1, 'producer': 'tools/acr_build.py', 'status': 'produced', 'metadata_produced': True,
               'linkage_verified': True, 'binding': binding}
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    ctx.write(ctx.control / 'receipt.json', raw)
    return {'receipt_sha256': hashlib.sha256(raw).hexdigest(), 'cnmt_layout': binding['cnmt_layout'],
            'version': binding['version']}


def fps_choice(args):
    """--fps, else NX_FPS in the build's environment; None (the default) builds both frame rates."""
    return str(args.fps or os.environ.get('NX_FPS') or '') or None


def fps60(args):
    """--fps 60 (or NX_FPS=60 in the build's environment): the one executable is the 60 fps lift
    (docs/ASTRAL_60FPS.md)."""
    return fps_choice(args) == '60'


def both_fps(args):
    """No --fps / NX_FPS: build astral (30 fps) and astral-60fps from a second lift of main; the launcher's Frame rate
    setting picks one."""
    return fps_choice(args) is None


VARIANT = '60fps'  # the second executable: astral-60fps (runtime/patches/astral-fps-variant.patch)


def variant_built(ctx):
    """Both frame rates were asked for and the lift made the 60 fps main (a main other than 1.0.0 builds 30 only)."""
    return both_fps(ctx.a) and (ctx.dry or (ctx.gen_variant / 'main').is_dir())


def single_fps(ctx):
    """The one frame rate of a one-rate build ('30' or '60'), '' with both (the launcher shows it: NX_SINGLE_FPS)."""
    return '' if variant_built(ctx) else ('60' if fps60(ctx.a) else '30')


def lift_input_fps60(ctx):
    """A copy of the player's main with the five 60 fps sites patched, verified word by word first. It is
    game-derived and stays in the private work directory; the runtime still loads the unpatched exefs/main."""
    import astral_fps60
    src = ctx.import_dir / 'exefs/main'
    dst = ctx.work / 'lift-fps60/main'
    ctx.step(f'60 fps: patching {len(astral_fps60.SITES)} instructions of main for the lift')
    if ctx.dry:
        return dst
    try:
        data = astral_fps60.patch(src.read_bytes())
    except astral_fps60.PatchError as e:
        raise BuildError(f'--fps 60: {e}') from None
    ctx.write(dst, data)
    return dst


def lift_module(ctx, name, base, src, gen, log):
    """Lift one module into gen/<name>, keeping identical files (sync_tree); its evidence."""
    env = {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONHASHSEED': '0'}
    fresh = gen / (name + '.new')
    ctx.rmtree(fresh)
    ctx.mkdir(gen)
    ctx.step(f'lifting {name}{" (60 fps)" if gen == ctx.gen_variant else ""} (a minute or two)')
    ctx.run([ctx.venv_python(), '-m', 'recomp', src, fresh, '--name', name, '--base', base], cwd=ctx.lift_src,
            env=env, log=log)
    if ctx.dry:
        return None
    kept = sync_tree(fresh, gen / name)
    ctx.rmtree(fresh)
    report = (gen / name / 'report.txt').read_text()
    m = re.match(r'functions (\d+), handled (\d+), unhandled (\d+)', report)
    require(m is not None, f'the {name} lift wrote no report; see {log}')
    if int(m.group(3)):
        ctx.step(f'WARNING: {name} has {m.group(3)} unhandled instructions (they abort if reached)')
    ctx.step(f'{name}: {m.group(0)}')
    return {'report': m.group(0), 'files': len(list((gen / name).iterdir())), 'unchanged_files_kept': kept,
            'tree_sha256': tree_digest(gen / name)}


def stage_lift(ctx):
    ctx.rmtree(ctx.lift_src)
    ctx.run(['git', 'clone', '-q', '--no-hardlinks', '--no-checkout', ctx.upstream, ctx.lift_src])
    ctx.run(['git', '-C', ctx.lift_src, 'checkout', '-q', '--detach', PIN])
    patch = ctx.root / 'runtime/patches/astral-sqshl.patch'
    ctx.run(['git', '-C', ctx.lift_src, 'apply', '--check', patch])
    ctx.run(['git', '-C', ctx.lift_src, 'apply', patch])
    evidence = {}
    inputs = {name: ctx.import_dir / 'exefs' / name for name, _ in MODULE_BASES}
    # Each patch checks its own original words; they touch disjoint sites, so they apply in sequence to one copy.
    if fps60(ctx.a):
        inputs['main'] = lift_input_fps60(ctx)
        evidence['fps'] = 60
    if ctx.a.render_res:
        inputs['main'] = render_res_input(ctx, inputs['main'])
        evidence['render_res'] = ctx.render_res_evidence
    for name, base in MODULE_BASES:
        ev = lift_module(ctx, name, base, inputs[name], ctx.gen, ctx.logs / f'lift-{name}.log')
        if ev:
            evidence[name] = ev
    # Both frame rates (the default): a second lift of main only. The build compiles just the files that differ.
    src = None
    if both_fps(ctx.a):
        try:
            src = lift_input_fps60(ctx)
        except BuildError as e:  # not Astral Chain 1.0.0: the 30 fps build alone, as with --fps 30
            ctx.step(f'NOTE: no 60 fps binary: {e}. Building 30 fps only (pass --fps 30 to skip this check).')
            evidence['fps'] = 30
            evidence['fps60_unavailable'] = str(e)
    if src is None:
        ctx.rmtree(ctx.gen_variant)
    else:
        evidence['fps'] = '30+60'
        if ctx.a.render_res:
            src = render_res_input(ctx, src, 'render-res-60fps')
        ev = lift_module(ctx, 'main', dict(MODULE_BASES)['main'], src, ctx.gen_variant,
                         ctx.logs / f'lift-main-{VARIANT}.log')
        if ev:
            evidence[f'main_{VARIANT}'] = ev
    if not ctx.dry:
        import prepare_runtime as prep
        manifest, _ = prep.validate_inputs(ctx.import_dir)
        prep.generated_evidence(ctx.gen, manifest)  # bases and module extents agree with the import
    return evidence


def sync_tree(src, dst):
    """Move src's files into dst, keeping dst's identical files untouched (their mtimes stay, so a relift that changes
    a few functions, such as --render-res, recompiles only those files). Files not in src are removed."""
    dst.mkdir(parents=True, exist_ok=True)
    names = {p.name for p in src.iterdir()}
    kept = 0
    for old in dst.iterdir():
        if old.name not in names:
            shutil.rmtree(old) if old.is_dir() and not old.is_symlink() else old.unlink()
    for name in sorted(names):
        new, old = src / name, dst / name
        if old.is_file() and new.is_file() and old.stat().st_size == new.stat().st_size and \
                old.read_bytes() == new.read_bytes():
            kept += 1
            continue
        if old.exists():
            shutil.rmtree(old) if old.is_dir() and not old.is_symlink() else old.unlink()
        os.replace(new, old)
    return kept


def render_res_input(ctx, src, work_dir='render-res'):
    """src (exefs/main, or the 60 fps copy) with the docked render size patched (tools/astral_render_res.py,
    docs/ASTRAL_RENDER_RES.md), written to <work>/<work_dir>/main."""
    import astral_render_res as rr
    try:
        w, h = rr.parse_res(ctx.a.render_res)
    except rr.PatchError as e:
        raise BuildError(str(e))
    dst = ctx.work / work_dir / 'main'
    ctx.step(f'patching main for a {w}x{h} internal resolution (checks every original instruction first)')
    ctx.render_res_evidence = {'resolution': f'{w}x{h}'}
    if ctx.dry:
        return dst
    try:
        ev = rr.patch_file(src, dst, w, h, ctx.a.graphics_memory_mib)
    except (rr.PatchError, OSError) as e:
        raise BuildError(f'--render-res: {e}')
    ctx.render_res_evidence = {k: ev[k] for k in ('resolution', 'graphics_memory_mib', 'sites', 'output_sha256')}
    return dst


def stage_shaders(ctx):
    if ctx.a.skip_shaders:
        ctx.step('skipped (--skip-shaders); the game will not render without translated shaders')
        return {'skipped': True}
    dotnet = ctx.dotnet()
    require(dotnet or ctx.dry, 'dotnet was not found: ' + DOTNET_HINT)
    dotnet = dotnet or 'dotnet'
    denv = {'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1',
            'DOTNET_NOLOGO': '1', 'NUGET_PACKAGES': str(ctx.shader_tools / 'nuget')}
    wonder = ctx.shader_tools / 'wonder'
    ryubing = wonder / 'private/third_party/ryubing'
    # 1. The upstream translator (Ryubing's Ryujinx.Graphics.Shader with Wonder's patches).
    if not (wonder.exists() and git_head(wonder) == PIN):
        ctx.rmtree(wonder)
        ctx.run(['git', 'clone', '-q', '--no-hardlinks', '--no-checkout', ctx.upstream, wonder])
        ctx.run(['git', '-C', wonder, 'checkout', '-q', '--detach', PIN])
    if not (ryubing.exists() and git_head(ryubing) == RYUBING_PIN):
        ctx.rmtree(ryubing)
        ctx.mkdir(ryubing)
        ctx.run(['git', '-C', ryubing, 'init', '-q'])
        ctx.run(['git', '-C', ryubing, 'fetch', '-q', '--depth', '1', ctx.a.ryubing or RYUBING_URL, RYUBING_PIN],
                log=ctx.logs / 'ryubing-fetch.log')
        ctx.run(['git', '-C', ryubing, 'checkout', '-q', '--detach', 'FETCH_HEAD'])
    ctx.step('building the shader translator (first build restores NuGet packages)')
    ctx.run([dotnet, 'build', wonder / 'tools/maxwell/spirv_harness/SpirvHarness.csproj', *DOTNET_BUILD_FLAGS],
            env=denv, log=ctx.logs / 'translator-build.log')
    translator = wonder / 'private/build/spirv_harness/bin/Release/net10.0'
    # 2. The Astral harness: upstream Program.cs + StaticGpuAccessor.cs with astral-headerless-compute.patch.
    hsrc, hbuild = ctx.shader_tools / 'harness-src', ctx.shader_tools / 'harness'
    ctx.rmtree(hsrc)
    ctx.mkdir(hsrc)
    for name in HARNESS_FILES:
        ctx.copy(wonder / 'tools/maxwell/spirv_harness' / name, hsrc / name)
    ctx.run(['patch', '-p1', '--forward', '-d', hsrc, '-i',
             ctx.root / 'tools/astral_spirv_harness/astral-headerless-compute.patch'])
    ctx.run([dotnet, 'build', ctx.root / 'tools/astral_spirv_harness/AstralSpirvHarness.csproj', *DOTNET_BUILD_FLAGS,
             f'-p:HarnessSourceDir={hsrc}', f'-p:TranslatorDir={translator}',
             f'-p:BaseIntermediateOutputPath={hbuild}/obj/', f'-p:BaseOutputPath={hbuild}/bin/'],
            env=denv, log=ctx.logs / 'harness-build.log')
    harness = hbuild / 'bin/Release/net10.0/astral_spirv_harness.dll'
    # 3. Extract every shader wrapper from the RomFS.
    extract = ctx.shaders / 'extract'
    ctx.rmtree(ctx.shaders)
    zenv = {'DYLD_FALLBACK_LIBRARY_PATH': f'{ctx.brew_prefix()}/lib:/usr/local/lib:/usr/lib'}
    jobs = str(min(8, ctx.jobs() * 2))
    ctx.step('extracting shaders from the RomFS')
    ctx.run([sys.executable, '-I', ctx.root / 'tools/astral_shader_full_inventory.py', 'extract',
             '--input', ctx.import_dir / 'extract/romfs', '--out', extract, '--jobs', jobs],
            env=zenv, log=ctx.logs / 'shader-extract.log')
    # 4. Translate the batch and every control variant.
    val = [] if ctx.a.no_shader_validation else ['--spirv-val', ctx.tool('spirv-val') or 'spirv-val']
    if ctx.a.no_shader_validation:
        val = ['--no-val']
    batches = [('out', extract / 'batch')]
    if not ctx.dry and (extract / 'variants').is_dir():
        batches += [(f'out-variant-{p.name}', p) for p in sorted((extract / 'variants').iterdir()) if p.is_dir()]
    for out_name, batch in batches:
        ctx.step(f'translating {batch.relative_to(extract) if not ctx.dry else batch.name}')
        ctx.run([dotnet, harness, '--batch', batch, '--out', ctx.shaders / out_name, '--astral-headerless-compute',
                 '--target-env', 'vulkan1.2', '--jobs', jobs, *val], env=denv,
                log=ctx.logs / f'shader-{out_name}.log')
    if ctx.dry:
        return {}
    return assemble_spirv(ctx, [ctx.shaders / n for n, _ in batches], ctx.shaders / 'spirv')


def read_results(path):
    with Path(path).open(newline='') as f:
        rows = list(csv.reader(f, delimiter='\t'))
    require(rows and rows[0][:1] == ['hash'], f'unexpected results header in {path}')
    return rows[0], {r[0]: r for r in rows[1:] if r}


def assemble_spirv(ctx, outs, final):
    """Batch products, with PREFERRED_VARIANT keys taken from a variant run; one merged results.tsv."""
    header, rows = read_results(outs[0] / 'results.tsv')
    source = {k: outs[0] for k in rows}
    for variant in outs[1:]:
        _, vrows = read_results(variant / 'results.tsv')
        for key, row in vrows.items():
            if key in PREFERRED_VARIANT and row[4] in ('ok', 'ok-retry'):
                rows[key], source[key] = row, variant
    status = {}
    for row in rows.values():
        status[row[4]] = status.get(row[4], 0) + 1
    bad = [k for k, r in rows.items() if r[4] not in ('ok', 'ok-retry')]
    if bad:
        ctx.step(f'WARNING: {len(bad)} shaders did not translate (first: {", ".join(bad[:5])})')
    ctx.rmtree(final)
    final.mkdir(parents=True)
    for key, row in rows.items():
        if row[4] in ('ok', 'ok-retry'):
            spv = source[key] / f'{key}.spv'
            require(spv.is_file(), f'missing translated product {spv}')
            shutil.copy2(spv, final / spv.name)
    with (final / 'results.tsv').open('w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(header)
        for key in sorted(rows):
            w.writerow(rows[key])
    ctx.step(f'{len(rows)} shaders: ' + ', '.join(f'{v} {k}' for k, v in sorted(status.items())))
    return {'products': sum(1 for _ in final.glob('*.spv')), 'statuses': status,
            'spv_tree_sha256': tree_digest(final, '*.spv')}


def stage_runtime(ctx):
    import prepare_runtime as prep
    series = read_series(ctx.root / 'runtime/patches/series.macos')
    patches = [ctx.root / 'runtime/patches' / n for n in series]
    for p in patches:
        require(p.is_file(), f'missing runtime patch {p}')
    ctx.rmtree(ctx.runtime_src)
    ctx.mkdir(ctx.runtime_src.parent)
    if ctx.dry:
        ctx.run(['git', 'clone', '--no-hardlinks', '--no-checkout', ctx.upstream, ctx.runtime_src])
        for p in patches:
            ctx.run(['git', '-C', ctx.runtime_src, 'apply', p])
        return {}
    ctx.step(f'applying {len(patches)} patches from runtime/patches/series.macos')
    try:
        prep.prepare_source(ctx.upstream, ctx.runtime_src, patches, pin=PIN)
    except subprocess.CalledProcessError as e:
        failing = next((str(x) for x in e.cmd if str(x).endswith('.patch')), '?')
        raise BuildError(f'a runtime patch did not apply: {failing}')
    receipt_path = ctx.control / 'receipt.json'
    require(receipt_path.is_file(), 'missing control metadata; rerun --from-stage control')
    raw = receipt_path.read_bytes()
    header = prep.control_header(json.loads(raw)['binding'], hashlib.sha256(raw).hexdigest())
    ctx.write(ctx.runtime_src / 'runtime/src/astral_control_context.h', header)
    fingerprint = prep.source_fingerprint(ctx.runtime_src)
    return {'patches': {p.name: sha256(p) for p in patches},
            'source_sha256': hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()}


def stage_build(ctx):
    cmake, ninja = ctx.tool('cmake'), ctx.tool('ninja')
    require(ctx.dry or (cmake and ninja), f'cmake/ninja missing; {BREW_HINT} or rerun --from-stage toolchain')
    cmake, ninja = cmake or 'cmake', ninja or 'ninja'
    vk = ctx.vulkan_include()
    if not (vk / 'vulkan/vulkan.h').is_file():
        dest = ctx.deps / 'Vulkan-Headers'
        ctx.rmtree(dest)
        ctx.mkdir(dest)
        ctx.run(['git', '-C', dest, 'init', '-q'])
        ctx.run(['git', '-C', dest, 'fetch', '-q', '--depth', '1', VULKAN_HEADERS_URL, VULKAN_HEADERS_PIN])
        ctx.run(['git', '-C', dest, 'checkout', '-q', '--detach', 'FETCH_HEAD'])
        vk = dest / 'include'
    prefix = ctx.brew_prefix()
    targets = ['astral']
    variant = {}
    if variant_built(ctx):
        targets.append(f'astral-{VARIANT}')
        variant = write_variant_list(ctx)
    cmd = [cmake, '-S', ctx.runtime_src, '-B', ctx.build_dir, '-G', 'Ninja', '-DNX_GAME=astral',
           f'-DNX_GEN_DIR={ctx.gen}', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
           f'-DCMAKE_MAKE_PROGRAM={ninja}', f'-DCMAKE_PREFIX_PATH={prefix}', f'-DNX_VULKAN_INCLUDE={vk}',
           '-DNX_HWOPUS=ON', f'-DNX_MAIN_VARIANT_LIST={ctx.variant_list if variant else ""}',
           f'-DNX_MAIN_VARIANT_NAME={VARIANT}', f'-DNX_SINGLE_FPS={single_fps(ctx)}']
    env = {'PKG_CONFIG_PATH': f'{prefix}/lib/pkgconfig:' + os.environ.get('PKG_CONFIG_PATH', '')}
    ctx.run(cmd, env=env, log=ctx.logs / 'configure.log')
    if not ctx.dry:
        commands = json.loads((ctx.build_dir / 'compile_commands.json').read_text())
        require(any(str(ctx.gen / 'main') in c['file'] for c in commands), 'the build does not include the lifted code')
        if variant.get('compile'):
            require(any(str(ctx.gen_variant / 'main') in c['file'] for c in commands),
                    'the build does not include the 60 fps lift (runtime/patches/astral-fps-variant.patch)')
        flags = ('-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1')
        require(all(all(f in c['command'] for f in flags) for c in commands),
                'the configured build is missing NX_ASTRAL_STRICT/NX_APPLE_HIGH_MEMORY; the patch series did not apply')
    jobs = ctx.jobs()
    ctx.step(f'compiling with {jobs} jobs at low priority (can take an hour; --jobs N changes it; fewer jobs are '
             'used automatically under memory pressure; rerunning continues where it stopped)')

    def make(n):
        return [cmake, '--build', ctx.build_dir, '--parallel', n, '--target', *targets]
    if ctx.dry:
        ctx.run(low_priority(make(jobs)), env=env)
        return {}
    ctx.commands.append([str(x) for x in make(jobs)])
    final_jobs = watched_build(ctx, make, jobs, ctx.logs / 'build.log', env=env)
    exe = ctx.build_dir / 'astral'
    require(exe.is_file(), 'the build finished but produced no astral executable')
    return {'executable_sha256': sha256(exe), 'jobs': jobs, 'final_jobs': final_jobs}


def font_slot_source(fonts_dir, stem):
    for suffix in ('.bfttf', '.ttf', '.otf'):
        for name in (stem + suffix, stem.upper() + suffix):
            if (fonts_dir / name).is_file():
                return fonts_dir / name
    return None


def fetch(ctx, url, digest, dest):
    if dest.is_file() and sha256(dest) == digest:
        return dest
    curl = ctx.tool('curl') or 'curl'
    tmp = dest.with_name(dest.name + '.part')
    ctx.run([curl, '-fsSL', '--retry', '3', '-o', tmp, url])
    if ctx.dry:
        return dest
    require(sha256(tmp) == digest, f'download checksum mismatch for {url}')
    tmp.replace(dest)
    return dest


def stage_fonts(ctx):
    dest = ctx.data / 'shared-fonts'
    fonts = Path(ctx.a.fonts) if ctx.a.fonts else None
    ctx.mkdir(dest)
    if fonts:
        missing = [s for s in FONT_FILES if not font_slot_source(fonts, s)]
        require(not missing, f'--fonts {fonts} lacks: ' + ', '.join(s + '.bfttf' for s in missing) +
                ' (see docs/BUILDING.md, or omit --fonts to use open-licensed replacements)')
        total = 0
        for stem in FONT_FILES:
            src = font_slot_source(fonts, stem)
            if ctx.dry:
                ctx.copy(src, dest / (stem + '.bfttf'))
                continue
            data = src.read_bytes()
            try:
                ttf = decode_bfttf(data) if src.suffix.lower() == '.bfttf' else data
                out = data if src.suffix.lower() == '.bfttf' else encode_bfttf(ttf)
            except BuildError as e:
                raise BuildError(f'{src}: {e}')
            total += len(ttf) + 8
            ctx.write(dest / (stem + '.bfttf'), out)
        require(ctx.dry or total <= FONT_LIMIT, f'the six fonts total {total} bytes, over the {FONT_LIMIT} limit')
        for stale in ('REPLACEMENT.txt', 'NotoSans-OFL.txt'):  # left by an earlier replacement-font build
            ctx.rmtree(dest / stale)
        return {'source': 'player', 'files': len(FONT_FILES)}
    # No firmware fonts: serve one open-licensed font in every slot.
    if ctx.a.replacement_font:
        ttf_path = Path(ctx.a.replacement_font)
        license_path = None
    else:
        cache = ctx.work / 'fonts'
        ctx.mkdir(cache)
        ttf_path = fetch(ctx, *REPLACEMENT_FONT, cache / 'NotoSans-Regular.ttf')
        license_path = fetch(ctx, *REPLACEMENT_LICENSE, cache / 'OFL.txt')
    ctx.step(f'no --fonts given: using {ttf_path.name} (open-licensed) for all six shared-font slots; '
             'they are installed and format-checked, but their in-game appearance is not yet verified; Nintendo '
             'button icons and CJK text will not display')
    if ctx.dry:
        return {}
    ttf = ttf_path.read_bytes()
    require(6 * (len(ttf) + 8) <= FONT_LIMIT, f'{ttf_path} is too large to fill six slots')
    blob = encode_bfttf(ttf)
    for stem in FONT_FILES:
        ctx.write(dest / (stem + '.bfttf'), blob)
    if license_path:
        ctx.copy(license_path, dest / 'NotoSans-OFL.txt')
    ctx.write(dest / 'REPLACEMENT.txt', f'These are not Nintendo fonts: every slot holds {ttf_path.name} '
              '(SIL Open Font License). Rerun tools/acr_build.py --fonts <dir> --from-stage fonts to use your '
              'console\'s fonts.\n')
    return {'source': 'replacement', 'font_sha256': hashlib.sha256(ttf).hexdigest()}


def stage_data(ctx):
    ctx.mkdir(ctx.data)
    for name in ('analysis', 'exefs', 'extract', '.wrapper', '.import'):
        ctx.symlink(Path('..') / ctx.import_dir.relative_to(ctx.out) / name, ctx.data / name)
    spirv = ctx.shaders / 'spirv'
    if ctx.dry or spirv.is_dir():
        ctx.rmtree(ctx.data / 'spirv')
        if ctx.dry:
            ctx.copy(spirv, ctx.data / 'spirv')
        else:
            shutil.copytree(spirv, ctx.data / 'spirv')
    ctx.mkdir(ctx.data / 'user')  # saves and settings: never removed by this script
    profile = ctx.a.nvn_format_profile
    if ctx.dry:
        ctx.say(f'    would check and write {ctx.data / "astral.profile"}' + (f' from {profile}' if profile else ''))
    else:
        sdk = (ctx.import_dir / 'analysis/sdk.bin').read_bytes()
        if profile:
            text, label = Path(profile).read_text(), str(profile)
            check_format_profile(parse_format_profile(text), sdk)
        else:
            text = label = None
            for name, candidate in KNOWN_FORMAT_PROFILES:
                try:
                    check_format_profile(parse_format_profile(candidate), sdk)
                except BuildError:
                    continue
                text, label = candidate, name
                break
            require(text is not None, 'this game version is not supported: the SDK does not match any known texture-'
                    'format profile. AC-Recomp supports Astral Chain 1.0.0 (base game, no update). If you have a '
                    'profile for your version, pass --nvn-format-profile <file>.')
        ctx.write(ctx.data / 'astral.profile', text)
        ctx.step(f'NVN format profile ({label}) matches this SDK; installed')
    if not ctx.dry:
        missing = [n for n in ('analysis/main.npdm', 'exefs/main', 'extract/romfs', 'shared-fonts')
                   if not (ctx.data / n).exists()]
        require(not missing, 'the data root is incomplete: ' + ', '.join(missing))
    return {}


LAUNCH = '''#!/bin/sh
# AC-Recomp launcher written by tools/acr_build.py. Game data stays in the data root below.
here="$(cd "$(dirname "$0")" && pwd)"
default_root={data}
export NX_DATA_ROOT="${{NX_DATA_ROOT:-$default_root}}"
if [ -z "${{NX_NVN_FORMAT_PROFILE:-}}" ] && [ -f "$NX_DATA_ROOT/astral.profile" ]; then
  export NX_NVN_FORMAT_PROFILE="$NX_DATA_ROOT/astral.profile"
fi
export SDL_VULKAN_LIBRARY="${{SDL_VULKAN_LIBRARY:-$here/../Frameworks/libMoltenVK.dylib}}"
{native}# Frame rate (docs/ASTRAL_60FPS.md): NX_FPS, else settings.ini's fps (the launcher's Frame rate setting). 60 runs
# astral-60fps when this build has it; the launcher switches binaries itself when the setting changes there.
fps="${{NX_FPS:-}}"
if [ -z "$fps" ] && [ -f "$NX_DATA_ROOT/settings.ini" ]; then
  fps="$(sed -n 's/^[[:space:]]*fps[[:space:]]*=[[:space:]]*\\([0-9]*\\).*/\\1/p' "$NX_DATA_ROOT/settings.ini" | tail -n 1)"
fi
bin=astral
if [ "$fps" = 60 ] && [ -x "$here/astral-{variant}" ]; then
  bin=astral-{variant}
fi
exec "$here/$bin" "$@"
'''


def write_variant_list(ctx):
    """runtime/patches/astral-fps-variant.patch's input: the second lift's main directory, its files that differ from
    the first lift's (compiled again) and the first lift's files they replace or that it lacks (left out)."""
    base, var = ctx.gen / 'main', ctx.gen_variant / 'main'
    if ctx.dry:
        ctx.step(f'60 fps: listing the files of {var} that differ from {base}')
        return {'compile': []}
    require(var.is_dir(), f'no 60 fps lift in {var}; rerun --from-stage lift')
    names = {p.name for p in var.iterdir() if p.is_file()}
    old = {p.name for p in base.iterdir() if p.is_file()}

    def same(n):
        a, b = base / n, var / n
        return n in old and a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    changed = sorted(n for n in names if not same(n))
    if any(n.endswith(('.h', '.hpp', '.inc')) for n in changed):  # a shared header changed: all compile again
        changed = sorted(n for n in names if n.endswith('.cpp'))
    compile_ = [n for n in changed if n.endswith('.cpp')]
    exclude = sorted(set(compile_) | {n for n in old - names if n.endswith('.cpp')})
    lines = [f'dir {var}'] + [f'compile {n}' for n in compile_] + [f'exclude {n}' for n in exclude]
    ctx.write(ctx.variant_list, '\n'.join(lines) + '\n')
    ctx.step(f'60 fps: {len(compile_)} of {len([n for n in names if n.endswith(".cpp")])} generated main files differ '
             'and compile again; the rest are shared')
    return {'compile': compile_, 'exclude': exclude}


ICON_SIZES = (16, 32, 128, 256, 512)  # each also @2x: the sizes an .iconset holds


def app_icon(ctx, contents):
    """Contents/Resources/AC-Recomp.icns from assets/launcher/AC-Recomp.png (1024 px) with sips and iconutil; False
    (and a note) when either tool or the image is missing."""
    png = ctx.root / 'assets/launcher/AC-Recomp.png'
    sips, iconutil = shutil.which('sips'), shutil.which('iconutil')
    if not (png.is_file() and sips and iconutil):
        ctx.step('no app icon (needs sips, iconutil and assets/launcher/AC-Recomp.png); the app uses the default icon')
        return False
    iconset = ctx.work / 'AC-Recomp.iconset'
    ctx.rmtree(iconset)
    ctx.mkdir(iconset)
    for size in ICON_SIZES:
        for scale in (1, 2):
            px = str(size * scale)
            name = f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png'
            ctx.run([sips, '-z', px, px, png, '--out', iconset / name], capture=True)
    ctx.mkdir(contents / 'Resources')
    ctx.run([iconutil, '-c', 'icns', iconset, '-o', contents / 'Resources/AC-Recomp.icns'], capture=True)
    ctx.rmtree(iconset)
    return True


def stage_app(ctx):
    exe = ctx.build_dir / 'astral'
    mvk = ctx.moltenvk()
    require(ctx.dry or exe.is_file(), 'no astral executable; rerun --from-stage build')
    require(ctx.dry or mvk, 'MoltenVK not found; pass --moltenvk <path to libMoltenVK.dylib>')
    contents = ctx.app / 'Contents'
    # --render-res: the launcher labels window sizes relative to it ("2560x1440 (Native)").
    native = (f'export NX_NATIVE_RES="${{NX_NATIVE_RES:-{ctx.a.render_res}}}"\n'
              if getattr(ctx.a, 'render_res', None) else '')
    ctx.rmtree(ctx.app)
    ctx.mkdir(contents / 'MacOS')
    ctx.copy(exe, contents / 'MacOS/astral')
    if variant_built(ctx):
        exe60 = ctx.build_dir / f'astral-{VARIANT}'
        require(ctx.dry or exe60.is_file(), f'no astral-{VARIANT} executable; rerun --from-stage build')
        ctx.copy(exe60, contents / f'MacOS/astral-{VARIANT}')
    ctx.copy(mvk or 'libMoltenVK.dylib', contents / 'Frameworks/libMoltenVK.dylib')
    assets = ctx.root / 'assets/launcher'
    for f in sorted(assets.iterdir()) if assets.is_dir() else ():
        ctx.copy(f, contents / 'Resources/assets/launcher' / f.name)
    ctx.write(contents / 'MacOS/AC-Recomp', LAUNCH.format(data=shlex.quote(str(ctx.data)), variant=VARIANT,
                                                           native=native), mode=0o755)
    info = {'CFBundleName': 'AC-Recomp', 'CFBundleDisplayName': 'AC-Recomp', 'CFBundleExecutable': 'AC-Recomp',
            'CFBundleIdentifier': 'local.ac-recomp', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '0.1.0',
            'CFBundleShortVersionString': '0.1.0', 'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.games'}
    if app_icon(ctx, contents):
        info['CFBundleIconFile'] = 'AC-Recomp'
    ctx.write(contents / 'Info.plist', plistlib.dumps(info))
    ctx.write(ctx.out / 'run-ac-recomp.sh', '#!/bin/sh\nexec "$(dirname "$0")/AC-Recomp.app/Contents/MacOS/AC-Recomp" '
              '"$@"\n', mode=0o755)
    if not ctx.dry and shutil.which('codesign'):
        ctx.run(['codesign', '--force', '--sign', '-', contents / 'Frameworks/libMoltenVK.dylib'], check=False,
                capture=True)
        for exe_name in ['astral'] + ([f'astral-{VARIANT}'] if variant_built(ctx) else []):
            ctx.run(['codesign', '--force', '--sign', '-', contents / 'MacOS' / exe_name], check=False, capture=True)
    ctx.step(f'done: open {ctx.app} (or run {ctx.out / "run-ac-recomp.sh"})')
    return {}


STAGE_FUNCS = {
    'preflight': stage_preflight, 'workspace': stage_workspace, 'upstream': stage_upstream,
    'toolchain': stage_toolchain, 'import': stage_import, 'control': stage_control, 'lift': stage_lift,
    'shaders': stage_shaders, 'runtime': stage_runtime, 'build': stage_build, 'fonts': stage_fonts,
    'data': stage_data, 'app': stage_app,
}
ALWAYS = {'preflight'}  # cheap checks rerun every time


def select(args):
    names = list(STAGE_NAMES)
    if args.only:
        for n in args.only:
            require(n in STAGE_FUNCS, f'unknown stage {n}; see --list-stages')
        return [n for n in names if n in args.only], set(args.only)
    start = names.index(args.from_stage) if args.from_stage else 0
    stop = names.index(args.to_stage) + 1 if args.to_stage else len(names)
    forced = set(names[start:stop]) if args.from_stage else set()
    return names[:stop], forced


def stage_inputs(ctx):
    """What each cached stage was built from. A change invalidates that stage and every later one."""
    patches = ctx.root / 'runtime/patches'

    def digest(paths):
        h = hashlib.sha256()
        for p in paths:
            h.update(p.name.encode() + b'\0' + (sha256(p).encode() if p.is_file() else b'missing') + b'\n')
        return h.hexdigest()
    series = patches / 'series.macos'
    names = read_series(series) if series.is_file() else []
    lift = PIN + ':' + digest([patches / 'astral-sqshl.patch'])
    if fps60(ctx.a):  # switching the frame rate relifts main and rebuilds everything after it
        lift += ':fps60:' + digest([ctx.root / 'tools/astral_fps60.py'])
    elif both_fps(ctx.a):
        lift += ':fps30+60:' + digest([ctx.root / 'tools/astral_fps60.py'])
    if getattr(ctx.a, 'render_res', None):  # a stock build keeps its recorded inputs
        lift += f':render-res={ctx.a.render_res}:mem={ctx.a.graphics_memory_mib or "auto"}:' + \
            sha256(ctx.root / 'tools/astral_render_res.py')
    return {'upstream': PIN, 'lift': lift,
            'control': digest([patches / 'astral-control-import.patch']),
            'runtime': PIN + ':' + digest([series] + [patches / n for n in names])}


def check_out_dir(ctx):
    out = ctx.out
    if out.exists():
        require(out.is_dir(), f'--out {out} is not a directory')
        if any(out.iterdir()) and not ctx.state_path.is_file():
            raise BuildError(f'--out {out} is not empty and is not an AC-Recomp build directory (no acr-state.json). '
                             'Choose a new or empty directory.')


def run_pipeline(ctx):
    check_out_dir(ctx)
    wanted, forced = select(ctx.a)
    current = stage_inputs(ctx)
    for i, name in enumerate(STAGE_NAMES):
        recorded = ctx.state.get('stages', {}).get(name, {}).get('inputs')
        if name in current and ctx.done(name) and recorded != current[name]:
            ctx.say(f'{name}: its inputs changed since it ran (pinned revision or patches); rebuilding it and the '
                    'stages after it')
            forced |= set(STAGE_NAMES[i:])
            break
    t0 = time.monotonic()
    for i, name in enumerate(wanted, 1):
        if name not in forced and name not in ALWAYS and ctx.done(name):
            ctx.say(f'[{i}/{len(wanted)}] {name}: already done ({ctx.state["stages"][name]["done_utc"]}), skipped')
            continue
        ctx.say(f'[{i}/{len(wanted)}] {name}: {dict(STAGES)[name]}')
        ctx.forget(name)
        started = time.monotonic()
        evidence = STAGE_FUNCS[name](ctx) or {}
        evidence['seconds'] = round(time.monotonic() - started, 1)
        if name in current:
            evidence['inputs'] = current[name]
        if name not in ALWAYS:
            ctx.record(name, evidence)
        ctx.say(f'    ok ({evidence["seconds"]} s)')
    ctx.say(f'finished in {round(time.monotonic() - t0)} s' + (' (dry run: nothing was changed)' if ctx.dry else ''))


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--nsp', type=Path, help='your Astral Chain dump (.nsp)')
    p.add_argument('--keys', type=Path, help="your console's prod.keys (passed by path only)")
    p.add_argument('--title-keys', type=Path, help='title.keys, if your dump needs it')
    p.add_argument('--fonts', type=Path, help='directory with the six shared fonts (.bfttf, or decoded .ttf); '
                                              'without it, open-licensed replacements are used')
    p.add_argument('--replacement-font', type=Path, help='a TrueType font to use instead of the default Noto Sans')
    p.add_argument('--nvn-format-profile', type=Path,
                   help='override the built-in texture-format profile (NX_FORMAT_PROFILE_V1; checked against your SDK)')
    p.add_argument('--out', type=Path, help='private build directory (needs about 25 GB)')
    p.add_argument('--reference', help='local clone or URL of SuperMarioWonderRecomp (default: GitHub)')
    p.add_argument('--ryubing', help='local clone or URL of Ryubing (default: Codeberg)')
    p.add_argument('--lift-python', help='Python used for the recompiler venv (default: this one)')
    p.add_argument('--prefix', type=Path, help='install prefix of SDL3/opus (default: Homebrew)')
    p.add_argument('--vulkan-include', type=Path, help='Vulkan headers include directory')
    p.add_argument('--moltenvk', type=Path, help='path to libMoltenVK.dylib')
    p.add_argument('--dotnet', type=Path, help='the dotnet executable of a .NET 10 SDK')
    p.add_argument('--cmake', type=Path)
    p.add_argument('--ninja', type=Path)
    p.add_argument('--jobs', type=int, help='parallel compile jobs (default: by CPU count and memory)')
    p.add_argument('--render-res', metavar='WxH',
                   help='docked internal resolution, e.g. 2560x1440 (stock 1600x900; patches main before lifting, '
                        'see docs/ASTRAL_RENDER_RES.md)')
    p.add_argument('--graphics-memory-mib', type=int, metavar='MIB',
                   help='with --render-res: the game\'s graphics memory budget (default: scaled; stock 310)')
    p.add_argument('--fps', choices=('30', '60'),
                   help='build one frame rate only: 30 (the game as shipped) or 60 (patches five instructions of main '
                        'before the lift; Astral Chain 1.0.0 only; docs/ASTRAL_60FPS.md). Default: NX_FPS, else both: '
                        'astral and astral-60fps, picked by the launcher\'s Frame rate setting')
    p.add_argument('--skip-shaders', action='store_true', help='skip shader translation (no rendering)')
    p.add_argument('--no-shader-validation', action='store_true', help='do not run spirv-val on translated shaders')
    p.add_argument('--from-stage', choices=STAGE_NAMES, help='rerun this stage and all later ones')
    p.add_argument('--to-stage', choices=STAGE_NAMES, help='stop after this stage')
    p.add_argument('--only', action='append', metavar='STAGE', help='run only this stage (repeatable)')
    p.add_argument('--dry-run', action='store_true', help='print the plan; change nothing')
    p.add_argument('--list-stages', action='store_true')
    a = p.parse_args(argv)
    if a.render_res:
        import astral_render_res as rr
        try:
            w, h = rr.parse_res(a.render_res)
            rr.plan(w, h, a.graphics_memory_mib)
        except rr.PatchError as e:
            p.error(f'--render-res: {e}')
        a.render_res = f'{w}x{h}'
    elif a.graphics_memory_mib is not None:
        p.error('--graphics-memory-mib needs --render-res')
    if not a.list_stages:
        missing = [f'--{n}' for n in ('out',) if getattr(a, n) is None]
        needs_inputs = set()
        if not missing:
            wanted, forced = select(a)
            state = Path(a.out) / 'acr-state.json'
            done = set(json.loads(state.read_text()).get('stages', {})) if state.is_file() else set()
            needs_inputs = {s for s in ('import', 'control') if s in wanted and (s in forced or s not in done)}
        missing += [f'--{n.replace("_", "-")}' for n in ('nsp', 'keys') if needs_inputs and getattr(a, n) is None]
        if missing:
            p.error('missing ' + ', '.join(missing))
    return a


def main(argv=None, root=ROOT, stream=sys.stdout):
    try:
        a = parse(argv)
    except BuildError as e:
        print('error: ' + str(e), file=sys.stderr)
        return 2
    if a.list_stages:
        for n, d in STAGES:
            print(f'{n:10} {d}', file=stream)
        return 0
    ctx = Context(a, root=root, out=stream)
    try:
        run_pipeline(ctx)
    except BuildError as e:
        print('\nerror: ' + str(e), file=sys.stderr)
        print('Fix the problem and run the same command again; finished stages are skipped.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\ninterrupted; run the same command again to continue.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
