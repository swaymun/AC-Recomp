# Astral texture format lookup (NVN-TEXTURE-072)

The post-NVN-INIT-070 fault was a read from an inherited Wonder SDK table
outside Astral's mapped SDK. The strict overlay now reads Astral's own format
records through supplied, validated metadata (the format profile). Default-profile lookup
and the existing storage-size/alignment calculations are unchanged.

The local SDK's layout helper and storage-size accessor independently establish
the record stride, block dimensions, bytes per block, and texture-valid flag.
Its relocation identifies the table. These facts agree with the inherited field
interpretation; the table location does not. Disassembly, relocation evidence,
SDK identity and records remain in ignored storage, never in this patch. The resulting profile for Astral
Chain 1.0.0 is published in `tools/acr_build.py` (see below).
The examined format prefix is deliberately bounded; formats beyond it are rejected.

## Profile contract

Set `NX_NVN_FORMAT_PROFILE` to the profile file before launching an Astral build. The first token is `NX_FORMAT_PROFILE_V1`, followed by nine unsigned
hexadecimal values: module-relative table offset, examined record count, stride,
width-byte offset, height-byte offset, bytes-per-block offset, flags-byte offset,
required flags mask, and FNV-1a-64 fingerprint of the entire examined table span.
No file contents or addresses are built into the runtime adapter itself.

The profile is factual metadata about the SDK's layout (a module-relative offset, record layout numbers and
a fingerprint), comparable to the function offsets these notes cite; it contains no game bytes.
`tools/acr_build.py` carries the profile for Astral Chain 1.0.0 (`KNOWN_FORMAT_PROFILES`). Its data stage
recomputes the FNV-1a-64 fingerprint over the player's own SDK image (`analysis/sdk.bin`), writes
`<data root>/astral.profile` only on a match, and fails with an "unsupported game version" message otherwise.
The app's launch script sets `NX_NVN_FORMAT_PROFILE` to that file. `--nvn-format-profile <file>` overrides the
built-in profile and gets the same check.

The adapter validates geometry, SDK bounds, readable mappings and the table
fingerprint before reading a record. Missing/malformed metadata, mismatched
fingerprints, invalid records and unmapped formats terminate with an explicit
strict error. FNV detects accidental mismatch; this is trusted local metadata,
not an authentication mechanism. The profile is initialized once, after SDK load.
It does not select a fallback format or bypass an SDK/game gate.

## Verification and actual startup

The test compiles the patched production layout translation unit under strict
and default profiles. Synthetic fixtures cover malformed/missing metadata,
range/geometry/readability errors, absent SDK, fingerprint mismatch, invalid
flags, zero dimensions/size, out-of-range enums and retained default fallback.
It exercises storage-size/alignment handlers and register preservation with
controlled builder getters; it does not execute the SDK's getter functions.

A private evidence receipt additionally drives the same production code with
real SDK records: the observed startup format, small uncompressed formats,
compressed block formats, the last examined record, mip levels, pitch-linear
storage and block-rounding boundaries. The actual first builder is 1600 by 900,
one layer and one level; zero samples normalize to one. The regression expects
6,553,600 bytes with 8,192-byte alignment. The native texture log agrees on size.
Expected layout totals are hand calculations of the inherited algorithm, not
an independent reference-driver oracle. Multisampling, 3D/cube/array behavior,
flags, packaged layouts and all integer extremes remain unproven.

`NVN_TEXTURE_EVIDENCE` can name the private receipt. The unit worktree's retained
receipt is used automatically when present. Without it, tests explicitly report
synthetic-only coverage; they do not claim SDK validation.

The independently passing, landed 070 source and executable were compared and
preserved before applying this overlay. All thirteen preceding overlays,
including VI and NVN API identity, remain applied. Normal Ninja incremental
build, two jobs: **3.069 seconds, exit 0**, one translation unit and relink.
No clean build, regeneration or build-metadata reconstruction occurred.

Native launch at **2026-10-18 21:04:10–21:04:13 UTC** passed texture setup and
exited 1 after **2.889 seconds** at `strict IPC missing service: hwopus`.
A second bounded launch under LLDB captured the first builder and stopped at
that fatal: `make_service` via service-manager IPC, called during audio startup.
The presented-frame counter was **zero**. The stopped target was explicitly
killed; both launches were bounded to 60 seconds and all owned processes reaped.
No screenshot/clip, logo, title/menu, loading image or gameplay is verified.

## Next scope and limits

A successor unit needs an SDK-evidenced `hwopus` service/decoder implementation
and focused IPC/audio tests, likely a new `runtime/src/svc_hwopus.cpp` service registered through the
existing IPC factory, plus any necessary `runtime/src/hle_audio.cpp` integration. Service registration alone cannot claim a
working decoder. Exact commands and buffer contracts need investigation before
choosing the final implementation scope. This unit does not edit those paths.

Player builds get the profile automatically from `tools/acr_build.py` (above). Automatic provisioning in
`tools/service_batch_startup.py` remains a separately scoped integration task; a different SDK needs a newly
derived and reviewed profile.

Mac native startup is partial progress. Platform/gameplay acceptance remains
untested by this unit for macOS, Linux, Windows and iOS/iPadOS; neither simulator
was run, and simulator results cannot establish physical-device acceptance.
Independent review and landing belong to the parent and remain pending.

Private receipts, source/executable snapshots, tests, profile and diagnosis are
retained in `.local/nvn-texture-072/`; `observed-result.json` indexes their hashes.
Only original adapter/test/notes are committed. Upstream licensing and dependency
notices continue to apply; no SDK records, code or assets are included in
tracked files.
