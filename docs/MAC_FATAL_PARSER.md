# MAC-FATAL-PARSER-056: isolated physical-line parsing

This unit changes only fatal extraction, its offline regressions and this
document. It preserves main's production overlay sequence, dependency and
preparation provenance, command interface and runtime worker. It adds no native
build, game start, runtime overlay or integration claim. MAC040 and MAC048 remain
`needs_split` with two failures each. Inspected MAC048 parser/test source was
selectively reused; its native receipts and cumulative changes are not accepted
results. MAC057 owns fresh runtime integration after MAC056 and HID051 land
independently. Independent Astra/medium review of this exact committed head is
required before landing; this producer neither commissions nested workers nor
waives review.

## Source-derived grammar

Wonder is pinned by `dependencies.lock` at
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. Inspection of that exact revision's
`runtime/src/loader.cpp` establishes `fatal`'s `FATAL: ` prefix and `log`'s LF
termination, also used by `platform_mac.cpp` on stderr. Its `runtime/src/ipc.h`
declares `IpcCtx::cmd` as `uint32_t`. Main's original
`runtime/patches/astral-bootstrap.patch` adds strict calls to the pinned
`runtime/src/ipc.cpp` with these formats:

```text
FATAL: strict IPC missing service: <service>
FATAL: strict IPC missing command: service=<service> command=<uint32>
```

The extraction allowlist is an ASCII letter followed by at most 80 ASCII
letters, digits, underscores or colons. Commands are canonical unsigned decimal
in 0..4294967295, matching `%u`. Unrecognized identifiers remain unknown, rather
than exporting arbitrary guest text. The entire physical line must match;
prefixes, suffixes, invalid bytes and control characters cannot establish a
fatal boundary. Only LF separates physical lines: CR, Unicode separators and
other `splitlines()` separators are not accepted delimiters. Missing services
carry no invented command. Caller-supplied log order, then physical line order,
selects the first valid fatal across both grammars.

## Bounded completeness and privacy

Each log supplies at most LIMIT bytes (16 MiB) plus one byte used only as an EOF
probe. If the probe sees more data, discard everything after the last LF within
the cap. With no LF the entire buffer is discarded. A newline-complete line
within the cap survives an unread later line. An unterminated tail is eligible
only when the probe observes true EOF, including EOF exactly at LIMIT. A newline
just beyond LIMIT does not complete an eligible line. Fatal data beyond the cap
is unverified; no claim of exhaustive log inspection is made. This assumes a
finished log, as supplied by the supervisor after process completion; it is not
a concurrent live-log reader.

Memory and parsing work are O(LIMIT) per log, independent of actual file size;
there is no unbounded read or scan of the suffix. Existing dispatch observations
remain observations rather than handler correctness. Only allowlisted fields,
fixed labels and booleans leave the private log. Raw guest text is not included
in errors or results. Gameplay remains false, visual frames unverified,
unmeasured semantic coverage unknown and cross-ISA byte match N/A.

## Verification

The required unittest suite retains temporary-repository provenance checks and
real synthetic subprocess supervision tests. Parser regressions cover both
grammars at the production cap and a small cap: a valid-looking prefix ending
exactly at LIMIT followed by a malformed private suffix must not be accepted.
They distinguish true EOF, newline inside/outside the cap, complete earlier
boundaries and caller log ordering; reject malformed fields/control separators;
verify privacy, missing logs and unread boundaries; and instrument stream reads
to reject unbounded access and require exactly `[LIMIT, 1]`.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_service_batch_startup.py -v
git diff --check main HEAD
```

No native rebuild is required for this parser unit. Ignored local receipts and
hashes are retained for review without adding raw runtime logs to Git.
