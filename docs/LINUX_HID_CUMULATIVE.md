# Linux cumulative HID integration

`tools/linux_runtime_startup.py` now selects the closed
`linux-hid-cumulative-v1` profile. Its reviewed-source ancestor is
`1a394ccc296f091115f273640560cd566f4af256`; every consumed helper, overlay and
lock file must match that commit's exact bytes. Clean tracked state and ancestry
remain mandatory. There is no caller-selected revision or overlay list.

The tested order is:

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

SQSHL and control-import preparation code is included for source identity;
accepted generated code and metadata are reused, never regenerated here.
Each overlay has a hash, size, application state and complete resulting source
fingerprint. The prepared identity binds the exact profile, Wonder pin, ordered
list and hashes. Omitted, duplicate, reordered, stale and tampered identities
fail before compilation. Prepared source is checked before and after execution.
Strict IPC errors remain errors; no runtime successor is implemented here.

## Reviewed source supersession

LINUX043 reviewed head `d50a4799e68c92180af6414be78bb699355b8693` passed Astra
run `0fcd49868bcb4c2b8effafb91f0a4dc0` and landed at
`7e4e44c0c62846d2cb80c9c64b32b89164c8983e`. It established six-overlay preparation,
not native execution. Its helper SHA-256 `0119b0b8...` is superseded by landed
IOS041, independently passed by Astra run `f4bb4b2595c346408f601b34b86217fe` at
`d8b1c49fc79127d93bdeb93e129eb9e0d4c7570f`. Current helper bytes exactly match
that full reviewed head, including its OpenStep parser correction; SHA-256 is
`97b166f6c0ed792b96966a0d24ec7a6222c89af6296eac18ae511bd5376e8895`.
The landed IOS041 sequence ends at `314678ae893c27ce3d6cfb0cae0ec18e15950a3c`.
This audit neither reverts the helper nor imports simulator acceptance into Linux.

IPC039 `0e9ee64ae97054e2870055bd1ca76ba97b2a3b8b`, AM044
`df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca` and HID045
`0ee4224829d3d23c232b3906a5c0f77ffbf92c64` are landed ancestors. Their independent
Astra/medium reviews are `fa772bf624b54cd194a772482110cf13`,
`24a8cd1ed1ed4980b8c3cf75657f143c` and `dd4b3c70cfce4e6ab2361b3baea25254`.
All three exact patch bytes are consumed. Private provenance retains review
head/patch/receipt hashes, ancestor checks and every consumed file identity.
LINUX027 remains needs_split after two failures; none of its history is reset.

## Preparation and native gate

The local source-only checkpoint composes all ten patches onto clean Wonder
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. Ordinary sequential `git apply`
produces the identical 449-file source fingerprint in the offline test.
Private preparation adds the validated control header: 450 source files and
319 actual generated files were verified. The canonical manifest SHA-256 is
`fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`.
Pinned generated/control receipt hashes remain
`a3c9827ead0ee15fbc3a7474b043d8bcb637a6672a849d7e1448344220e06d9a` and
`f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
Actual input hashes, generated identities and metadata linkage are revalidated;
receipt identity alone cannot establish input readiness.

No native configure/build/start was performed. Parent's 18:05Z receipt SHA-256
`e38c579085cf40587360d38bae9581fc9055fca1cfe6378712eb473b11a661a8`
covers immutable 043 source only. Neither that receipt nor 1728 staging can
authorize this profile. Fresh 049 readiness is absent; do not wait or poll SSH.
The exact committed-head bundle, source/control hashes, native argv and parent
request are retained under ignored `.local/linux-hid-cumulative-049/`.

After independent Astra/medium exact-head pass, parent exclusively transfers the
source bundle to a NEW isolated checkout on the owned Pod configured
as `ACS_RUNPOD_POD_ID` (`--pod`), alias
`acs-afternoon-linux`, preserving all 043 staging. Parent verifies bundle hashes,
clean checkout, source/receipt/input/dependency identities, live STOP absence and
current all-four-platform controls. No credentials, keys or full dump are needed.
No worker provision, transfer, install, provider administration or nested review
is authorized. Parent commissions review and landing; review is not waived.

Native CLI requires `--parent-readiness` inside the new checkout's ignored
`.local`. The parent JSON must include schema 1, unit LINUX-HID-CUMULATIVE-049,
`at` (UTC, no more than 600 seconds old), pod, alias, exact `head`, profile,
`wrapper` (SHA-256 and bytes), `afternoon_controls` (four hashes),
`live_stop_absent: true`, and `review` with matching head, verdict pass,
model gpt-6-astra and effort medium. The private request provides a concrete
receipt template and all explicit arguments. Exact reviewed worker head remains
the runtime checkout identity, separate from a later landing/report commit.

Bounds remain three compile jobs, 1500 seconds total including cleanup,
one owned-Xvfb guest launch of at most 60 seconds, 20:30Z dispatch cutoff and
21:00Z deadline, at most three workers and (amount omitted) total. Source preparation,
configuration, compilation and launch share the supervisor budget. Children stay
in owned sessions; TERM/KILL cleanup covers Linux compiler process groups.
New-session escape remains an explicit limitation. Output is bounded. Receipts
retain exact argv, compile commands, compiler hashes, per-TU source and object hashes, counts,
executable/log identities, exit/signal, first fatal line and guest observations.
Parent's fresh host/GPU evidence and the actual guest trace remain separate.

The latest actual Linux observation remains the 12:01Z `469d03f` launch stopping
at IParentalControlService command 1. Passing this checkpoint does not advance
that native boundary. A fresh run must report progression through parental,
logger, APM and HID initialization and its exact first successor, or the earlier
actual failure. No runtime boundary, compiler result, GPU, game frame or gameplay
is inferred from Mac, Windows or simulator evidence. No real game visuals exist
from this unit, so no visual update is manufactured. Future genuine frames and
approximately five-second advancing clips must be inspected, labeled and kept
privately through visual-updates.json and the store inbox. Semantic function,
service and shader percentages remain unknown; cross-ISA byte match is N/A.

Verification uses actual subprocesses/temporary Git and clean local pinned
Wonder (override its location with `LINUX_REFERENCE`); no cloud or credentials:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_linux_runtime_startup.py -v
git diff --check main HEAD
```

The Linux `/proc` descendant cleanup test is skipped on macOS. That skip does
not establish native Linux cleanup acceptance. Private preparation and verification
receipts are retained, not deleted.
