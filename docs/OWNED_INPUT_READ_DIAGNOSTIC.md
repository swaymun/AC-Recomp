# INPUT-READ-016: input access remains blocked

The local synthetic file is readable. Path-only metadata queries succeed for the
three authorized sources, but a descriptor-based walk stalls opening
the owner's documents folder (the parent of `$ACS_DUMP_DIR`) as a directory. No source file was opened by this unit;
no NSP read syscall was reached and no key contents or xattr values were accessed.
The cause remains unknown. These observations do not establish encryption, TCC,
cloud hydration, mount failure, or a permission denial as the cause.

## Predecessor evidence and interpretation

Read-only predecessor: sibling `CONTROL-METADATA-015`, producer head
`8fa5d44039607ef612504ae2bc2bc156da4eab1f`, still under independent review.
Its retained evidence is `.local/game-private/control-metadata-015/` there.
`source/nximport_cli.cpp` places a completed temporary `ofstream` stage write
immediately before `open(argv[i], O_RDONLY | O_CLOEXEC)` and another immediately
after. `staged-probe-command.json` orders production keys, title keys, then NSP.
At 12:04:18.499737–12:04:28.632297 UTC the retained stage was
`opening_input_0`, exit -9. This localizes the old observation to the first key
path open interval (including scheduling/next marker), before `run_import`.
`nximport.cpp` calls `import_main` from `run_import`; key parsing at lines
1108–1114 occurs inside `import_main`, after CLI input opens. We did not rerun it.

The predecessor hash helper calls `hash_file`, opens the NSP and loops over
8 MiB reads to EOF; it prints a result only after hashing finishes. Its
12:05:44.234681–12:06:04.441725 UTC timeout (20.206962 seconds, exit -9)
contains no open/read progress. Reading and hashing 10,344,357,116 bytes within
20 seconds would require over 517 MB/s end-to-end. That timeout alone proves
neither a stalled open nor a read failure. Historical stat success also does
not prove bytes readable. The retained expected size is 10,344,357,116; expected
SHA-256 is `b2197c338f5c6e91b16b1a50cb5b5971d014240319944556a6740d64a410572f`.
Current full-file identity remains unverified. The canonical receipt also says
the original parent extraction was not preceded by hashing the NSP.

## Observed checks, 2026-10-18 UTC

Private receipts live in this worktree under `.local/input-read-016/`:

- `run-0524986v/receipt.json`: initial four individually supervised children,
  12:17:13.247372–12:17:37.517662 UTC, total 24.270396 seconds.
- `path-metadata.json`: distinct path-only lstat strategy followed by a
  directory-open localization, 12:18:10.851224–12:18:19.212826 UTC,
  total 8.361923 seconds. This was adaptive localization, not a read retry.
- `probe-live-v2.py`: original diagnostic source snapshot used for the second
  batch. The first batch used the same core inspect/supervisor before adding
  ordinal ancestor markers and the path-only metadata strategy. The final
  tracked version integrates those observations into its suite and tightens
  protocol validation; it was tested synthetically, not rerun against sources.

