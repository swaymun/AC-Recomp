# Astral runtime assumptions audit — TITLE-ASSUMPTIONS-071

**First disjoint runtime fix: remove the inherited SDK-specific texture-format
table lookup.** Its table lies beyond Astral's loaded SDK image and BSS. A
separate shader-product handoff is also absent at the measured Mac data root.
These are static findings from this lane. NVN-INIT-070 owns startup crash
diagnosis; its newly landed notes independently report the same texture-path
successor after fixing API identity. No runtime implementation or launch
occurred here.

## Evidence identity and limits

All upstream paths/line numbers below refer to public SuperMarioWonderRecomp
**`010ed7a596a621c15d3a8dfa5795ca8c3668b066`**. Both supplied source checkouts
report that Git HEAD, but have local overlays. Public comparisons therefore use
`git show <pin>:<path>`, not the dirty reference checkout's working files.

Observations began on ACS revision `a60c20d34be0662fe0118a40e7c79285e905bd33`;
the audit was rebased onto `1454e822cf6bef637c404799903a45001a15bc33`
(070's API-identity overlay) before completion.
Selected current files were copied read only from the evening
`native-current/source` at **2026-10-18T20:53:50Z**; additional bounded source/input
checks were recorded at **20:57:39Z**. The format proof separately rechecked the
live layout file against its snapshot. Exact timestamps, per-file hashes and
original paths are in ignored `.local/title-assumptions-071/`. This identifies
selected bytes, not an immutable revision of 070's evolving source/build.

Canonical inputs and the existing generated directory were located through
069's retained `measure.py`/`measurement.json`. Only the two canonical modules,
NPDM, selected generated SDK bodies/table metadata and existing trace evidence
were examined. No generated-tree hashing, regeneration, build, native run,
debugger, simulator or provider operation was performed. Original 069 receipts
remain untouched. SDK identifying metadata references the **6.4.0 family**;
upstream's device/format comments describe **16.2**. That difference alone is
not a defect.

## Prioritized findings

### 1. Confirmed mismatch — texture format table is outside Astral's SDK

**Public location:** `runtime/src/nvn/nvn_texture_layout.cpp:19–36`,
`format_info`; consumers `compute:53` and
`runtime/src/nvn/nvn_objects.cpp:272`, `TextureInitialize`.

**Assumption:** find the module exporting `nvnBootstrapLoader`, then read format
metadata at the fixed SDK 16.2 table location, using a fixed entry stride/count.
The nonzero-field fallback happens after the dereference.

**Actual Astral evidence:** `format-proof.json` binds the original SDK NSO/flat
hashes, its actual dynamic export, MOD0 BSS and the generated `nx_module_sdk`
metadata. The earliest table-field read already exceeds the SDK's entire loaded
extent, including macOS host-page rounding. The current layout file is identical
to the public pin. `loader.cpp::load_modules` commits only the image/BSS extent;
`platform_mac.cpp::reserve/commit` leaves the remaining reserved pages protected.
Exact private coordinates and arithmetic are retained only in that receipt.

**Impact:** the inherited lookup is invalid for this actual SDK; a storage query
or texture initialization can read outside the committed SDK before computing
allocation/upload geometry. This lane establishes a confirmed incompatible
lookup without executing it. The newly landed `docs/MAC_NVN_INIT.md` at the
rebase revision independently reports a native fault on this path; its debugger
receipts were not re-investigated here. Live protections remain unmeasured by 071.

**Next validation:** independently locate Astral's format metadata through its
own SDK getters/references, or verify an original format description against
that metadata. Check uncompressed, block-compressed and depth formats, mip/layer
sizes and alignment; verify all reads are bounded by the selected SDK. Do not
substitute an unverified SDK offset or generic four-byte fallback. Use 070's reported storage-query failure as the parent-owned native regression
case after the bounded fix; this audit does not rerun it.

### 2. Confirmed integration mismatch — measured data root has no shader products

**Public location:** `runtime/src/nvn/nvn_shaders.cpp:243–301`, `shader_for`;
`nvn_program.cpp:29–54`, `set_shaders`; `nvn_draw.cpp:261–274`, `draw`;
`runtime/src/platform_mac.cpp:217`, `data_root`.

**Assumption:** translated hash-named SPIR-V and resource records are installed
under the selected data root's `spirv/` directory. There is no live translation
or alternate lookup on a miss.

**Actual Astral evidence:** the canonical root selected by 069's launch driver
has neither that directory nor `results.tsv` at the audit check.
`graphics-handoff.json` records the path-selection chain and directory state.
The earlier selected vertex success and the two-representative extraction in
`docs/ASTRAL_SHADER_BATCH.md` do not establish installed products or a linked
pipeline. 070's subsequent launch environment is not certified here.

**Impact:** at this root, future shader lookup cannot find products; missing
stages are omitted while `ProgramSetShaders` returns success, and empty programs
or missing vertex stages skip draws. The actual first shader set, resource
requirements and resulting visuals are unknown.

**Next validation:** preflight an explicit private runtime shader package against
accepted translation receipts, exact shader identifiers and resource rows.
Preserve the canonical inputs. Parent then captures the first actual shader
hash requests and linked vertex/fragment pipeline; two arbitrary representatives
are not a sufficient runtime package or coverage denominator.

One metadata-only atomic notification was sent for this early handoff finding.
The later format-table finding is included here without a second notification.

### Remaining bounded checks

Each location in this table uses the same public pin above. “Adapted” identifies
an existing code change, not new behavioral acceptance.

| Classification / public location | Assumption and actual Astral evidence | Impact / precise next validation |
| --- | --- | --- |
| **Already adapted; now on main via 070.** `nvn/nvn_device.cpp:12–15,118`, `kDeviceInfo` / `nvnDeviceGetInteger` | Public API identity is Wonder-specific; the current snapshot contains a strict-Astral version branch. Other query constants remain inherited, including explicitly provisional device-derived fields. This audit did not retrace the fault or independently validate 070's version proof. | Keep version/caller/crash work with 070. Validate remaining queried IDs against Astral's own driver and actual callers individually; changing the API identity does not certify the rest of the table. |
| **Generic reusable mechanism, ABI risks unknown.** `nvn/nvn.h:1–7`; `nvn_trace.cpp::driver_serves:80`, `real_proc_slow:170`; `nvn_objects.cpp::MemoryPoolInitialize`, `nvn_state.cpp::BindVertexAttribState` | Builders/state getters run Astral's own recompiled SDK and active host objects are keyed by guest address, avoiding a universal host struct overlay. Selected actual SDK getter bodies and the retained procedure-resolution trace support that mechanism. No complete enum/object-size/callback ABI comparison was made. Program entry strides, mapping-request layout and shader-control fields remain fixed. | Do not label every Wonder comment an ABI defect. Compare the first actually used compound entry/callback against its Astral caller and SDK body; validate output widths, float returns, sizes and control extents before use. |
| **Plausible risk.** `nvn_trace.cpp::proc_address:87`, `trace_stub:53`; `nvn_program.cpp::set_shaders:29` | Unknown NVN procedures still receive tracing fallbacks; initialization names can return success. Strict generic imports/IPC do not automatically close this separate fallback path. No executed unsupported Astral procedure was established by this audit. | A future first-call trace must distinguish real HLE, guest driver and fallback. Scope a strict NVN policy only after enumerating required procedures; do not infer support from successful procedure lookup or returned success. |
| **Plausible title-hook risk; ordinary crop path reusable.** `nvn_queue.cpp::frame_time_probe:380`, `WindowSetCrop:549`; `nvn_pipeline.cpp::graphics_pipeline:291` | The frame probe recognizes a Wonder return-site offset and accesses framework fields without a title check. An Astral collision is unknown. Window crop uses supplied values rather than enforcing the comment's resolution. Linked pipeline construction handles vertex/fragment stages; Astral geometry/tessellation usage, format compatibility and presentation remain unknown. | Gate the title-specific probe by verified title/module identity before enabling tuning. Observe actual crop, formats and first linked stages on Mac; separately check feature limits and presentation on the other targets. No inherited resolution comment alone proves a defect. |
| **Already adapted / bounded compatible boot prerequisites.** `games/wonder/game.cpp::kInfo:8`; `main.cpp::boot`, `kDtInit:50`, `tdata_range`, `nn_main`; `loader.cpp::load_modules`; `memory.cpp::memory_init` | The Astral adapter replaces title/data-root/resource metadata; the stack is NPDM-derived. This audit independently parsed NPDM and checked both modules' boot metadata: retained main/sdk fit the slots and required initialization/export shapes. 069's unchanged trace reaches TLS setup and `nnMain`. TLS allocation and all constructor semantics are not thereby proven. | Preserve current adapter/memory work. Test thread TLS initialization/isolation and destructor behavior when a concrete symptom appears; reserve rtld lifecycle equivalence for a separate unit. The importer intentionally omits rtld, not an accidentally missing third loaded module. |
| **Already adapted dispatch; lower-priority semantics unknown.** `ipc.cpp::Service::handle`, `ipc_request`; `hle_hid.cpp`; `hle_audio.cpp`; `hle_fs.cpp::MountRom/MountSaveData`; `svc_am.cpp::common_state_getter`; `svc_set.cpp::make` | Current strict IPC and landed framing/controller/audio/applet/APM/VI overlays differ from the pin. RomFS/save paths derive from the selected root. Default docked mode, language/region lists, controller layout and audio object/renderer layouts still need Astral-specific behavioral checks. Existing dispatch receipts do not prove payload semantics, audible output or saving. | Follow the next actual command with its original SDK caller/response layout, then exercise input/audio/save and reload after genuine rendering. Compare settings to authenticated control metadata; do not replace defaults solely because they originated with Wonder. |

The inspected recompiler CLI, `recomp/__main__.py::write_table`, emits module
metadata and relocatable base definitions rather than a title-ID override
(**generic reusable code**). Astral's selected SDK table agrees with original
MOD0 BSS. This does not validate instruction lifting, indirect-branch discovery
or all relocation/symbol semantics; those require separate targeted comparisons.

## Exact disjoint follow-up scopes

1. **NVN-FORMAT:** `runtime/patches/astral-nvn-format.patch`,
   `tests/test_nvn_format.py`, `docs/ASTRAL_NVN_FORMAT.md`. Overlay only upstream
   `runtime/src/nvn/nvn_texture_layout.cpp` unless a new bounded scope is approved.
   Establish the original metadata and meaningful layout/bounds tests before
   integration. This avoids 070's device-query/version changes. Parent owns
   application to the shared source and the cumulative Mac launch.
2. **SHADER-RUNTIME-PACKAGE:** `tools/prepare_astral_shader_package.py`,
   `tests/test_astral_shader_package.py`, `docs/ASTRAL_SHADER_PACKAGE.md`.
   Validate an explicit private package and report missing actual requests;
   reuse existing extraction/translation tools. Do not edit shared NVN files,
   `tools/prepare_runtime.py` or `tools/service_batch_startup.py` in parallel.

Shader control-tail/compute semantics, full enum equivalence, every object size,
callback ABI, packaged texture tiling, full shader/cache population, IPC command
versions, controller/audio behavior, save persistence and platform presentation
remain unexamined or incomplete. No exhaustive defect count is claimed.

Independent **Astra/medium review of the exact committed Sol/high head** remains
required before landing; no review is waived. This worker does not land, push or
launch nested reviewers. Mac gameplay remains unverified; Linux, Windows,
iPhone simulator and iPad simulator require separate acceptance. No new
26.5-tested / 26.0-target simulator or physical-device evidence was produced.
