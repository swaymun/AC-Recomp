# Linux native cumulative startup: source 049

The completed parent run provides genuine Linux x86-64 native guest-startup
evidence for `linux-hid-cumulative-v1`. It reaches `nnMain`, APM configuration
and Npad initialization, then exits at unsupported `ShowControllerSupport`.
Configuration and linking succeeded; guest startup remains blocked. No game
visuals or gameplay acceptance are established.

This is LINUX-NATIVE-CUMULATIVE-055's local, evidence-only audit of the
18:43:58–18:52:50Z run on 2026-10-18. It performed no SSH, transfer, guest launch,
resource action or runtime change. The parent completion notice was treated as
untrusted input and checked against retained bytes and repository history.

## Reviewed source and preparation

The executed repository head is
`a3a1951d61785f2395e3441e6c46fa0a835160b6`, with normalized patch SHA-256
`639f32d7f5ad2a644079cedf98f49a948e9adfd5baad503d4b1280eb0d3449b3`.
Its independent Astra/medium pass is run `77be0e1deb7b45feab2ad565648cd1de`.
The exported review matches the store's review byte-for-byte: 3,501 bytes,
SHA-256 `045e5d4c922e630f3b049bb85efa78a887ff3854cbd96a1e4bb638995f12fe31`.
The review and producer have distinct run identities. The normalized patch was
recomputed using the orchestrator's normalization; source 049 is an ancestor of
the audit base `1c6dbeb46e0f45f83f31a6532ad570306f9f6ea6`.

The native receipt's `reviewed_head`,
`1a394ccc296f091115f273640560cd566f4af256`, is the supervisor's fixed source
ancestor, not the executed repository head. All 16 consumed helper/lock/overlay
identities match source 049's Git blobs. The wrapper is 25,397 bytes, SHA-256
`c3f004be809ac87adcd3481d1ec92b8c918f083df9ecb1495904481bd6f3bb9d`.
The staged Git bundle was rehashed directly inside the retained tar: 891,041
bytes, SHA-256 `1e91c01300271c18b963b6fd5774b1bdb559e6cc93723e49369e8dd2a4236aff`.

Wonder pin `010ed7a596a621c15d3a8dfa5795ca8c3668b066` and the prepared identity
bind this exact applied order:

1. `apple-memory.patch`
2. `astral-bootstrap.patch`
3. `astral-control-import.patch`
4. `astral-sqshl.patch`
5. `astral-audio.patch`
6. `astral-notifications.patch`
7. `astral-apm.patch`
8. `astral-ipc-buffer.patch`
9. `astral-applet.patch`
10. `astral-hid.patch`

