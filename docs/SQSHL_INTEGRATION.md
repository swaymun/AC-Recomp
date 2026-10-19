# CPU-REGEN-020: private SQSHL regeneration and native integration

`tools/regenerate_sqshl.py` performs one bounded main-only lift with the accepted
SQSHL patch. It never writes canonical inputs/output, lifts SDK, installs a
package, starts a service or launches the title. All derived bytes and detailed
site identities remain ignored beneath this worktree's `.local/cpu-regen-020/`.
Only the original wrapper, synthetic tests and this document belong in Git.

The required predecessor is CPU-SQSHL-019 at
`942747883cce902b7d06c0c541cb02d9f64f613f`, independently accepted by
Astra/medium review `3b0d2309ca254491bda3479cad6a8ac3` and landed by the parent.
Portable arithmetic acceptance (85,200 native/bigint/UBSan cases) belongs to that
unit. This unit separately checks fresh regeneration and native compilation;
neither establishes instruction execution in the title or gameplay coverage.

## Refusal and audit contract

The standard-library wrapper requires the clean Wonder pin
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`, exact shipped patch, exact accepted
private inventory/site-audit hashes, exact preparation receipt and input manifest.
It validates NSO/flat/NPDM bytes and metadata using the existing reviewed
preparation validator. It compares all 319 canonical generated files with the
retained receipt and checks actual site words against the retained main flat
image. Missing provenance is a blocker, never an inferred default. Inputs are
resolved from preparation receipts, not from personal dump directories.

Data/reference/output symlink arguments and members, multiply linked files, unsafe output placement,
existing output, overlap, wrong identities and a dirty reference are refused.
The output must be a fresh descendant of this unit's ignored directory. The
local source clone uses `--no-hardlinks`; only `recomp/emit_neon.py` may change
when applying the shipped patch. Installed Capstone 5.0.6, lz4 4.4.4 and zstandard
0.24.0 are checked before generation. The actual pinned `python -m recomp`
command lifts the full main module once with its ordinary analysis and emission
path, with no function filter. SDK files are copied into independent files and
must remain byte-identical.

The audit constructs an expected output from the accepted baseline by replacing
each of exactly eight inventoried fatal statements with its independently
accepted emitted statement. Each replacement must occur exactly once and carry
the accepted emission hash. Every output file must then match that expectation
byte for byte. The deterministic coverage report receives only its exact count
change and removal of its SQSHL unsupported row. Any other byte, inventory or
report difference fails. Detailed per-file before/after hashes and private site
identities are retained in `regeneration/report.json`; no game-derived operands,
offsets or generated source are included here.

The real patched dispatcher is additionally exercised on the predecessor's 32
unsupported forms, requiring `Unhandled` and the actual function emitter's fatal
`nx::unimpl` behavior. Support remains vector-register 4S only. Scalar,
immediate, other arrangements and unsupported operands retain fatal behavior.
No other instruction emitter or runtime service behavior changes.

Every owned subprocess has a shared wall-clock deadline, a separate process
group, retained argv/cwd/UTC/log/exit receipts and timeout termination/reaping.
Failures preserve their output and report instead of retrying a real lift.

## Reproduction

Supply the exact paths from verified existing receipts:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/regenerate_sqshl.py \
  --reference "$WONDER_PIN" --python "$EXISTING_VENV/bin/python" \
  --inputs "$VERIFIED_INPUT_ROOT" --baseline "$CANONICAL_GEN" \
  --receipt "$IPC_CALLER_INITIAL_PREPARED_RECEIPT" \
  --inventory "$ACCEPTED_INVENTORY" --sites "$ACCEPTED_SITE_AUDIT" \
  --out "$PWD/.local/cpu-regen-020/regeneration" --timeout 600
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_regenerate_sqshl.py' -v
git diff --check
```

The tests use temporary Git repositories and a synthetic emitter invoked through
an actual Python subprocess. They exercise cloning, patch application,
main-only argv, SDK copying, exact-site/report auditing, unexpected output,
missing sites, wrong pin, dirty reference, wrong provenance hashes, existing or
unsafe/overlapping output, hardlinks/symlinks, failed children and timed-out
process-group cleanup. They use no game inputs, credentials or network.

Native preparation uses the existing `tools/prepare_runtime.py` with the owned
combined generated directory and fresh output, `--configure --jobs 3`, installed
CMake/Ninja/Homebrew dependencies and retained Vulkan headers. It applies the
existing Apple-memory then bootstrap patches without new runtime behavior.
The private build driver and full commands remain in the evidence directory.
Compilation uses at most three jobs, with no object reuse. Source/patch/input
identities must match the retained IPC-CALLER-014 receipts apart from the audited
generated main output. Actual compile commands must retain strict mode and
Apple high-memory mode. The build records compiler/tool hashes and versions,
current Ninja dependency bytes, explicit linked-library hashes and the exact
executable hash. The executable is never launched.

