# Astral shader translation — SHADER-ASTRAL-004

On 2026-10-18, **one real Astral vertex code/control pair translated successfully**
on the existing `acs-recovery-linux` host. The harness reported **1/1 `ok`**, and
an independent invocation of `spirv-val --target-env vulkan1.2` exited **0** with
no diagnostics. The emitted module is **1,288 bytes**. This measures one selected
graphics stage, not a linked vertex/fragment pipeline or total game coverage.
Rendering and gameplay remain unverified. Cross-ISA byte match is N/A.

## Reviewed inputs and identities

SHADER-PKZ-003 head `6618de973544bd90bcb36e7359b1abb6c4cbb3e8` was confirmed
landed and an ancestor of main before execution. Its independent passing review
is `08f35aba187a40548fefa238887b6d8d`; the landing receipt names the same head.
The overnight plan, shader preflight and shader inventory were read first.

The retained inventory receipt SHA-256 was independently recomputed as
`e9f9fbf0ac0844b7bae1c0fbcefb680039ae8d2deab362ec21e681a3fce57fbc`.
At 10:27:34Z, this unit rehashed the selected original archive, read its bounded
compressed member extent, decoded it in memory, reparsed the DAT directory and
selected wrapper, and reproduced all three handoff files byte-for-byte. The
inventory tool hash also matched its receipt. This checks the original input
chain rather than merely accepting the hashes in the brief. Private names and
source paths remain in ignored evidence.

Only these files were copied from the retained `.local/pkz-inventory-003/` into
this worktree's fresh `.local/astral-shader/input/`, then transferred by SCP into
the fresh remote `.local/astral-shader-004/input/` directory. All three remote
hashes matched the local files before translation; originals were preserved.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `manifest.tsv` | 243 | `4fb2168290135d544712fa515797d7314fee5be78555931fbe6e73293fd8690d` |
| `sample.code.bin` | 256 | `e009a03963076998b9059df75ffd7c06e9a58ae64f80076860177653915881b7` |
| `sample.ctrl.bin` | 2,001 | `5047780e3866817c440c78ceca38cd793eebf138ec1a0a0e69d2da4abe8a5818` |

The prepared root is `/root/acs-units/SHADER-TOOLS-002/repo`. Its wrapper and
dependency lock hashes matched this reviewed checkout before execution:

- `prepare_shader_tools.py`: `b82871595753bb284987bcb638ae8970d5b37365037d091dca45ff7646be96cb`.
- `dependencies.lock`: `e932ebd7d36be38a35b70912c8893611e8f25a7bc8b9ec67ccfeb9c2e8886b5d`.
- Wonder: `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
- Shader translator: `a82350bb774f70fcbd41c9987bf67a3775409963`.
- Harness DLL: `c882db34f88b2b334d770d78a4e375b2d467b632f74451b5817d2ca8d062b336`.
- Validator: `d1a31767a6b197df6f218f1f7ac435d44f74d86e08716f26c832e2dcc7245989`.

The remote toolchain receipt was read before execution and later compared in full
to the retained SHADER-TOOLS-002 receipt; they agree. Its SHA-256 is
`2c2d8edf3e451213558436748a1c7b723a0eec0dd89d1c13989e47edd86926c5`.
It records SDK 10.0.401, the preflight's two selected patches and 57 signed
packages. Batch rechecked the clean source pins, lock, dotnet/harness binaries,
runtime DLL/JSON files, restore locks, package archives/expanded contents and
validator identity before invoking the harness. The retained signature log hash
also matched. No preparation, install, download or upstream modification ran.
The outer remote tool root has no committed HEAD; its actual wrapper/lock bytes
were verified against the reviewed local files, while both upstream source
repositories had the exact pinned heads.

## Exact execution and measured results

Executed through `ssh -o BatchMode=yes acs-recovery-linux`, beginning
**2026-10-18T10:27:51.653770Z**, with shell working directory as shown:

```sh
cd /root/acs-units/SHADER-TOOLS-002/repo
timeout --signal=TERM --kill-after=5s 180s env PYTHONDONTWRITEBYTECODE=1 \
  python3 tools/prepare_shader_tools.py batch --repo "$PWD" \
  --input "$PWD/.local/astral-shader-004/input" \
  --output "$PWD/.local/astral-shader-004/output-001" --jobs 1
```

The command exited **0** after **2.712 seconds**, including SSH and integrity
checks; the per-shader harness measurement was **125.6 ms**. The timeout was not
reached. The underlying harness command and arguments are retained in
`output-001/receipt.json`: pinned dotnet and harness DLL, `--batch` and `--out`
paths above, `--jobs 1 --spirv-val /usr/bin/spirv-val --target-env vulkan1.2`.

| Result field | Observed value |
| --- | --- |
| Code identifier | `6f573d87d0373cb9` |
| Stage / stages using block | vertex / 1 |
| Status | `ok`, no retry |
| Output | `6f573d87d0373cb9.spv`, 1,288 bytes |
| Resources column | empty; not a proof of runtime binding compatibility |
| Translator messages / error | empty / empty |
| Draw-time queries | `drawParameters` |
| Invalid / exception / timeout | 0 / 0 / 0 |

A separate SSH invocation, outside the wrapper's validation, began at
**2026-10-18T10:28:04.835079Z**:

```sh
/usr/bin/spirv-val --target-env vulkan1.2 \
  /root/acs-units/SHADER-TOOLS-002/repo/.local/astral-shader-004/output-001/6f573d87d0373cb9.spv
```

It exited **0**, stdout/stderr empty, **0.512 seconds** including SSH.
SPIR-V SHA-256:
`bfbf4ab9f8193b81362342a1cf1388f00b445b6b1e51edc0926dc488367ae0b2`.
All five output files were hashed remotely, copied to this worktree's fresh
`.local/astral-shader/output-001/`, and hash-verified locally. Previous outputs
and original inputs were not changed.

## Coverage, evidence and next gate

Measured numerator/denominator: **1 translated and independently validated / 1
submitted real graphics code/control pair**, representing one vertex stage.
No rejection occurred and translation of this pair is not blocked. This does not
establish coverage of the 1,451 structurally checked graphics wrappers or any
other shader population. Whole-game shader and variant denominators remain
unknown; compute shaders were not submitted and their format remains unresolved.

The next bounded unit should inspect this stage's draw-parameter assumptions and
resource/pipeline interface against actual guest draw state, then establish a
compatible linked pipeline and rendering evidence. Static accessor defaults,
bindings, visual correctness, other graphics stages, compute translation and
all-platform game coverage remain unverified. No render or gameplay success is
inferred from SPIR-V validity.

Private local evidence is retained under `.local/astral-shader/`: input provenance
in `receipts/input-check.json`; exact SSH/SCP commands, UTC starts, elapsed times,
exit codes and logs in `receipts/commands.json`; pre-execution toolchain snapshot
in `receipts/remote-toolchain.txt`; independent validation and all output hashes
in `receipts/independent-validation.json`; and the five original output files in
`output-001/`. Private helper scripts record the checks. Remote input/output
remains under the named `.local/astral-shader-004/` directory only. No agent,
authentication, provider or Windows cloud machine work was performed on the host.

Verification after rebasing onto current main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/prepare_shader_tools.py check-manifest --repo "$PWD" --input "$PWD/.local/astral-shader/input"
git diff --check
```

The manifest check reports `stages: 1`; diff checking passes. Only this safe
report is committed. Independent **Sol/high exact-head review is required before
`scripts/land`**, with no waiver. The parent commissions that review; this worker
has not spawned a reviewer, landed or pushed a branch.
