"""Desktop overlays preserve the non-Astral profile on the private pinned upstream."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ['runtime/src/hle_hid.cpp', 'runtime/src/platform.h', 'runtime/src/platform_mac.cpp',
          'runtime/src/platform_linux.cpp', 'runtime/src/platform_win.cpp', 'runtime/src/platform_android_input.cpp',
          'runtime/src/perf_hud.cpp', 'runtime/src/nvn/nvn_vk.cpp', 'runtime/src/nvn/nvn_vk.h',
          'runtime/src/nvn/nvn_frames.cpp', 'runtime/src/nvn/nvn_debug.cpp', 'runtime/src/nvn/nvn_pipeline.h',
          'runtime/src/nvn/nvn_spirv_patch.cpp', 'runtime/src/nvn/nvn_present.cpp', 'runtime/src/hle_vi.cpp',
          'runtime/src/hle_fs.cpp']
DIRECTIVE = re.compile(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$')
WAIT_CALL = re.compile(r'p_vk(WaitForFences|AcquireNextImageKHR|AcquireNextImage2KHR|WaitSemaphores(?:KHR)?)\s*\(')


def strict_value(cond: str, defined: bool):
    """The condition's value when it is decided by NX_ASTRAL_STRICT alone, else None (kept as is)."""
    c = cond.split('//', 1)[0].strip()
    if 'NX_ASTRAL_STRICT' not in c:
        return None
    plain = r'defined\s*\(?\s*NX_ASTRAL_STRICT\s*\)?'
    if re.fullmatch(plain, c) or c == 'NX_ASTRAL_STRICT':
        return defined
    if re.fullmatch(plain + r'\s*&&.*', c):
        return False if not defined else None
    if re.fullmatch(r'!\s*' + plain, c):
        return not defined
    raise AssertionError(f'unsupported NX_ASTRAL_STRICT condition: {cond!r}')


def resolve(text: str, defined: bool) -> str:
    """Keeps the branches the preprocessor would take for NX_ASTRAL_STRICT (un)defined; every other line stays."""
    out, stack = [], []  # [decided, keep, taken]
    for line in text.splitlines(keepends=True):
        m = DIRECTIVE.match(line)
        if not m:
            if all(e[1] for e in stack):
                out.append(line)
            continue
        kind, rest = m.group(1), m.group(2)
        if kind in ('if', 'ifdef', 'ifndef'):
            cond = rest.strip() if kind == 'if' else 'defined(' + rest.strip() + ')'
            v = strict_value(('!' + cond) if kind == 'ifndef' else cond, defined)
            if v is None:
                if all(e[1] for e in stack):
                    out.append(line)
                stack.append([False, True, True])
            else:
                stack.append([True, v, v])
            continue
        top = stack[-1]
        if not top[0]:
            if kind == 'endif':
                stack.pop()
                if all(e[1] for e in stack):
                    out.append(line)
            elif all(e[1] for e in stack[:-1]):
                out.append(line)
            continue
        if kind == 'elif':
            v = strict_value(rest, defined)
            if v is None:
                raise AssertionError('#elif mixing NX_ASTRAL_STRICT with other conditions')
            top[1], top[2] = v and not top[2], top[2] or v
        elif kind == 'else':
            top[1], top[2] = not top[2], True
        else:
            stack.pop()
    return ''.join(out)


def unbounded_waits(text: str):
    """(line, call) of runtime Vulkan waits whose arguments contain UINT64_MAX or an all-ones literal."""
    found = []
    for m in WAIT_CALL.finditer(text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            depth += {'(': 1, ')': -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        call = text[m.start():i + 1]
        if re.search(r'UINT64_MAX|~0ull|~uint64_t\(0\)|0xffffffffffffffff', call, re.I):
            found.append((text.count('\n', 0, m.start()) + 1, ' '.join(call.split())))
    return found


PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'


def git_apply(tree: Path, name: str) -> None:
    subprocess.run(['git', '-C', str(tree), 'apply', '--whitespace=nowarn', str(ROOT / 'runtime/patches' / name)],
                   check=True, timeout=120, capture_output=True)


def patched_tree(test, d: Path) -> tuple[Path, Path]:
    """(base, patched): the Wonder pin with runtime/patches/series.macos up to astral-launcher.patch, and the same plus
    every desktop overlay after it (astral-touch.patch, astral-upscale.patch, ...), with git apply (skipped
    without the private pinned reference)."""
    common = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--path-format=absolute',
                                      '--git-common-dir'], timeout=10).decode().strip()
    ref = Path(common).parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
    if not (ref / '.git').exists():
        test.skipTest('private pinned upstream reference unavailable')
    series = [l.strip() for l in (ROOT / 'runtime/patches/series.macos').read_text().splitlines()
              if l.strip() and not l.startswith('#')]
    split = series.index('astral-launcher.patch') + 1  # the overlays after the launcher (touch, upscale, ...)
    test.assertEqual(series[split:split + 2], ['astral-touch.patch', 'astral-upscale.patch'])
    trees = []
    for name, extra in (('base', []), ('tree', series[split:])):
        tree = d / name
        tree.mkdir()
        archive = subprocess.run(['git', '-C', str(ref), 'archive', PIN], check=True, capture_output=True, timeout=120)
        subprocess.run(['tar', '-x', '-C', str(tree)], input=archive.stdout, check=True, timeout=120)
        subprocess.run(['git', 'init', '-q', str(tree)], check=True, timeout=30)
        for patch in series[:split] + [p if p.endswith('.patch') else p + '.patch' for p in extra]:
            git_apply(tree, patch)
        trees.append(tree)
    return trees[0], trees[1]


class ProfileTest(unittest.TestCase):
    def test_resolver(self):
        src = ('a\n#if defined(NX_ASTRAL_STRICT)\nb\n#else\nc\n#endif\n#if defined(X)\nd\n#else\nx\n#endif\n'
               '#if !defined(NX_ASTRAL_STRICT)\ne\n#endif\n#if defined(NX_ASTRAL_STRICT) && defined(NX_OTHER_FEATURE)\nf\n'
               '#endif\n')
        self.assertEqual(resolve(src, False), 'a\nc\n#if defined(X)\nd\n#else\nx\n#endif\ne\n')
        self.assertEqual(resolve(src, True), 'a\nb\n#if defined(X)\nd\n#else\nx\n#endif\n'
                                             '#if defined(NX_ASTRAL_STRICT) && defined(NX_OTHER_FEATURE)\nf\n#endif\n')
        self.assertEqual(unbounded_waits('p_vkWaitForFences(d, 1, &f, VK_TRUE,\n UINT64_MAX);\n'
                                         'p_vkWaitForFences(d, 1, &f, VK_TRUE, gpu_fence_timeout_ns());'),
                         [(1, 'p_vkWaitForFences(d, 1, &f, VK_TRUE, UINT64_MAX)')])

    def test_patched_shared_files_are_unchanged_without_astral_strict(self):
        with tempfile.TemporaryDirectory() as d:
            live, tree = patched_tree(self, Path(d))
            for rel in SHARED:
                self.assertEqual(resolve((tree / rel).read_text(), False), resolve((live / rel).read_text(), False),
                                 rel)


if __name__ == '__main__':
    unittest.main()