## Acceptance boundaries

Independent Astra/medium exact-head whole-result review is required before
`scripts/land`; the parent owns that review and landing. No nested worker,
review, provider, SSH, authentication, paid inference, mobile or Windows action,
push or PR is authorized by this unit. The unchanged strict parental command-1
startup gate remains blocked on program/control metadata. Compilation cannot
resolve or claim passage through that gate.

macOS/Linux are partial pending gameplay. Windows is blocked by unready Windows cloud machine
controls with no paid start. iPhone and iPad simulator acceptance are separately
blocked, 26.5 tested / 26.0 minimum. Physical acceptance is unverified. Overall
semantic/gameplay coverage is unknown; cross-ISA byte match is N/A.

## Measured regeneration

The single real main-emitter command ran **2026-10-18T12:56:59.225447Z–
12:58:28.980870Z**, exit **0** (89.755 seconds). Full wrapper evidence spans
12:56:56.249542Z–12:58:33.419517Z. Validated counts:

| Module | Baseline functions / handled / unsupported | Owned output functions / handled / unsupported |
|---|---|---|
| main | 27,763 / 2,569,143 / 8 | 27,763 / 2,569,151 / 0 |
| sdk | 33,573 / 1,302,326 / 0 | 33,573 / 1,302,326 / 0 |

Of **319** files, **317** are byte-identical, including all **110 SDK files**.
The remaining files contain exactly the eight accepted statement replacements
in one main translation unit and the deterministic coverage-report change.
Jump-table and unresolved-indirect-branch counts are unchanged. The audit
accepted every byte and all 32 unsupported-form checks passed. Canonical
NSO/flat/NPDM/manifest/generated bytes and the clean reference were revalidated.
Regeneration report SHA-256:
`4550554fc4715c750e3dd71943e9b4968a2cbcd5539441100a33932219a3b6d5`.

The initial preparation invocation was refused before creating runtime output
because its `--repo` identified the worktree instead of the common repository
that owns canonical private inputs. Its argv/log/exit are retained separately
under `prepare-refusal/`. The corrected preparation uses the common repository
for private-path validation and this worktree's reviewed preparation tool and
patches. No real regeneration was repeated and no objects were reused.

## Measured native compilation and cleanup

Corrected fresh preparation/configuration ran
**2026-10-18T12:59:32.211561Z–12:59:39.804509Z**, exit **0**. The exact UTCs and
argv are authoritative in `commands.json`. Prepared-receipt SHA-256:
`3167d0b7676b1011edabd9965ddd7bc4ee36ff65907fb8d80abf387de3fc0f52`.
All **449** prepared source identities and both runtime patch hashes match the
retained IPC-CALLER-014 preparation. SDK generated identities and the input
manifest also match that predecessor.

The clean build ran **2026-10-18T12:59:40.614142Z–13:05:39.534599Z**,
exit **0**, **358.920 seconds**, with **three compiler jobs**. All **395** compile
commands retain strict mode and Apple high-memory mode. No objects were copied
or reused. Apple Clang **21.0.0**, CMake **4.4.4** and Ninja
**1.13.2.git.kitware.jobserver-pipe-1** identities are recorded with executable
hashes. Current compiler/header/library identities cover **1,678 dependency
files**; supplementary receipts hash the installed Python packages, compiler
shims/linker, SDK settings and SDL CMake package files. System-library runtime
execution is not a claim from these static build receipts.

Exact unlaunched executable SHA-256:
`b24129a0374ccdc459cfaea2a21566dd32d14462d4d9bf279af2530c5548ab49`.
Dependency-identity receipt SHA-256:
`6bfba5f53f477ef3cd888014f7afde60d69536dd68ca158fcb3f85244bcb5fa5`.
Supplementary toolchain receipt SHA-256:
`8c6225c34fb8b0705807c7d8d5d6ce441e49be3e4677816874aaa42cefd58a36`.

`validate_final.py` reuses the final original audit to revalidate all output
bytes, canonical NSO/flat/NPDM/manifest/generated identities, clean reference,
patched emitter source, prepared runtime source and executable hash without
another lift or launch. `final-validation.json` binds these receipts to the
committed head. All **15** recorded owned commands, including the refused first
preparation, exited and were reaped; a process-table check found no remaining
owned subprocess. Private evidence, source clones, generated output, objects and
executable are intentionally retained rather than deleted. No title process or
service was started.

The final prescribed suite contains **17 passing tests**. Review remains
**pending**: independent Astra/medium must review this exact committed whole
result before the parent runs `scripts/land`. No waiver or nested review occurred.
Portable semantics, fresh regeneration and native compile evidence are distinct;
the unchanged blocked parental startup and all platform/gameplay limitations
above remain in effect.
