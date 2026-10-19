# Retained native Mac controller startup evidence

MAC-CONTROLLER-EVIDENCE-065 independently revalidates retained evidence from
exhausted MAC-CONTROLLER-CUMULATIVE-057. MAC057 remains `needs_split`, failures=2;
its malformed final report and correction narrative confer no acceptance. No
old report, receipt or failure counter was changed. This unit performs no native
configure, build or guest launch and implements no successor capability.

MAC-CONTROLLER-CORE-064 independently landed at
`e20d343d2a991cc91ea2c009b7da7ff014296f2e`. Its independent Astra/medium review
`ef637677a73b4f2ca7aeb382f450f222` passed that exact head and normalized patch
`08b93712c00f61b995bd4b857592410e0a885a951845bd952e381772c87042d2`, against base
`d9fd320c363e91b424a0b150d37fe1c853db63be`. The dependency row, distinct producer
and reviewer identities, review metadata/final result, patch and main/worker
ancestry were checked. That review covers supervisor code and synthetic
regressions; it does not independently accept this native evidence document.
Parent-owned independent Astra/medium exact-head review and guarded `scripts/land`
rebase, exact-patch and VERIFY remain required for this unit; no review is waived.

## Source and provenance comparison

The native measurement revision remains
`587fdd8dff4d784d6a55cf5f19cfd1b3fc68ad5c`, distinct from the documentation/report
head. Last untrusted MAC057 head
`a98781e83b5281be730cfa030c2aced8dc84f712` has identical supervisor text to that
measured revision. The measured supervisor hash was checked against its Git blob.
Its complete text becomes exactly the landed064 supervisor after only these two
changes: replace the receipt unit label with MAC-CONTROLLER-CORE-064 and remove
`require(len(commands) == 395, 'expected actual 395 translation units')`.
Whole-file supervisor byte identity is therefore **not** claimed. No other source
text differs; the extra historical count guard is independently checked below.

Using the current landed helpers, a fresh **source-only** preparation cloned the
pinned Wonder reference `010ed7a596a621c15d3a8dfa5795ca8c3668b066`, applied the
eleven authenticated overlays in this exact order and regenerated the canonical
control-context header. Its complete 450-file fingerprint map exactly matches
the retained native prepared source map, including unchanged upstream files and
untracked adapter/header files. The retained source files were also rehashed.
No runtime-source equivalence gap was found; this is evidence reuse, not a new
native measurement of the final documentation head.

| Order | Overlay | Retained/current SHA256 |
|---|---|---|
| 1 | `apple-memory.patch` | `a3d5225648bb88cae4dfa9647950745ac3f3de742c39fafe5c24387b2e741104` |
| 2 | `astral-bootstrap.patch` | `05f84f0025cc7074f157232e066288fae8f8b5c9ada535820cf2c5a2adff2f7c` |
| 3 | `astral-control-import.patch` | `106c66596d6c3f52a25bc222cf367ed4a7b561ce4f28095098bdcf776c58a63f` |
| 4 | `astral-sqshl.patch` | `e0e90c230e2a4c50eb2885a7d1298b24020158c67360303e2e36660fd44e4035` |
| 5 | `astral-notifications.patch` | `bb7e30290e0058bf4754e4f0c2e4f9f96ae955f564fb052c858c4ab9bc29fcea` |
| 6 | `astral-apm.patch` | `670ac4698ee7333b99ce3a5bc990be2f005359ea6076f45f69c56af3a1df9744` |
| 7 | `astral-audio.patch` | `19b27662567bdb1ef10f51e661e0c69798ae2b19bcdf81c96d76f1add2fcc121` |
| 8 | `astral-ipc-buffer.patch` | `6818e4f6d1aebc2c242601a7ec0736eb95062d7e53c6895f49c0ebc76d8e5808` |
| 9 | `astral-applet.patch` | `b9cda5617da673c458fba6f36c9480d52cca2ab6cd9a9260e60b8ebd01f527ed` |
| 10 | `astral-hid.patch` | `8a1b7a1b4a8b2c979a8a7bdeb1208075a2be0a09935b725841db0e152c4534fb` |
| 11 | `astral-controller-support.patch` | `1c04ccc2999628da86a72dcca0e20572399c83d78517e02bb768d8da544743ba` |

The complete dependency profiles were recomputed through landed064's
`cumulative_patches` and exactly matched the measured profiles: LOGGER029,
AUDIO032, NOTIFY033, IPC039, APPLET044, HID045, CONTROLLER051 and APM030. This
includes historical whole-scope review authentication, exact normalized patches,
review receipt hashes, reviewed/landed file identities, supersession checks and
both ancestries, rather than accepting a retained report's verdict alone.
Shared preparation also matches exactly: IOS041 review/consumed helper plus all
ten support-file identities. MAC056's historical whole review and exact current
`safe_observations`/`LIMIT` fragments match the measured parser profile. Its
landed/reviewed heads are `1c6dbeb46e0f45f83f31a6532ad570306f9f6ea6` /
`8d75571cef2e93cc602cba03f114abc5b0c7f119`.

