# Astral NVN API identity (NVN-INIT-070)

The first crash after VI FitToLayer was a cleanup fault caused by an NVN API
version mismatch. The Astral overlay now reports its bundled driver's API
**53.310**, selected by the existing `NX_ASTRAL_STRICT` build definition. Other
builds retain 55.15. No capability, renderer, guest branch, or cleanup behavior
is changed. This corrects API identity; it does not prove full API compatibility.

## Evidence from the owned local binaries

069 executable SHA-256:
`bb4461a89ba75630b3a7030a295bb23ca1f89fbd5c97f95dbd5ba074206fe459`.

- Host `main_009AAB00 + 264` (executable + `0x1c2d69c`) reads eight bytes
  through a null list pointer plus 8. The pointer comes from the cleanup
  object's offset `0x28`; this corresponds to guest `main+0x9aab4c`.
  LLDB reproduced the fault and the caller `main_003DF8E0`.
- The preceding queries are pnames 0 and 1, called from `main_009DC5B0`, with
  guest return addresses `main+0x9dc664` and `main+0x9dc678`. The caller requires
  major exactly 53 and signed minor at least 310. The inherited 55/15 response
  returns false from initialization; failure propagates to startup cleanup.
- Astral's real query entry is `sdk+0x3f9f40`, confirmed through the runtime's
  resolver. Its helper at `sdk+0x3fb230` uses the table at `sdk+0xa0e23c`:
  selectors 0/1 resolve to returns of 53/310. Both the generated translation
  and original local binary disassembly were checked. No proprietary source
  or binary is included here.

## Verification on 2026-10-18

The focused test compiles the actual patched NVN translation unit and real HLE
registry with every preceding Mac overlay. It executes both Astral and default
profiles, checks exact version values, four-byte output writes with adjacent
guards, 32-bit enum arguments, register preservation, device-independent version
queries, and representative unchanged capabilities/unknown-query behavior.

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_nvn_init.py -v
git diff --check
```

069 remains intact. Its source, receipts, logs and executable were additionally
preserved before experiments. A source clone and a new build use stable private
paths under `.local/orchestrate/2026-10-18-evening/native-current/`. Relocation
required one ordinary CMake/Ninja build: 395 translation units, two jobs,
210.589 seconds, exit 0. The subsequent incremental check took 0.432 seconds,
exit 0, with no work required. No dependency metadata was rewritten.

Source/input comparison found only `runtime/src/nvn/nvn_device.cpp` changed from
069; all twelve preceding overlays and generated inputs matched. Both strict
and Apple high-memory definitions are present in every compiler command.

Current executable SHA-256:
`cb146805ff094bbe06877fe4b9a71dff81616153f913a06bb03df1757c46c946`.

The actual run at 20:48:56–20:48:58 UTC passed the version check and reached
texture setup. It then exited on signal 10 after 1.577 seconds. A final LLDB
launch without `NX_NVN_REAL` reproduced the same failure. The three actual
launches (baseline debugger, corrected native, corrected debugger) each had a
60-second bound and were reaped; stopped debugger targets were explicitly killed.
An earlier LLDB command failed before launching a process and is recorded too.

## Successor blocker and limits

`nvnTextureBuilderGetStorageSize` now faults in host `format_info(0x25) + 84`,
executable + `0x624dc`, guest LR `main+0x9d25b0`. The implementation in
`runtime/src/nvn/nvn_texture_layout.cpp` uses Wonder SDK 16.2's table offset
`0xd34198` and a `0x30` stride. Its read at
`sdk_base + 0xd34198 + 0x25*0x30 + 8 = 0x7010d34890` falls in a no-access region
in Astral's mapped SDK. This is confirmed by host disassembly, registers and
LLDB's memory-region query, rather than inferred from the last HLE log.

A follow-up overlay needs to establish Astral's format-table location and layout
from its bundled SDK, with storage-size regression coverage and another native
run. The table offset is not changed in this unit. The automatic overlay list
in `tools/service_batch_startup.py` also needs a separately scoped integration
update for VI and NVN; this measurement applied both explicitly.

**No rendered frame, logo, menu, loading scene, or gameplay is verified.** No
screenshot or clip was captured. Input/audio and other platforms are untested
by this unit. Existing later NVN behavior remains outside this result.

Private commands, disassembly, source/binary snapshots, stage receipts and logs
are retained in this worktree's `.local/nvn-init-070/`; `observed-result.json`
indexes the evidence and hashes. Independent Sol/high review and landing belong
to the parent and are pending.
