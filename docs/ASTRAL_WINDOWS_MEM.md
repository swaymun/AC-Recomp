# Windows memory growth

## WIN-MEM-036 integration and attribution follow-up

Before this integration, the Windows memory overlay was **never enabled** in the shipping series. `git log 778bbb4 -S
'astral-windows-mem.patch' -- runtime/patches/series.windows` has no entries; commits
`8195bf7` and `dde9cac` added the patch/tests/docs without changing that series. The old integration instructions
explicitly deferred activation to the parent. The fresh current Windows stack also rejected the old patch in
`nvn_frames.cpp`, `nvn_written.cpp` and `nvn_upload.cpp`; no other overlay had folded in its retirement repairs.

`series.windows` now includes the rebased overlay immediately after `astral-windows-desktop.patch`.
The performance, resident, writeback and stutter overlays are rebased around it; the replay overlay is unchanged.
The three behavioral repairs remain **opt-in until the native route gates pass**:

| Setting | Absent / `0` | Exact `1` |
|---|---|---|
| `NX_WINDOWS_IMAGE_RETIRE_FIX` | Previous ownership path | Release duplicate retired references as visited; route expired snapshot images through the existing retirement serial |
| `NX_WINDOWS_STREAM_UPLOADS` | Previous scene-batched staging | Complete eligible fresh ASTC uploads separately and free their staging after the fence |
| `NX_WINDOWS_IMAGE_CACHE` | Keep all live guest textures' decoded images | Trim cold, reconstructible ASTC GPU backing toward a 1 GiB soft budget |
| `NX_MEM_TRACE` | No hooks or inventory sampling | Allocation/lifetime counters, raw guard peaks and commit inventories |

No memory-limit policy changes are included. `NX_MEM_LIMIT_GB` remains **8 GiB by default**, checked every
250 ms. Inventory sampling runs after the unchanged guard-stop check. The over-limit path records its raw peak before the existing termination. Failed diagnostic queries/allocations cannot
waive the guard. These repairs do not promote WIN-GATE-034's eight performance switches.
Fresh-upload API failures also discard undefined error-output handles, preventing a failed allocation from
being freed or a failed command pool from being reused. Successful submissions still require fence completion
before staging can be released; submit/fence failures retain the existing fatal path.

### Allocation accounting

With `NX_MEM_TRACE=1`, the existing guard reports `memtrace:` records every 20 ticks (about five seconds), plus new private-byte highs in 64 MiB steps. `process` records preserve the exact peak from its unchanged 250 ms checks; guard exits also log the exact raw bytes.
The Vulkan hooks are installed once after device creation, before upload-ring allocation and shader prewarming.
They preserve API results and output handles, including successful individual pipelines in a failed batch.
`dropped` or `unknown_frees` records must be investigated before treating a run as fully attributed.

| Record / pool | Measurement and ownership |
|---|---|
| `images` | Explicit `VkDeviceMemory` allocations for guest texture images, retained until the actual Vulkan free |
| `staging`, `fresh_staging` | Dedicated upload allocations, including failed bind/map cleanup; GPU retirement and fence frees close their lifetimes |
| `upload_ring`, `resident` | Explicit fixed Vulkan buffer allocations; resident classification and CPU snapshot observers are installed only for tracing |
| `other_vulkan` | All remaining explicit Vulkan memory allocations, including readback/presentation helpers |
| `shader_code` | Live input SPIR-V byte sizes of shader modules; opaque driver storage is not included |
| `graphics_pipelines`, `compute_pipelines` | Live object counts, **not byte estimates** |
| `decoded_prepared`, `decoded_store` | Prepared decoded payload and queued **plus in-flight** persistence payload; existing 192 / 128 MiB budgets remain unchanged |
| `texture_queues` | CPU texel payload/capacity and queue/texture counts in the live objects map; sampled on GPU retirement without waiting for the game-thread lock (`busy=1` skips a contended sample) |
| `snapshots name=compute/resident` | Payload bytes held by shared CPU snapshots, including aliases in resident entries and in-flight writeback slots; last-owner frees balance allocations |
| `host_stack_reserve` | Requested fiber reservation bytes and counts; commitment is reported separately by the VA inventory |
| `ownership` | Pending retirement references/staging buffers/reusable images, and final texture owners that disappear with still-live Vulkan memory |