Current authorization/control-file digests match those consumed by the native
measurement: deadline 21:00Z, dispatch cutoff 20:30Z, (amount omitted) total, cap three including
reviews, game mode and all four platform families. Canonical module/NPDM input
validation, main/SDK generated-file hashes and extents, and control metadata/header
were independently recomputed. Manifest SHA256 is
`fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`;
control receipt SHA256 is
`f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
No credentials were read.

## Retained commands, objects and cleanup

All 879 identities in the original retained-file map were rehashed without
mutation, including raw journals, source, compilation database, objects and
executable. All 395 compilation-database entries name distinct translation units;
each has exactly `-DNX_APPLE_HIGH_MEMORY=1` and `-DNX_ASTRAL_STRICT=1`, without an
undefinition/alternate value. Main and SDK generated modules are present. All
395 distinct object outputs resolve inside the retained build and match their
recorded sizes and SHA256 values. Executable identity is 56,090,504 bytes,
SHA256 `87e7b81920a319ad1027d17edf14988a57b6e32bafbf243a92eec186e0477208`.
Compilation database, command arrays and stage log hashes match their original
measurement records. Build command used `--parallel 2 --target astral`.

All dates below are 2026-10-18 UTC; these are original receipt times, not new runs.

| Stage | Start → finish | Elapsed | Bound | Exit | Observed owned groups |
|---|---|---:|---:|---:|---:|
| Configure | 19:08:43.978197 → 19:08:46.561099 | 2.582948 s | 1200 s | 0 | 3 |
| Build | 19:08:46.666552 → 19:20:14.673157 | 688.007232 s | 1200 s | 0 | 399 |
| Guest startup | 19:20:27.605533 → 19:20:30.641245 | 3.035764 s | 60 s | -11 | 1 |
| Outer supervisor | 19:08:27.762537 → 19:20:35.235613 | 727.473654 s | 1090 s | 1 | 403 |

The outer bound sits within the original 1100-second command budget. Every stage
and outer receipt reports `timeout=false`, `output_limit=false`, and an empty
owned cleanup-group list. Stage receipts and log identities were checked against
the measurement, then the outer journal/log chain was checked separately. This
supports the recorded completion of owned cleanup; it does not establish an
independent historical OS process census. No new process was launched to reproduce
the fault. The supervisor's filtering permits only PATH/HOME/TMPDIR/SDKROOT/
DEVELOPER_DIR before adding compiler/trace settings; no scripted input is present
in its launch environment construction.

## Independently inspected first failure

The complete trace and startup log are byte-identical: 830,951 bytes, SHA256
`7a4e0825829d4a2ba72c54bac612f0737e68d96640288a93d949d3924005d599`, below the
16 MiB output cap. Inspection covered all physical lines. ShowControllerSupport's
argument-only overload is recorded at line 866, followed at line 867 by logical
FullKey policy `min=1 max=1 takeover=1 single=1 connected=1 result=0`. This is an
observed service result for an existing logical connection, not observed physical
controller input or proof of complete controller semantics.

The first CRASH/FATAL physical line is line 11097, fully LF-terminated, 210 bytes,
SHA256 `b05b6729a6f9fcb43d92f71ca347c48d26a7b9295deef3311d6b1cc12e35504e`.
The entire line was inspected, including its executable path and suffix, rather
than accepting a bounded prefix. It records signal 11, native executable offset
`+268e09c`, data address zero. The immediate successor context records guest LR
`sdk+39d7d0`, `nn::vi::SetLayerScalingMode +0x30`. No earlier CRASH/FATAL line
occurs. This is the first observed failure after controller support; its root
cause and semantic coverage remain unknown. No successor service implementation
or successful recovery is claimed.

The original startup exit is -11. The unchanged strict IPC parser yields a null
IPC boundary for this out-of-grammar native crash. The original measurement
therefore remains `blocked=ValueError`, `first_unsupported_boundary=null`,
`input_validation=pending`; the supervisor exit remains **1**. This failed IPC
measurement is not promoted to successful IPC acceptance. The original post-run
source/input booleans are true, and the retained identities now rehash correctly;
those facts supplement rather than rewrite the failed measurement.

Original measurement SHA256 is
`e3e18ac7fad53c549ba78cbb9306f2b31d2dec3aa435d034316675125a6da9dc`
(402,008 bytes); original outer supervisor SHA256 is
`5b2d01481062f76f16622dece0597989b9426f23ac6ad86f6e9fe947f20e951c`
(2,230 bytes). Both were checked again after the read-only audit.

Original private evidence remains under the store's
`worktrees/MAC-CONTROLLER-CUMULATIVE-057/.local/mac-controller-057/`, especially
`native-1/measurement.json`, `supervisor.json`, stage journals/logs, source and build.
This worker's ignored `.local/evidence065/` retains the independent audit script,
receipt and source-only recomposition. Raw evidence and game-derived files remain
ignored, outside Git, and are retained rather than deleted.

## Acceptance limits and verification

No game frame or advancing clip was inspected or obtained by this unit. Gameplay,
input, audible audio, save and reload remain unverified. No visual reference match
or recording acceptance follows from startup or window/layer creation. Windows,
Linux, iPhone simulator and iPad simulator remain separate required targets; no
acceptance is inferred for them or any physical device. Cross-ISA byte match is
N/A; unmeasured semantic coverage is unknown. Providers, transfers, paid inference,
credentials and unrelated devices/services were untouched.

Required checks are the exact service supervisor unittest discovery command and
`git diff --check main HEAD`. The committed worker report records their actual
exit codes and observations, the frozen report-time base/head/normalized patch,
and offline report preflight. A valid report does not replace independent review
or native/gameplay acceptance.