Exact interpreter/script/source argv, start/end UTC, exit code and timings are
in those receipts. Initial entry command:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/probe_owned_input.py --live
```

It exited 2. The adaptive driver called `supervise` once per authorized source
with `[sys.executable, absolute_tool, '--child', absolute_source,
'path-metadata', 'None']`, then once for the NSP path with mode `metadata`.
Each child had an 8-second deadline; the driver exited 0 after retaining the
results, which is not a source-access success. Do not invoke `--child` directly:
it needs the supervisor's separate protocol descriptor.

| Operation | Elapsed seconds | Exit | Observation |
|---|---:|---:|---|
| Local 4604-byte synthetic file | 0.091911 | 0 | Open 0.0000265 s; read 4096 bytes in 0.000006708 s; fixed PFS0 classification |
| Initial production-key descriptor metadata walk | 8.065241 | -9 | Metadata phase incomplete |
| Initial title-key descriptor metadata walk | 8.055182 | -9 | Metadata phase incomplete |
| Initial NSP descriptor metadata walk | 8.056862 | -9 | Metadata phase incomplete; no open/read of final file |
| Production-key path-only lstat | 0.098145 | 0 | Regular, 14612 bytes, mode 0664, flags 0, 32 allocated blocks |
| Title-key path-only lstat | 0.102314 | 0 | Regular, 1292 bytes, mode 0664, flags 0, 8 allocated blocks |
| NSP path-only lstat | 0.093245 | 0 | Regular, 10344357116 bytes, mode 0644, flags 0, 20203824 allocated blocks |
| Directory-open localization | 8.066568 | -9 | Last ordinal 2: open Documents; no next ordinal |

Sources are under the authorized `Documents/My-Personal-Game-Dumps` directory.
All three lstat observations have uid 501, gid 20, device 16777230. Every path
component was checked without a symlink observation. Mode bits, allocation and
flags are metadata hints, not proof of read availability or authorization by
other OS mechanisms. No xattrs or ACL values were collected. The synthetic file
is on the same reported device; its success rules out universal local read
failure but does not explain source-directory behavior.

Sum of active supervised diagnostics: **32.632319 seconds**, each below 10 seconds
including owned cleanup. The first-to-last wall-clock span is **65.965454 seconds**,
including the gap for inspection/instrumentation; thus if the 60-second limit is
interpreted as contiguous wall time rather than cumulative live operations, that
span exceeded it by 5.965454 seconds. No more live operations were performed.
All eight direct children were reaped; timed-out groups received SIGKILL. The
supervisor cannot claim to reap grandchildren or kill descendants that escape
its process group. Actual probe children do not spawn descendants. No source
bytes, raw signatures, native diagnostics or credential values were retained.

## Tool contract and reproducibility

Standard library, POSIX only. The public CLI fixes the three authorized source
paths; no arbitrary live-input argument exists. The final suite performs a local
synthetic read, three path-only metadata children, then one NSP read attempt.
At most five children, each 8 seconds plus at most 0.5 seconds leader cleanup;
no retry or full-file hash. It stops if leader reaping is uncertain. Timeout is
observable separately from metadata/open/read/size errors through fixed stage
markers, numeric errno and return code. Kernel scheduling or an uninterruptible
child can prevent an absolute real-time guarantee; unreaped state is reported.

Reading uses directory descriptors pinned one component at a time, O_NOFOLLOW,
regular-file and single-link checks, expected size, O_NONBLOCK, and post-open
identity/size/mtime comparison. Unsafe paths, parent/final symlinks, FIFOs,
directories and hardlinks fail closed. The path-only lstat route never authorizes
a read and is an observation across instants, not a race-free identity proof.
Keys receive only metadata operations. The NSP gets at most one `os.read(4096)`;
only count, timing and fixed `PFS0`/`other` classification survive. Child stdout
and stderr go to DEVNULL; fixed typed events use a bounded separate pipe.
No directory enumeration, hydration commands, settings/permission changes,
provider actions or game launch occurs. Output is private ignored local storage.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_owned_input_probe.py' -v
```

Synthetic tests cover real child invocation, one-read bounds, discarded stdout
and stderr, secret-marker nonretention, metadata without final opens, unsafe
files, size rejection, open/read errors, short reads, fixed protocol validation,
timeouts and owned child-group cleanup. They never touch real authorized inputs.

## Smallest follow-up and acceptance limits

The precise blocker is descriptor opening of the Documents ancestor under this
scoped child, while path lstat succeeds. The smallest next investigation is an
independently scoped review of that directory-open boundary and the process's
existing access context, using these retained receipts; do not retry hashes or
run the importer to diagnose it. Any proposed OS access-policy change requires
separate scope and evidence. No owner choice or speculative remediation is
required from this unit. Key readability remains deliberately untested.

This is diagnostic tooling, not recovered input access or control-metadata
production. Independent Sol/high exact-head review is required for this Astra
producer before `scripts/land`; no nested reviewer or waiver was used.
macOS/Linux remain partial; Windows and separate iPhone/iPad simulators remain
blocked. Report 26.5 tested / 26.0 minimum; physical acceptance unverified,
gameplay/semantic coverage unknown, cross-ISA byte match N/A.