The thread-safe ledger distinguishes memory, module, pipeline and host-stack handle domains and handle reuse.
It does not hold its mutex across Vulkan calls or logging. Tracing observes orphaned images without freeing them,
so the old path can still reproduce the leak. Borrowed readback/swapchain wrappers do not count as orphaned textures.
`live`, `peak`, `total`, `allocations` and `frees` refer to explicit payload/reservation sizes or the stated object unit.
They must not be added to Windows process commit: WDDM can account device-local allocations differently, and driver
pipeline storage, allocator capacity/fragmentation and other host heaps remain an explicitly unattributed residual.

Every trace sample also performs a read-only `VirtualQueryEx` inventory: committed private/mapped/image virtual
ranges, the guest heap/alias/stack/kernel ranges, and whole allocation groups containing `PAGE_GUARD`.
Guarded groups are a host-stack diagnostic rather than a guarantee that every stack retains a guard page.
Reservations and commitments are separate. At each new private-byte high at least 64 MiB above the preceding
inventory high, `va_peak` records preserve allocation-base groups with at least 16 MiB committed or a guard page.
The aggregate includes smaller groups. `query_failed=1` identifies an incomplete walk; VA commitment is not
interchangeable with `PrivateUsage` or resident working set.

### WIN-MEM-036B: L4 attribution and image-cache experiment