Each composition entry's size/hash agrees with the exact source commit, records
`applied`, and retains its resulting source fingerprint. The prepared receipt
contains 450 final source records; the source-only composition contains 449
before the control header. Its SHA-256 is
`3c6e6048caabaa90ae8d832533b79b4a4324ea60d59ccb5193d1a23719077a42`.
The source fingerprint matches the parent request using the producer's
`json.dumps(source, sort_keys=True)` serialization. Canonical manifest SHA-256
is `fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`.
Generated/control receipt identities match the request and native receipt:
`a3c9827ead0ee15fbc3a7474b043d8bcb637a6672a849d7e1448344220e06d9a`
and `f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
Readiness reports 319 generated files; 315 generated translation units were
compiled. These counts describe different sets.

## Freshness and bounded execution

The historical readiness receipt, SHA-256
`a294d9d8b6126fd5b3ba112d8321961975b567fc2d1da4d6249e597b03bc533b`,
was rehashed and retained. Its 18:40:13Z expiry precedes execution and does not
authorize this run. The native receipt instead binds `receipt-1844.json`, issued
at **18:43:57.887988Z**. Execution began at **18:43:58.114922Z**, an age of
**0.226934 seconds**, within the supervisor's 600-second gate. No receipt time
was rewritten. Its `native_execution_performed: false` describes preflight at
issuance; the later stage receipts record execution.

All four control hashes match the staged tar, current store, readiness and
native receipt. They retain all four platform families, three workers including
reviews, (amount omitted) total, 20:30Z dispatch cutoff and 21:00Z deadline. This audit does
not authorize another run. Readiness records clean tracked source and live STOP
absence at preflight; those historical observations are not current readiness.

The supervisor records a 1,500-second total bound with 15 seconds reserved for
cleanup, three build jobs and one Xvfb-wrapped guest launch bounded to 60 seconds.
Overall execution finished at 18:52:50.133017Z, 532.018095 seconds after start.
The separately exported stage JSON values exactly match the native receipt.

| Stage | UTC start → finish | Elapsed | Exit |
| --- | --- | --- | --- |
| Configure | 18:44:01.646603 → 18:44:12.180643 | 10.534 s | 0 |
| Build/link | 18:44:12.747674 → 18:52:34.886455 | 502.139 s | 0 |
| Guest via Xvfb | 18:52:42.457206 → 18:52:43.191000 | 0.734 s | 1 |

All three stages report no timeout, log limit or signal. The host wrapper also
records exit 1. This is a measured guest failure after a successful build, not a
passing startup or a timeout.

## Compiler, objects and executable

The two exported compile-command lists agree for all 395 entries. Every command
contains `-DNX_ASTRAL_STRICT=1`, with no strict-off or undefine flag. There are
395 unique translation units: 315 generated and 80 prepared runtime sources.
Each recorded source SHA-256 agrees with the corresponding generated or prepared
fingerprint. There are 395 unique recorded object identities with positive sizes
and SHA-256 values, no reported missing objects, and corresponding object paths
in the Ninja log. Counts are **395 commands / 395 measured objects / 395 present /
0 absent**; they are compilation counts, not semantic coverage percentages.

All commands use `/usr/bin/clang++`; configuration identifies Clang 14.0.0.
The supervisor resolves it to `/usr/lib/llvm-14/bin/clang`, 137,056 bytes,
SHA-256 `31925065812631303cf9af9a30b2f56427d2102667a87a9fb4ba03a306104589`.
That compiler binary and individual source/object files were not exported.
Their recorded identities and correspondence were checked; their remote bytes
could not be independently rehashed in this local-only audit.

The actual exported `prepared/build/astral` was independently rehashed: 74,842,320
bytes, SHA-256 `6612937ac253d733b9f73f77c85ac12800ae40e21b4bf9b077b33fcd90dcb874`.
Its header identifies ELF64, little-endian, x86-64. Its identity agrees with both
manifest and runtime receipt, and the startup argv names that executable.
It was inspected as data and never executed locally.

## Measured successor and acceptance limit

The identical startup/trace logs contain 853 physical lines and match their
recorded hashes. In order, they show:

| Trace line | Measured event |
| --- | --- |
| 2 | Strict boot, host rtld replacement, main and SDK |
| 179–180 | Parental Initialize loads authenticated application context; account policy remains unknown |
| 189–190 | ILogger accepts a packet; later packets also appear |
| 781 | Guest enters `nnMain` |
| 824–827 | APM session configuration acknowledged; host clocks unchanged |
| 848–851 | InitializeNpad, supported IDs, handheld activation and style setup |
| 852–853 | ShowControllerSupport dispatch followed by the first fatal |

The complete first fatal line is:

```text
FATAL: hid: unsupported host capability: _ZN2nn3hid21ShowControllerSupportERKNS0_20ControllerSupportArgE
```

This advances Linux's measured startup boundary beyond the historical parental
command-1 failure. It does not establish complete service correctness or physical
controller input. The wrapper's post-run validation records unchanged prepared
source, canonical input manifest and generated identities, and revalidates the
private receipts. The actual final remote source/input bytes are not included
for a second local rehash; this remains a wrapper measurement.

Configure/build/startup session IDs are 6300, 6449 and 7321, each matching its
stage PID and recorded cleanup group. The supplemental parent cleanup check at
18:59:15.246288Z names those same sessions, reports no remaining members and
reports Codex/GitHub auth absent. Its own bytes were rehashed, but it is outside
the immutable ZIP manifest. This is retained parent cleanup evidence, not an
independent live `/proc` check or provider-deletion receipt. New-session escapes
remain a supervisor limitation. Parent exclusively owns resource closeout.

No screenshots or clips were supplied, and both result and native receipt record
no game frame. No `visual-updates.json` entry is manufactured. Xvfb settings,
GPU/dependency descriptions, source compilation and this trace do not establish
presented game pixels, advancing frames, input, audio, save or reload. Semantic
function/service/shader coverage remains unknown; cross-ISA byte match is N/A.
Other platforms and physical Apple devices gain no acceptance from this run.

The next concrete Linux capability is the bounded controller-support completion
already implemented separately in `astral-controller-support.patch`, with its
documented logical FullKey endpoint and strict ABI/policy checks. A follow-up
must integrate its independently reviewed exact bytes after HID into a newly
reviewed cumulative profile, then obtain fresh parent execution readiness.
The current ten-overlay identity cannot silently accept an eleventh patch.
The integration target is progression through controller confirmation into asset
access and real native window/layer presentation, followed by inspected game
frames and controllable input. The later Mac VI crash recorded in
`CONTROLLER_SUPPORT.md` is separate evidence; its Linux outcome is unknown.
This unit implements no successor and creates no diagnostic-only runtime fix.

## Private provenance and local verification

Let `P` be the absolute private directory
`$ACS_ROOT/.local/afternoon-control/linux-source-049-a3a1951d6178`, where
`$ACS_ROOT` is the repository checkout.
Immutable artifacts and raw receipts remain there, outside Git:

| File relative to P | Bytes | SHA-256 independently checked |
| --- | ---: | --- |
| `native-049-evidence.zip` | 21613631 | `4e991aee80afc2ba606b8d9b6977489b875e11f5cffba4af5aead52fae6cfa99` |
| `native-evidence/receipt.json` | 263577 | `f46ce7f35ff9db530c9c9cb2c241744c86f5e8c7973ddc9aab6243d8ba5bd974` |
| `receipt-1844.json` | 5753 | `4fcd87bd230c7ce799de9968f10739760c1cc44b4bea9c9caa859444c20b992c` |
| `native-evidence/evidence-manifest.json` | 2260 | `e0e4eba8dfe99029b15e802a1434419af1a00dc4d9905b685cc196513ab3b4c2` |
| `native-evidence/startup-trace.log` | 67449 | `6deff4ae7bbbafd2d0fc92da060ebf47eaae67f69e8332b2ca96791e5643f9ba` |

All 17 manifest entries were independently size/hash checked, including the
intentionally empty lock file, and all 18 ZIP members match the extracted
artifacts plus manifest with no duplicates or unexpected members. The ignored
audit at this worker worktree's `.local/linux-native-cumulative-055/audit.json`
retains every absolute artifact path/hash, 2,527 consistency checks, supplemental
receipt identities and the measurement gaps. It is 289,786 bytes, SHA-256
`fae76283d7991a08690d7e39cbb9a53be36ebc13b41073528ad255600435df62`.
These checks establish bundle consistency, not independently replayed execution.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_linux_runtime_startup.py -v
git diff --check main HEAD
```

