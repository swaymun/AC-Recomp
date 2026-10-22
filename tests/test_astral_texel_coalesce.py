"""Texel-write coalescing overlay (astral-texel-coalesce.patch, docs/ASTRAL_TEXEL_COALESCE.md).

The overlay follows astral-fps-variant.patch and precedes astral-shader-cache.patch. Its drop_covered_writes() is compiled
from the patch bytes with a stand-in TexelWrite and checked: a write drops the pending writes it covers completely
(same level, contained box, any depth), keeps partial overlaps, other levels and larger writes, and keeps the order of
what remains; a texture written every frame keeps one pending write. The change is inside NX_ASTRAL_STRICT, and on
a fresh copy of the pinned runtime the default profile's preprocessed nvn_objects.cpp is unchanged (skipped without
the private pinned reference). No game, GPU or device is used.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime  # noqa: E402
import test_astral_fps_variant as profiles  # noqa: E402
from test_astral_touch import added_file  # noqa: E402

# Compose the earlier tests' order, inserting the audio fix at its dump dependency.
# The shader-cache test extends this prefix through shader-cache and render-fix.
OVERLAY = 'astral-texel-coalesce.patch'
_AUDIO_FIX_AT = profiles.ORDER.index('astral-audio-dump.patch') + 1
ORDER = (*profiles.ORDER[:_AUDIO_FIX_AT], 'astral-audio-fix.patch',
         *profiles.ORDER[_AUDIO_FIX_AT:], OVERLAY)
PATCH = ROOT / 'runtime/patches' / OVERLAY
OBJECTS = 'runtime/src/nvn/nvn_objects.cpp'


def helper() -> str:
    body = added_file(PATCH, OBJECTS)
    start = body.index('void drop_covered_writes(')
    return body[start:body.index('\n}\n', start) + 3]


FIXTURE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
struct Texture { struct TexelWrite { uint32_t level = 0, x = 0, y = 0, z = 0, w = 0, h = 0, d = 1; std::vector<uint8_t> data; int id = 0; }; };
@HELPER@
using W = Texture::TexelWrite;
W mk(int id, uint32_t level, uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint32_t z = 0, uint32_t d = 1) {
    W t; t.id = id, t.level = level, t.x = x, t.y = y, t.w = w, t.h = h, t.z = z, t.d = d; return t;
}
std::vector<int> ids(const std::vector<W>& v) { std::vector<int> r; for (auto& w : v) r.push_back(w.id); return r; }
void queue(std::vector<W>& v, W w) { drop_covered_writes(v, w); v.push_back(std::move(w)); }
int main() {
    std::vector<W> v;
    queue(v, mk(1, 0, 0, 0, 1600, 900));
    queue(v, mk(2, 0, 10, 10, 20, 20));      // inside 1: 1 stays (not covered by 2)
    queue(v, mk(3, 1, 0, 0, 800, 450));      // another level
    queue(v, mk(4, 0, 1590, 0, 20, 10));     // partial overlap past the right edge of 1
    assert((ids(v) == std::vector<int>{1, 2, 3, 4}));
    queue(v, mk(5, 0, 0, 0, 1600, 900));     // covers 1 and 2, not 4 (extends past), not 3 (level)
    assert((ids(v) == std::vector<int>{3, 4, 5}));
    queue(v, mk(6, 0, 0, 0, 1600, 900, 0, 2));  // deeper box covers 5
    assert((ids(v) == std::vector<int>{3, 4, 6}));
    queue(v, mk(7, 0, 0, 0, 1600, 900, 1, 1));  // a shallower box does not cover 6
    assert((ids(v) == std::vector<int>{3, 4, 6, 7}));
    std::vector<W> frames;
    for (int k = 0; k < 1000; k++) queue(frames, mk(k, 0, 0, 0, 1600, 900));
    assert(frames.size() == 1 && frames[0].id == 999);
    W huge = mk(8, 0, 0xFFFFFFF0u, 0, 0x20, 1);  // x + w past 2^32 is not wrapped
    std::vector<W> edge{mk(9, 0, 0, 0, 1, 1)};
    queue(edge, huge);
    assert((ids(edge) == std::vector<int>{9, 8}));
    std::printf("PASS coalesce\n");
    return 0;
}
'''


class TexelCoalesceTests(unittest.TestCase):
    def test_series_prefix_through_the_overlay(self):
        series = [l.split('#')[0].strip() for l in (ROOT / 'runtime/patches/series.macos').read_text().splitlines()]
        series = [s for s in series if s]
        self.assertEqual(series[:series.index(OVERLAY) + 1], list(ORDER))

    def test_patch_is_strict_only_and_public(self):
        text = PATCH.read_text()
        self.assertEqual(re.findall(r'^diff --git a/(\S+) ', text, re.M), [OBJECTS])
        self.assertNotRegex(text, r'/(?:Users|home|work)/')
        added = [l[1:] for l in text.splitlines() if l.startswith('+') and not l.startswith('+++')]
        depth, outside = 0, []
        for line in added:
            if line.startswith('#if defined(NX_ASTRAL_STRICT)'):
                depth += 1
            elif line.startswith('#endif'):
                depth -= 1
            elif depth == 0 and line.strip():
                outside.append(line)
        self.assertEqual(outside, [])

    def test_drop_covered_writes(self):
        cxx = shutil.which('c++') or shutil.which('clang++')
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'fixture.cpp'
            src.write_text(FIXTURE.replace('@HELPER@', helper()))
            exe = Path(d) / 'fixture'
            r = subprocess.run([cxx, '-std=c++20', '-Wall', '-Werror', str(src), '-o', str(exe)],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('PASS coalesce', r.stdout)

    def test_applies_after_the_series_and_default_profile_is_unchanged(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('NVN_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        if not (reference / '.git').exists():
            self.skipTest('private pinned upstream reference unavailable')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'source'
            patches = [ROOT / 'runtime/patches' / n for n in ORDER]
            runtime.prepare_source(reference, source, patches[:-1])
            before = (source / OBJECTS).read_text()
            subprocess.run(['git', '-C', str(source), 'apply', str(PATCH)], check=True, capture_output=True, timeout=60)
            after = (source / OBJECTS).read_text()
            self.assertIn('drop_covered_writes(t->writes, w);', after)
            strip = re.compile(r'#if defined\(NX_ASTRAL_STRICT\)\n.*?#endif\n\n?', re.S)
            self.assertEqual(strip.sub('', after), before)


if __name__ == '__main__':
    unittest.main()