The continuation uses the on-demand Windows Server 2025 host with a four-core/eight-thread Xeon at 2.20 GHz,
NVIDIA L4 and driver 596.86. Its frame rates are not comparable with the earlier G4. Private evidence remains
in `.local/units/WIN-MEM-036/` and `C:\acr\units\WIN-MEM-036\`.

Fresh native default and eight-switch compiled-candidate baselines both reproduce the normal **unset 8 GiB guard**:

| L4 run | Guard observation | Last explicit image bytes | Other attribution |
|---|---|---:|---|
| True default, both original repairs off | Exit 3, 8.00 GiB rounded | 3,457,234,432 | Scene-batched staging peak 1,111,533,824 bytes |
| Eight compiled defaults, all eight variables absent | Exit 3, 8.03 GiB rounded | 3,154,375,680 | Resident 256 MiB; prepared decoding 192 MiB; store drained |
| Default, streamed uploads alone | Exit 3, **8,593,346,560 bytes** | 4,005,539,840 | Ordinary staging peak about 16 MiB; fresh staging peak about 171 MiB |

The original five-second inventory and two-second external watcher can miss a rapid guard peak. The last
unfixed-default inventory records 8,229,142,528 private bytes; its watcher only catches 7,972,982,784. These are
not passing peaks. The follow-up diagnostic records exact guard peaks and inventories rapid high-water rises. Passing supervised routes additionally retain the OS lifetime commit peak (`PeakPagefileUsage`) in the stop receipt and external samples; [Microsoft documents this field](https://learn.microsoft.com/en-us/windows/desktop/api/psapi/ns-psapi-process_memory_counters_ex) separately from current `PrivateUsage`.

The guest heap stays at 3,376,414,720 committed bytes. The upload ring stays at 268,435,456 bytes; guarded host
stacks commit about 1.5 MiB. Compute snapshots regularly return to zero (about 32 MiB peak), the CPU texel queue
is about 4 MiB, and the candidate's decoding/store budgets remain bounded. No dropped records, unknown frees or
orphaned-image events are observed before these exits. Thus the known alias-retirement defects do not explain
these pre-exit samples. The largest transition rise is **live decoded images**, plus the staging overlap already
reduced by streamed uploads. Live NVN objects can retain their expanded ASTC backing beyond their last sample.

`NX_WINDOWS_IMAGE_CACHE=1` adds an independently selectable Windows-only experiment. At new-image creation it
samples current image owners at most every 250 ms and trims toward a **1 GiB soft budget**. It considers only
uploaded, decoded ASTC images cold for at least 250 ms, with valid guest backing for every alias. Rendered
images, texel-write history, pending texel writes, host snapshot keys, unknown backing and external owners
(including deferred incarnations/retirement entries) stay protected. A touch since this replay's recording began
also protects an image, even during a long recording. Only after the existing graphics queue is idle are selected
images/views destroyed and all eligible texture aliases reset; later sampling reconstructs them from guest bytes.
The current command buffer is preserved. Active/protected images may exceed the soft budget; the hard process
guard remains 8 GiB. This trades cold-image reconstruction and occasional queue waits for memory headroom.

`memtrace: image_cache` reports live/cold/protected bytes, releases and cumulative counts. The production fixture
checks physical/virtual backing, alias release, current-recording/hot images, GPU/texel history, external owners,
invalid mappings, disabled mode and failure-before-free on an unsuccessful queue wait. Both native variants link.
Mac/Linux shared-source preprocessing still matches under all 14 comparisons. The continuation also fixes the
texture sampler's accidental internal linkage, which the first native link exposed.

An initial cache-enabled lab prefix released 875,192,320 bytes across 91 cold images and peaked at 5.579 GiB,
without orphan/unknown/drop records. Its supervisor stopped the game after Windows denied a progress-file rename;
it is **not** a stability gate. Progress writes now retry and cannot stop play. A separate earlier prefix ended
when Windows completed a planned reboot. Both interrupted prefixes are retained separately and excluded from gates.
The full-route measurements below distinguish guard survival from the remaining headroom and scene-coverage gates.

#### Frozen-head route measurements

The 250 ms cache experiment was built separately for the true performance-default runtime and the eight-switch
compiled candidate. All eight performance environment variables were absent in both processes; all three memory
repair variables were explicitly `1`. `NX_MEM_LIMIT_GB` was absent, preserving the normal 8 GiB guard. This does
**not** make the repairs public defaults. Source/archive/executable receipts are retained in `036B-build-gates/`.

| L4 run | OS lifetime private-commit peak | First-minute mean | Last-minute mean | Growth |
|---|---:|---:|---:|---:|
| Default 1 | 7,963,635,712 bytes (7.417 GiB) | 5.709 GiB | 6.034 GiB | +333.4 MiB |
| Default 2 | 7,958,409,216 bytes (7.412 GiB) | 5.756 GiB | 6.006 GiB | +256.2 MiB |
| Default 3 | 7,957,467,136 bytes (7.411 GiB) | 5.723 GiB | 5.945 GiB | +227.0 MiB |
| Candidate 1 | 8,510,275,584 bytes (7.926 GiB) | 6.086 GiB | 6.444 GiB | +366.1 MiB |
| Candidate 2 | 8,514,412,544 bytes (7.930 GiB) | 6.059 GiB | 6.535 GiB | +487.7 MiB |
| Candidate 3 | 8,513,609,728 bytes (7.929 GiB) | 6.074 GiB | 6.373 GiB | +306.2 MiB |

Minute means use the same 375–975 s, 600-second observation window in each run, with 299 external samples.
All six survived that window and ended through bounded supervisor termination, with no guard stop. Candidate 2
leaves only **72.02 MiB** below the guard. That fails the requested comfortable headroom; promotion is withheld.
The positive differences span changing scenes rather than equal-scene plateaus, so they do not prove a residual
per-minute leak. Explicit image peaks remain about 2.83–2.86 GiB despite the 1 GiB soft target. Current-recording,
hot and non-reconstructible images remain protected; opaque driver/host allocations remain an unattributed residual.
The soft policy also permits transient cold backing: near Candidate 2's high sample, the next trim observes
3,040,265,216 live image bytes, of which 1,145,718,784 are cold and released. The trim nearest Default 1's high sample
instead has 2,968,724,992 protected bytes (2.765 GiB). A stricter pressure/working-set policy and remaining host/driver attribution are still needed;
the experiment does not establish a hard 1 GiB image bound. Candidate 2 releases 79,326,612,992 cumulative bytes
across 13,093 images, so reconstruction/queue-wait cost must also be evaluated before promotion.

The first pair's dense screenshot requests exposed a harness problem: the native request file is polled every
60 presents, so requests accumulated and extended actual supervision to 1,338 / 1,590 s. Frame metadata retains
actual capture times. Default 1 shows CLEAR at 760.3 s, the following autosave tutorial at 1,061.1 s, and the
on-foot scene later. The controller sequence ends at 1,060 s, so these observations do **not** prove the requested
following-combat coverage. Subsequent runs skip missed capture deadlines and request frames every 30 s.
No stale frame is substituted for a failed capture. The third pair extends the supervisor/controller limit to
1,200 s. Candidate 3 adds 30 s of owned-window continuous fire at 1,025.6 s; Default 3 adds it at 621.8 and 817.6 s.
Thus these routes are not identical input replays or scene-aligned growth comparisons. Default 3 captures the
following autosave guide at 1,158.0 s and later on-foot tutorial controls. Its extra Plus input at 1,177.5 s occurs
after that guide; its effect is unverified and is not evidence of a confirmed cinematic skip. Following combat
is still unproven. All six have zero observed orphan/drop/unknown-free records and complete VA inventories.
Their mean background CPU is 3.56–5.18% of total machine capacity (individual samples reach 22.09%); every sampled
game inventory contains just the owned game. Full-scene visual and validation acceptance remain separate.

#### Validation and remaining acceptance

Matched 435 s default prefixes use the same frozen executable, normal unset 8 GiB guard and active Khronos
validation layer, with the three memory switches absent before and `1` after. Both reach the opening, lab,
character scene and chase. Their full observed message multisets match exactly: **45 errors and 9 warnings each**,
with no new error/warning messages or VUIDs. These are inherited DrawParameters/interlock capability,
clip/cull-distance and dynamic-unused-attachment defects; duplicate suppression limits repeated counts.
This comparison does not establish full CLEAR/following-combat validation. Raw messages, outcomes and scene
captures are retained in `validation-default-before-036b/`, `validation-default-after-036b/` and
`036B-validation-comparison.json` under the private unit directory.

The first saved-candidate before probe stays at the title because its early menu inputs miss the prompt. The
after probe is advanced with owned-window ZL+ZR at 125.7 s and A at 154.8 s and reaches the crash cinematic.
Both record 45 errors; only the latter records the nine unused-attachment warnings already present in both
default prefixes. That unequal scene coverage cannot establish a matched later-scene validation pass.
A separate corrected before replay (`validation-saved-candidate-before-v2-036b`) adds the after probe's menu
inputs at 125.684 / 154.819 s. It reaches the autosave guide and on-foot early interaction. Its observed
**45 errors / 9 warnings match the after probe exactly**, with no new messages or VUIDs. These saved probes
cover different moments and are not full-route validation. The corrected before replay lasts 217.27 s,
peaks at 8,401,760,256 private-commit bytes (7.825 GiB), and has no guard stop. The two planned additional
saved-default probes are explicitly skipped at the cleanup cutoff. No short validation probe is counted
among the six 600-second memory windows.

The six memory windows pass guard survival. Comfortable headroom, six runs covering following combat, and
full-route validation remain **unmet**. The three repairs stay opt-in, and WIN-GATE-034's performance defaults
are unchanged. Parent independent review is required; this worker performs no nested review.

### Current verification and native gate

Private work and resume instructions are in `.local/units/WIN-MEM-036/` (main checkout), with VM work restricted
to `C:\acr\units\WIN-MEM-036\`. The actual public default and WIN-GATE-034 eight-switch compiled candidate are
prepared separately; candidate promotions stay private. Their native executable/source/archive receipts,
normal-guard routes, per-pool time series, peak inventory, growth and visual/validation results must be recorded
here before the memory repairs become default-on.

The portable fixtures compile the production retirement, staging, accounting and Vulkan-dispatch helpers.
They reproduce the alias leak and prove 20,004 exact image frees, ownership/serial safety, snapshot alias and
allocation-failure accounting, concurrent handle reuse, failed Vulkan allocation outputs, partially successful
pipeline batches, and reserved/committed/guest/guarded-stack inventory semantics. Fresh complete-series application
and shared translation-unit preprocessing are checked. macOS/Linux series are unchanged; preprocessing compares
all seven changed shared translation units under macOS and Linux guards. Only whitespace and the generated
registrar identifiers' `__LINE__` suffixes are normalized; constructor arguments and registration order stay exact.
The Linux guard check preloads the Mac host SDK before selecting runtime Linux guards; it is not a Linux native run.

**Fresh L4 baselines and allocation accounting are available above; comfortable headroom, three complete chase/combat
runs per build, full-route validation and default-on promotion remain pending.** The initial WIN-MEM-036
closeout was blocked by SSH timeouts; the continuation's native observations above supersede that availability status.
WIN-GATE-034's historical sampled peaks are 8,591,290,368 bytes (**8.001 GiB**) for the 16 GiB diagnostic reference
and 8,920,133,632 bytes (**8.308 GiB**) for the candidate. The brief's 8.59 / 8.92 values are decimal GB, not GiB.
The first-to-last-minute reference growth is 728,491,349.3 bytes (694.743 MiB). These are historical measurements;
the L4 continuation above supplies fresh counters and distinguishes the remaining acceptance failures.

## Historical WIN-MEM-018 prototype evidence

These are retained prototype measurements, not new WIN-MEM-036 native results. In particular, the old
fresh-upload prototype defaulted on; the current integration keeps both repairs opt-in pending the route gates.

The original prototype bounded Windows scene-load staging and fixed two shared GPU-image ownership leaks. Real L4 probes show
lower private-byte peaks and balanced compute snapshots. The original complete chase -> CLEAR -> next-scene
`bad_alloc` route is a separate acceptance gate; do not infer its completion from the tests or a stationary scene.

### Cause and implementation

`upload_texture -> staging_alloc` retains every large decoded texture's host-visible staging buffer until the
entire scene-load submit retires. The measured load held 1,318,578,336 bytes in this host-visible allocation category,
including the small frame-readback buffer, alongside the device-local images, guest heap and 256 MiB upload ring.
A loading peak can therefore stop the guard or exhaust commit while the later scene's working set looks small.

For Windows strict builds, fresh ASTC uploads of at least 1 MiB now complete separately. Eligibility requires no
previous upload, undefined image layout, no GPU writes and no texel-write history. A private command buffer copies
the same decoded bytes and mip/layer regions on the existing graphics queue. Its fence is waited before freeing
the staging allocation. The main replay command buffer and bound state remain intact. Other uploads keep their
existing path. This bounds this staging component by the largest individual texture instead of a whole scene's
upload batch. `NX_WINDOWS_STREAM_UPLOADS=0` restores the previous path for bisecting. The default guard stays 8 GiB.

There are extra submissions and waits at first texture use, trading loading work for a lower memory peak.
Pre-submit allocation/recording failures restore the tracked image layout and fall back. Submit failure or a fence
timeout stops the process without freeing memory that the GPU might still access. The synchronization follows the
[Khronos queue-submit/fence contract](https://docs.vulkan.org/refpages/latest/refpages/source/vkQueueSubmit.html).

The WIN-MEM-018 prototype repaired two additional image-lifetime defects. Its shared prototype changes were not activated in any series; the current follow-up limits these repairs to strict Windows builds:

* `free_retired_images` skipped every image with `use_count() > 1`. Duplicate entries in the same retired batch
  each saw another retired reference, so every entry was skipped. Vector destruction then dropped the final owner
  without destroying Vulkan handles (`GpuImage` has no Vulkan destructor). The helper releases each retired
  reference immediately; the final one destroys the handles once. A genuinely live owner still protects its image.
* Snapshot expiry used `snap->image.reset()`, which could lose the final owner without Vulkan destruction. It now
  moves the reference through `retire_image` with the existing `g_submitted + 1` safety serial. Destruction stays
  on the GPU thread after retirement.

`NX_MEM_TRACE=1` reports fresh-upload payload totals/largest staging allocation, retired references/image frees,
and live/peak/total compute snapshot bytes with allocation/free counts. Snapshot aliases count once and in-flight
write-backs keep their payload live. Snapshot `bad_alloc` logs requested bytes and region/overlap counts, then
rethrows; it does not silently retry. Without tracing, snapshots retain their original `make_shared<vector>` path.

### Windows evidence

All evidence is private and retained beneath `.local/units/WIN-MEM-018/` in the main checkout, with corresponding
files under `C:\acr\units\WIN-MEM-018\`. Game inputs, generated code, saves and frames remain ignored. No owner-build
writes, keys, new cloud resources or public-repository changes were used.

The controlled A/B ran on Windows Server 2025, NVIDIA L4, GRID 596.86. It uses **one binary**, identical copied save
and input script, and only changes `NX_WINDOWS_STREAM_UPLOADS=0|1`. Private input instrumentation clears the shared
VM's physical/virtual pad state for this process. Both runs reached the same on-foot autosave tutorial, confirmed
from frame dumps. Both ended at their 180 s supervision limit, not a game crash, allocation exception or guard stop.
Binary SHA-256: `19537c4451fba1d81b06ff4cabb2e724e42e5967a95483413a4a96a065fee721`.

| Controlled saved-scene measurement | Previous path | Fresh uploads |
|---|---:|---:|
| Duration | 181.016 s | 180.906 s |
| Guard's 250 ms private-byte peak | 6.92 GiB | 6.77 GiB |
| Sampled private-byte peak | 7,410,163,712 | 7,254,155,264 |
| Final private bytes | 7,215,095,808 | 7,055,499,264 |
| Uncached host-visible Vulkan allocation peak | 1,318,578,336 | 23,935,584 |
| Cached allocation peak, including the ring | 268,435,456 | 447,392,448 |
| Largest completed fresh-upload staging buffer | batch retained | 178,956,992 |
| Compute snapshot allocation/free counts at last log | 16,863 / 16,863 | 15,272 / 15,272 |
| Live snapshot payload at last log | 0 | 0 |

The uncached category includes a 5,760,000-byte frame-readback buffer as well as staging. The ring is a fixed
268,435,456 bytes. The new dedicated staging peak is 178,956,992 bytes; at least 352 uploads / 2,494,216,016 payload
bytes completed. App-owned staging no longer accumulates across those uploads. Drivers may retain freed allocation
capacity, and live textures still consume memory; this is not a promise of a constant total footprint in every scene.

System-commit peaks were 20,284,633,088 and 20,635,860,992 bytes against a 35,429,654,528-byte limit. Other units were
active on the VM, so those system-wide differences are context, not a causal A/B metric. Evidence:
`isolated-before/`, `isolated-after/`, `isolated-ab-summary.json`, and `isolated-*-current.png`.

An earlier, less controlled saved-scene pair reached 7.63 GiB before versus 6.77 GiB after; it could receive the shared
pad's inputs. It is corroborating evidence rather than the headline comparison. The new path rendered textures,
closed the save tutorial and accepted forward movement; private bytes settled near 6.56–6.57 GiB. Evidence:
`upload-before/`, `upload-after/`, `upload-*-current.png`. An ownership-fix-only probe still tripped a 7 GiB diagnostic
guard during loading; ownership repair alone was insufficient, which is why staging was investigated separately.

The native Vulkan ownership regression uses no game data. It creates 64 2048x2048 RGBA8 images, 16 MiB each, and
retires duplicate references using either the previous loop or the shipped helper. On the actual L4:

| Ownership diagnostic | Previous loop | Fixed helper |
|---|---:|---:|
| Initial private bytes | 38,699,008 | 38,703,104 |
| Private bytes after 64 images | 1,114,902,528 | 290,856,960 |
| Explicit Vulkan bytes freed | 0 | 1,073,741,824 |
| Images whose final owner vanished with live handles | 64 | 0 |

The fixed process plateaued at about 277.4 MiB from iterations 16–64 with all explicit image allocations freed.
Both diagnostics exited normally. Evidence: `vk_retire_repro.cpp`, `nvn_retire.h`, `build-vk-repro.log`,
`vk-retire-before.jsonl`, `vk-retire-after.jsonl`. This proves the ownership leak on a real GPU, not the full game route.

### Snapshot and fiber checks

`written_bind`'s CPU snapshots return to zero after write-back. They are not a retained per-frame queue in the
measured probes. The cached ring remains fixed. Win32 `CreateFiberEx` reserves 8 MiB with 64 KiB initial commit;
`Context::~Context` calls `DeleteFiber`, and finalization/thread retirement erase contexts. A read-only
`VirtualQueryEx` inventory during the longer startup/chase probe found 39 guarded host-stack groups committing
1,101,824 bytes; three 8 MiB groups committed 233,472 bytes. Guest committed ranges totaled 3,625,365,504 bytes.
Evidence: `chase-stack-query.json`. These stack commitments do not explain the GiB-scale loading peak.

The same shipped snapshot counters were compiled and run on the physical Mac for 60.29 s through `mac-game-lock`,
headless and muted. Last counters: `live=0 peak=10041084 total=12491334344 allocations=5412 frees=5412 regions=0`.
The guard logged 2.15 GiB with a 2.16 GiB peak. Evidence: `mac-production-counters/guest.log` and `receipt.json`.
This checks counter/lifetime behavior on the Mac; it does not test audio-device timing, windowed presentation or
File 01. Windows private commit and Mac physical footprint are different metrics and are not directly comparable.

### Verification, integration and remaining gates

The original four-test suite compiled the prototype bodies and applied that older overlay after all three full
platform series when the private pinned reference was available. The expanded current suite is described above. They reproduce the old alias leak and check 20,004 exact image frees,
live owners, retirement batches and snapshot expiry serials. Snapshot tests inject failures at the vector object,
backing bytes and shared control block. The Vulkan-call fixture checks payload copies, private commands/barriers,
fence-before-free, 100 uploads with one staging allocation live, disabled mode, pre-submit fallback and fatal
submit/timeout paths. Unit tests use no game, GPU, cloud credentials or VM.

The original WIN-MEM-018 worker left series integration to the parent. History confirms that
`astral-windows-mem.patch` was never listed in `series.windows`, rather than removed or folded into another overlay.
WIN-MEM-036 now composes it after `astral-windows-desktop.patch`, before the performance overlays, as described above.
The original proposed macOS/Linux additions were not made. Those series remain unchanged.

Independent review belongs to the parent orchestrator because both workers' contracts forbid nested reviews.
The historical probes below did not reach CLEAR; they are not full-route acceptance of this integration.

The 903.58 s startup/chase probe included character setup and about four minutes of scripted motorcycle combat.
Its peak sampled private bytes were 6,951,997,440 (guard peak 6.47 GiB); final private bytes were 6,918,942,720.
The last snapshot counters were `live=0 peak=33224172 total=299170303308 allocations=102722 frees=102722 regions=0`.
It ended at the supervision limit with no `bad_alloc`, fatal, GPU timeout or memory-guard stop. CLEAR was not
observed, so this is prefix coverage, not full route acceptance. Evidence: `chase-final/`,
`chase-final-summary.json`, `chase-final-current.png`.

Native probes reused isolated copies of the validation runtime objects and generated libraries, rebuilt the scoped
NVN changes, and added private allocation/input instrumentation. Rebase integration additionally tests patch
application against the latest complete series (including the subsequently landed render/desktop overlays).
A clean final player build against that full landing prefix remains for parent integration.

A second 903.59 s startup/chase probe also included profile setup and about five minutes of scripted
combat. Its peak/final sampled private bytes were 6,955,184,128 / 6,923,030,528; the guard peak was
6.48 GiB. Last counters: `live=0 peak=33224076 total=264502173480 allocations=91080 frees=91080 regions=0`. It stopped at the supervision
limit with no allocation exception, fatal, GPU timeout or guard stop. CLEAR was again not observed. No full-route
acceptance is claimed. Evidence: `chase-load/`, `chase-load-summary.json`, `chase-load-current.png`. Both game probes
and their input drivers were reaped; the final process inventory contained no WIN-MEM-018 game or runner.
