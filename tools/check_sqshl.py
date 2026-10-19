#!/usr/bin/env python3
"""Fail-closed, local-only SQSHL emitter / bigint / native-ARM64 check.

No packages, downloads, game inputs or title execution. Receipts stay in .local.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys

PIN = '010ed7a596a621c15d3a8dfa5795ca8c3668b066'
CONTRACT_URL = 'https://documentation-service.arm.com/static/67e40f3398aa3c3b6eea6a85'
CONTRACT_SHA = 'b7baa6869789722df70da60170d999a62810409aaabbb6db1ef729ed68686bdf'
ROOT = Path(__file__).resolve().parents[1]
QC = 1 << 27
ALIASES = [(0, 1, 2), (1, 1, 2), (2, 1, 2), (0, 1, 1), (1, 1, 1)]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, *, cwd=None, data=None, timeout=60):
    p = subprocess.run([str(x) for x in argv], cwd=cwd, input=data,
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                             'UBSAN_OPTIONS': 'halt_on_error=1'})
    require(p.returncode == 0, f'child failed ({p.returncode}): {p.stderr[-2000:]}')
    return p.stdout


def defaults():
    common = Path(run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT).strip())
    base = common.resolve().parent if common.is_absolute() else (ROOT / common).resolve().parent
    return (base / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp',
            base / '.local/game-private/astral-work/venv/bin/python')


def validate_reference(reference):
    require(reference.is_dir(), 'required reference missing')
    require(run(['git', '-C', reference, 'rev-parse', 'HEAD']).strip() == PIN, 'wrong reference pin')
    require(not run(['git', '-C', reference, 'status', '--porcelain']).strip(), 'dirty reference')


def fingerprint(source):
    paths = run(['git', '-C', source, 'ls-files']).splitlines()
    return {p: sha(source / p) for p in paths}


# Only this child imports the existing pinned dependencies. All fixture instructions
# are synthetic encodings assembled from the architecture's register/size fields.
EMIT_CHILD = r'''
import json, sys, types
import capstone, lz4, zstandard
assert capstone.__version__ == '5.0.6'
assert lz4.__version__ == '4.4.4'
assert zstandard.__version__ == '0.24.0'
sys.path.insert(0, sys.argv[1])
from recomp.emit import Emitter, Unhandled
cs = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); cs.detail = True
e = Emitter(types.SimpleNamespace(module=None, functions=[]))
def decode(word):
    ins = list(cs.disasm(word.to_bytes(4, 'little'), 0))
    assert len(ins) == 1 and ins[0].mnemonic == 'sqshl'
    return ins[0]
aliases = [(0,1,2),(1,1,2),(2,1,2),(0,1,1),(1,1,1)]
statements = []
for d,n,m in aliases:
    i = decode(0x4ea04c00 | m << 16 | n << 5 | d)
    assert i.op_str == f'v{d}.4s, v{n}.4s, v{m}.4s'
    statements.append(e.insn(None, i, {}))
rejected = []
# All other legal AdvSIMD register arrangements, all scalar widths, and
# immediate forms at both ends of their legal shift range.
words = []
for size in range(4):
    words.append((f'scalar-register-{8<<size}', 0x5e204c20 | size<<22 | 2<<16))
    for q in range(2):
        if not (size == 3 and q == 0) and not (size == 2 and q == 1):
            words.append((f'vector-register-{8<<size}-{q}', 0x0e204c20 | size<<22 | q<<30 | 2<<16))
    for shift in (0, (8<<size)-1):
        imm = (8<<size) + shift
        words.append((f'scalar-immediate-{8<<size}-{shift}', 0x5f007420 | imm<<16))
        for q in range(2):
            if not (size == 3 and q == 0):
                words.append((f'vector-immediate-{8<<size}-{q}-{shift}', 0x0f007420 | q<<30 | imm<<16))
for label, word in words:
    i = decode(word)
    try: e.insn(None, i, {})
    except Unhandled: rejected.append(label)
    else: raise AssertionError('unsupported form accepted: '+label)
    f = types.SimpleNamespace(start=0, end=4)
    an = types.SimpleNamespace(module=types.SimpleNamespace(image=word.to_bytes(4, 'little')),
                               functions=[f], jump_tables={})
    fatal = Emitter(an)
    assert 'nx::unimpl(' in fatal.function(f) and fatal.unhandled['sqshl'] == 1
print(json.dumps(dict(statements=statements, rejected=rejected,
    dependencies=dict(capstone=capstone.__version__, lz4=lz4.__version__, zstandard=zstandard.__version__))))
'''


def expected(regs, alias, fpsr):
    """Independent arbitrary-precision architectural operation, no fixed-width math."""
    d, n, m = alias
    result = []
    for raw, count in zip(regs[n], regs[m]):
        x = raw if raw < (1 << 31) else raw - (1 << 32)
        shift = count % 256
        if shift >= 128:
            shift -= 256
        y = x * (2 ** shift) if shift >= 0 else x // (2 ** -shift)
        clipped = max(-(1 << 31), min((1 << 31) - 1, y))
        if clipped != y:
            fpsr |= QC
        result.append(clipped % (1 << 32))
    out = [list(r) for r in regs]
    out[d] = result
    return out, fpsr


def cases():
    values = [0, 1, 2, 3, -1, -2, -3, -(1<<31), -(1<<31)+1,
              (1<<31)-1, (1<<30)-1, 1<<30, -(1<<30)]
    # Exhaust every signed low-byte count, plus unrelated high count bits.
    flags = [0, QC, 0x0800009f, 0x9f, 0xfedcba980000009f]
    for aid in range(len(ALIASES)):
        for x in values:
            for low in range(256):
                regs = [[0xa5a5a5a5] * 4,
                        [(x+j if -(1<<31) <= x+j < (1<<31) else x) & 0xffffffff for j in (0,0,1,-1)],
                        [(low | high) & 0xffffffff for high in (0, 0x123400, 0xffffff00, 0x80000000)]]
                for fpsr in flags:
                    yield aid, regs, fpsr
    rng = random.Random(192019)
    for _ in range(2000):
        yield rng.randrange(5), [[rng.getrandbits(32) for _ in range(4)] for _ in range(3)], rng.choice(flags)


def harness(statements):
    functions = []
    native = []
    for aid, ((d,n,m), stmt) in enumerate(zip(ALIASES, statements)):
        functions.append(f'case {aid}: {stmt} break;')
        native.append(f'''case {aid}: asm volatile(
            "ldr q0, [%[p0]]\\nldr q1, [%[p1]]\\nldr q2, [%[p2]]\\n"
            "sqshl v{d}.4s, v{n}.4s, v{m}.4s\\nstr q{d}, [%[dst]]\\n"
            : : [p0] "r" (&native.v[0]), [p1] "r" (&native.v[1]),
                [p2] "r" (&native.v[2]), [dst] "r" (&result)
            : "v0", "v1", "v2", "memory"); native.v[{d}] = result; break;''')
    return '''#include <nx/cpu.h>
#include <iostream>
int main() {
  int id; uint64_t input;
  while (std::cin >> id >> input) {
    nx::CPU c{};
    for (int r=0;r<3;r++) for (int k=0;k<4;k++) std::cin >> c.v[r].u32[k];
    c.fpsr=input; nx::CPU native=c;
    switch(id) {''' + '\n'.join(functions) + '''default: return 2; }
    uint64_t saved, actual; nx::V128 result;
    asm volatile("mrs %0, fpsr" : "=r"(saved) : : "memory");
    uint64_t host_input=input & 0x0800009full;
    asm volatile("msr fpsr, %0" : : "r"(host_input) : "memory");
    switch(id) {''' + '\n'.join(native) + '''default: return 3; }
    asm volatile("mrs %0, fpsr" : "=r"(actual) : : "memory");
    asm volatile("msr fpsr, %0" : : "r"(saved) : "memory");
    uint64_t restored;
    asm volatile("mrs %0, fpsr" : "=r"(restored) : : "memory");
    if (restored != saved) return 5;
    for (int r=0;r<3;r++) for(int k=0;k<4;k++) std::cout << c.v[r].u32[k] << ' ';
    std::cout << c.fpsr << ' ';
    for (int r=0;r<3;r++) for(int k=0;k<4;k++) std::cout << native.v[r].u32[k] << ' ';
    std::cout << actual << '\\n';
  }
  return std::cin.eof() ? 0 : 4;
}
'''


def check(reference, python, contract, out, compiler='clang++'):
    validate_reference(reference)
    require(python.is_file(), 'required pinned dependency Python missing')
    require(contract.is_file() and sha(contract) == CONTRACT_SHA, 'required pinned Arm contract missing/mismatched')
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'required native Mac ARM64 oracle unavailable')
    compiler_path = shutil.which(compiler)
    require(compiler_path is not None, 'required compiler missing')
    out = Path(os.path.abspath(out))
    require(out.is_relative_to(ROOT / '.local/cpu-sqshl-019'), 'output outside owned ignored directory')
    require(not any(p.is_symlink() for p in (out, *out.parents)), 'symlink output refused')
    require(not out.exists(), 'fresh output required')
    require(subprocess.run(['git','-C',str(ROOT),'check-ignore','-q',str(out)]).returncode == 0,
            'output must be ignored')
    patch = ROOT / 'runtime/patches/astral-sqshl.patch'
    targets = [line for line in patch.read_text().splitlines() if line.startswith('diff --git ')]
    require(targets == ['diff --git a/recomp/emit_neon.py b/recomp/emit_neon.py'], 'patch target scope violation')
    before = fingerprint(reference)
    out.mkdir(parents=True)
    source = out / 'source'
    run(['git','clone','--no-hardlinks','--no-checkout',reference,source])
    run(['git','-C',source,'checkout','--detach',PIN])
    run(['git','-C',source,'apply','--check',patch])
    run(['git','-C',source,'apply',patch])
    after = fingerprint(source)
    changed = [p for p in before if before[p] != after[p]]
    require(changed == ['recomp/emit_neon.py'], 'upstream source scope violation')
    original_ast = ast.parse((reference/'recomp/emit_neon.py').read_text())
    patched_ast = ast.parse((source/'recomp/emit_neon.py').read_text())
    neon = next(n for n in patched_ast.body if isinstance(n, ast.ClassDef) and n.name == 'NeonOps')
    added = [n for n in neon.body if isinstance(n, ast.FunctionDef) and n.name == 'i_sqshl']
    require(len(added) == 1, 'expected one SQSHL handler')
    neon.body.remove(added[0])
    require(ast.dump(original_ast) == ast.dump(patched_ast), 'other emitter behavior changed')
    emission = json.loads(run([python,'-c',EMIT_CHILD,source]))
    (out/'emission.json').write_text(json.dumps(emission,indent=2)+'\n')
    cpp = out/'oracle.cpp'; cpp.write_text(harness(emission['statements']))
    binary = out/'oracle'
    argv = [compiler_path,'-std=c++20','-O1','-g','-fsanitize=undefined',
            '-fno-sanitize-recover=all','-I',source/'runtime/include',cpp,'-o',binary]
    run(argv, timeout=90)
    fixtures = list(cases())
    data = ''.join(' '.join(map(str,[aid,fpsr,*[v for reg in regs for v in reg]]))+'\n'
                   for aid,regs,fpsr in fixtures)
    (out/'inputs.txt').write_text(data)
    output = run([binary],data=data,timeout=90)
    (out/'outputs.txt').write_text(output)
    lines = output.splitlines()
    require(len(lines)==len(fixtures), 'missing oracle results')
    saturated = sticky = nonsaturating = 0
    for index, ((aid,regs,fpsr), line) in enumerate(zip(fixtures,lines)):
        words = [int(x) for x in line.split()]
        exp, ef = expected(regs, ALIASES[aid], fpsr)
        host_exp, hf = expected(regs, ALIASES[aid], fpsr & 0x0800009f)
        require(words == [*[v for r in exp for v in r],ef,*[v for r in host_exp for v in r],hf],
                f'emitter/reference/native mismatch case {index}')
        _, clear = expected(regs,ALIASES[aid],0)
        saturated += bool(clear & QC)
        sticky += bool(fpsr & QC) and not bool(clear & QC)
        nonsaturating += not bool(clear & QC)
    require(fingerprint(reference)==before, 'reference mutated')
    report = dict(schema=1, pin=PIN, patch_sha256=sha(patch), contract_url=CONTRACT_URL,
                  contract_sha256=sha(contract), changed_upstream=changed,
                  unchanged_upstream_files=len(before)-1, dependencies=emission['dependencies'],
                  supported='AdvSIMD vector SQSHL register 4S only', rejected=emission['rejected'],
                  cases=len(fixtures), lane_comparisons=len(fixtures)*4,
                  native_cases=len(fixtures), ubsan_cases=len(fixtures),
                  saturating_cases=saturated, nonsaturating_cases=nonsaturating, sticky_cases=sticky,
                  compiler_argv=[str(x) for x in argv], compiler=run([compiler_path,'--version']),
                  binary_sha256=sha(binary), cpp_sha256=sha(cpp), outputs_sha256=sha(out/'outputs.txt'),
                  host_fpsr_saved_restored=True, compiler_jobs=1,
                  runtime_integration='unchanged; no game launch or regeneration')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    reference, python = defaults()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,default=reference)
    p.add_argument('--python',type=Path,default=python)
    p.add_argument('--contract',type=Path,default=ROOT/'.local/cpu-sqshl-019/arm-contract.pdf')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',default='clang++')
    a=p.parse_args()
    try:
        report=check(a.reference,a.python,a.contract,a.out,a.compiler)
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        print(f'SQSHL check failed: {e}',file=sys.stderr)
        return 1
    print(json.dumps(report,indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