The exact unittest command exited 0: 23 tests, 22 passed and
one Linux owned-session cleanup fixture skipped on macOS. Actual pinned-source
composition passed with ten overlays and 449 source files. The skipped Linux
test is not Linux cleanup acceptance. The committed documentation diff is also
checked with the exact second command; structured results accompany the worker
report.

Source 049's review is complete; this separate documentation result still
requires parent-commissioned Astra/medium review of its final exact head before
`scripts/land`. Nested workers are forbidden, so this worker neither commissions
that review nor lands itself. No review is waived. Historical LINUX-GUEST-027
remains `needs_split` with two failures; neither it nor 043 is reused as fresh
native readiness or silently reset.

## Bounded report correction

REPORT-CONTRACT-058 landed independently at
`4374add81e103f3a32d03d42f2bf9e7fec04c19b`. This final bounded correction rebases
only this document onto that main head and rechecks the immutable native export;
it does not rebuild or relaunch the guest. The original 2,527-check audit remains
unchanged. The ignored `.local/linux-native-cumulative-055/correction-audit.json`
records the repeated byte checks and provenance comparisons for producer run
`949c4cd44749475b9f715a386f609b23`.

The first monitor rejection remains authoritative with failure count one: the
previous report had empty `evidence[8]`. The final draft must contain only
nonempty evidence entries and pass the landed strict helper against the actual
clean committed branch, assigned unit row/run identity and current brief. That
preflight does not replace monitor acceptance or the parent's Astra/medium
exact-head review. A second failure requires a split or premise decision;
there is no third correction and no review waiver.
