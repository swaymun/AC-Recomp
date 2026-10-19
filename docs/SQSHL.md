# CPU-SQSHL-019: isolated observed-form semantics

This unit adds an **optional, separately applied emitter patch** against Wonder
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. It does not change runtime preparation,
the bootstrap patch, canonical generated code, service policy or parental startup.
Independent Astra/medium review of the committed whole result belongs to the parent
before `scripts/land`; it is required, pending and not waived. No nested reviewer
or worker was started.

## Inventory and supported scope

The clean pinned reference was checked read-only. Existing IPC-CALLER-014
`prepared-initial/prepared.json` receipt identities were revalidated against the
retained input manifest, both original NSOs and flat images, NPDM, and all **319**
canonical generated files. Manifest SHA-256:
`fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`.

All **eight** main SQSHL traps were independently decoded from original words in
the retained flat image using Capstone 5.0.6, and matched to their existing emitted
trap text. Every site is **AdvSIMD vector, register-controlled, 4S**: four signed
32-bit lanes in a 128-bit destination. Scalar sites: **0**; immediate sites: **0**.
Private words, operands, offsets and emitted bodies remain ignored. A separate
private site audit confirmed that the patched actual emitter accepts all eight;
this is emission evidence, not evidence that those instructions executed.

Only this form is supported. Other vector register arrangements, every scalar
form, every immediate form and by-element operands raise `Unhandled`, preserving
the emitter's existing fatal `nx::unimpl` path. All other shift handlers are
unchanged. The verifier checks both byte identity of the other **447** upstream
files and AST identity of all existing behavior in `recomp/emit_neon.py` after
removing the one added method.

Canonical retained reports remain main **27,763 functions / 2,569,143 handled /
8 unsupported**, SDK **33,573 / 1,302,326 / 0**. No full regeneration was performed,
so no new whole-module counts or changed-generated-site claim is made.

## Architectural contract and implementation

Primary source: Arm **DDI 0602 (ID032025)**, *A64 Instruction Set for A-profile
architecture*, **2025-03**, build **2025-03-21T17:41**,
[SQSHL register, printed pages 1862–1864; ShiftSat/SignedSatQ, page 6004](https://documentation-service.arm.com/static/67e40f3398aa3c3b6eea6a85).
The exact PDF is retained privately with SHA-256
`b7baa6869789722df70da60170d999a62810409aaabbb6db1ef729ed68686bdf`.
The checker requires these exact bytes; it never downloads them.

FPSR bit numbering and cumulative behavior were also checked in Arm
[Cortex-A55 Advanced SIMD TRM, 100446_0200_00_en, 2018-11-30, section 2.4, page 2-17](https://documentation-service.arm.com/static/5e7e16dfb2608e4d7f0a2f8b).
The retained primary PDF SHA-256 is
`d818bb3ae135fa21419026aaf61b4e3b79d7bfb6f62ec2cdf69aa75310191169`.

Each count uses its signed low byte. Negative counts perform arithmetic right
shifts; positive counts shift left and clamp to the signed lane range. Zero
remains zero at large counts. Saturation sets FPSR bit 27 cumulatively. The
implementation snapshots both sources before writing the destination, computes
bounded products in int64, and ORs QC into the existing 64-bit guest FPSR. Products
fit within int64; every executed shift has a valid count. Arithmetic right shift
uses the C++20 signed-right-shift rule. Counts at or beyond lane width take explicit
branches, equivalent for this operation to the architecture's ShiftSat bound.

The complete 128-bit 4S destination is written. Scalar and 64-bit-vector high-lane
clearing are **outside supported scope and explicitly rejected**, rather than
partially implemented. There is no production CPU-header or FPSR-helper change.

## Reproduction and measurements

From this worktree, retain the primary PDF at
`.local/cpu-sqshl-019/arm-contract.pdf`. The existing reference and dependency Python
are located relative to the repository's common Git directory. Explicit overrides
are available; no package installation is attempted:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/check_sqshl.py \
  --reference "$WONDER_PIN" --python "$EXISTING_VENV/bin/python" \
  --contract "$ARM_CONTRACT_PDF" \
  --out "$PWD/.local/cpu-sqshl-019/manual-check"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_sqshl.py' -v
git diff --check
```

Each check requires a fresh ignored output, the exact clean reference, Capstone
**5.0.6**, lz4 **4.4.4**, zstandard **0.24.0**, a native **macOS ARM64** host and a
working C++20 Clang compiler with UBSan and SQSHL assembly. Missing requirements
fail; required checks never skip. Only Python standard-library code runs in the
wrapper; installed emitter dependencies are imported in its bounded subprocess.
Each run makes an owned local clone, applies the actual shipped patch and invokes
the actual patched emitter. Synthetic fixture repositories also verify wrong-pin
and dirty-reference refusal. All child commands have timeouts; compilation uses
one sequential job. No credentials, network services or paid resources are used.

Measured on this Mac with Apple Clang **21.0.0**, C++20, `-O1`,
`-fsanitize=undefined -fno-sanitize-recover=all`:

- **85,200** synthetic vector instructions, **340,800** result-lane comparisons,
  all matching both the independent arbitrary-precision Python model and native
  ARM64 inline-assembly SQSHL; the generated emitter implementation runs under
  UBSan for every case.
- **31,251** saturating and **53,949** nonsaturating cases; **21,587** cases preserve
  an already-set QC without new saturation. QC clear/set/sticky and preservation
  of other guest FPSR bits are checked. Native comparisons cover architecturally
  writable FPSR bits; reserved/high guest bits are checked against Python only.
- Every low-byte count **-128 through 127**, unrelated upper count bits, signed
  boundary values, zero, large left/right shifts, heterogeneous lanes, 2,000
  deterministic random cases, and five alias classes: distinct, destination equal
  to either source, both sources equal, and all equal.
- **32** synthetic unsupported register/immediate form/shift combinations are
  rejected by actual dispatch and retain `nx::unimpl` through actual function
  emission. The supported width/arrangement is only **32-bit / 4S**.

Native code saves FPSR before the oracle instruction and restores it afterward;
restoration is read back and checked. No host state is adopted as guest state.
The synthetic native oracle is genuine hardware evidence for this CPU form only.

## Private evidence and remaining gates

All owned artifacts are retained beneath `.local/cpu-sqshl-019/`, including
`inventory.json`, `actual-site-audit.json`, `architectural-source.json`, the pinned
PDF, source clones and per-run `report.json`, synthetic generated C++, UBSan/native
binary, inputs and outputs. Reports hash the patch, generated synthetic C++, binary
and output. Final verification logs and exact-head receipts are retained there.
Initial inventory SHA-256:
`6dda05727aa2e398f522a909331bd2a10ced3544393045eaddc8362f02f7d25e`.
Actual-site audit SHA-256:
`8a370c2fac07b37c6d915ee40c439e424c7b3e0da516b014a0cb746903079bb5`.

There was no title executable integration, replacement of canonical output,
regeneration or game launch. The eight canonical traps and strict parental
command-1 startup blocker remain. Implemented/verified portable CPU arithmetic
for this form is separate from runtime integration and all-game semantics.

macOS/Linux remain **partial**; Linux execution of this unit is unverified.
Windows remains **blocked by unready Windows cloud machine controls**, with no paid start.
iPhone and iPad simulator acceptance remain **separately blocked**, **26.5 tested /
26.0 minimum target**; physical acceptance is **unverified**. Cross-ISA byte match
is **N/A**. Overall semantic, first-frame and gameplay coverage remain **unknown**.
All supervised children exited and were reaped. No task service was started;
private evidence is intentionally retained, so disk cleanup is not claimed.
