# Astral shared fonts and software keyboard

Two strict-only overlays, applied after the native overlay stack (`NATIVE_ORDER`, then
`astral-nvn-window-depth.patch`, `astral-nvn-bc-zero-fill.patch` and `astral-nvn-cube-storage.patch`):

1. `runtime/patches/astral-shared-font.patch` changes `runtime/src/hle_pl.cpp`.
2. `runtime/patches/astral-swkbd.patch` adds `runtime/src/hle_swkbd.cpp` and lists it in `CMakeLists.txt` for
   `NX_GAME=astral` only. The hunk's context includes `astral-hwopus.patch`, so apply it after that patch.

Neither overlay changes the default profile. `hle_pl.cpp` preprocesses identically and `hle_swkbd.cpp` preprocesses
to nothing.

The fonts come from the owner's own firmware dump, extracted with an existing tool (see README.md). Fonts, keys and firmware stay in ignored private storage.

## ABI findings (Astral's own SDK and main, disassembled)

### Fonts
- `main` imports `nn::pl::GetSharedFont`, `GetSharedFontAddress` and `GetSharedFontSize`. It does not import
  `ScalableFontEngineHelper::Decode`, and no SDK code calls `Decode`.
- `main+0x5638f0` calls `GetSharedFont(&count, records, 6, language)`. It then loops over `count` records and passes
  only each record's **type** to `main+0x562ac0`.
- `main+0x562ac0` calls `GetSharedFontSize(type)` and `GetSharedFontAddress(type)`. It passes that address directly to
  `nn::fontll::ScalableFontEngine::LoadFont` (`sdk+0x18f200`), which forwards to iType's `FSS_load_font`.
  That address must therefore point at the TrueType data itself.
- The SDK's `GetSharedFontAddress` (`sdk+0x32a560`) returns the mapped base of the 0x1100000 shared memory plus the
  pl:u offset (cmd 3), which lies past each font's 8-byte header. `GetSharedFontSize` (`sdk+0x32a700`) returns the
  TrueType size (cmd 2).
- `bool GetSharedFont(int* outCount, SharedFontData* out, int count, settings::LanguageCode)` (`sdk+0x32aa70`)
  calls pl:u cmd 5 with three 6-entry u32 arrays (types, offsets, sizes), then:
  - sets `*outCount` to the service's count before any clamping;
  - fills `min(count, outCount)` records, each `{u32 type @0, u64 address @8 = base + offset, u64 size @0x10}`
    with a stride of 0x18;
  - returns false when the service reports the fonts are not loaded, and aborts on an IPC error.
- `Decode` (`sdk+0x18fb60`) has a second key. If the first word is 0x1A879BD9 it uses key 0xA6018502; otherwise it
  uses 0x49621806. Both the extractor and the runtime support both keys.

**The header-versus-payload mismatch is resolved in favour of the SDK.** The runtime's existing `hle_pl.cpp` returns
the header address and a size of TTF + 8. That suits Wonder, whose game code calls `Decode`. Astral never calls
`Decode`, so under strict mode it would receive the plain magic where `FSS_load_font` expects TrueType. The overlay
returns the payload address and the TTF size, as the SDK and pl:u do.

### Software keyboard
- `main+0x995390` calls `InitializeKeyboardConfig` and `MakePreset`, then sets `TextMaxLength` to the game's limit
  minus 1 and `IsUseUtf8` to 0. It then sets up the work buffer (`GetRequiredWorkBufferSize(false)` = 0x1000) and the
  string buffer (`GetRequiredStringBufferSize()` = 0x7d4), and calls `SetInitialText` and then
  `ShowKeyboard(String* out, const ShowKeyboardArg& arg)` (`sdk+0x371900`).
  - On 0 it reads `out->ptr` as UTF-16.
  - On any other value it skips the name. Both paths return normally.
- `String` is `{u64 ptr, u64 size}`. The `ShowKeyboardArg` fields this overlay uses:

  | field | offset | type |
  |---|---|---|
  | TextMaxLength | 0x3ac | u32 |
  | TextMinLength | 0x3b0 | u32 |
  | IsUseUtf8 | 0x3bd | u8 |
  | InitialStringOffset | 0x3c0 | u32 |
  | InitialStringLength | 0x3c4 | u32 |
  | IsUseTextCheck | 0x3d0 | u8; `MakePreset` clears it and Astral never sets it |
  | work buffer | 0x4d0 | ptr |
  | work buffer size | 0x4d8 | u64 |

  The SDK pushes a 0x4c8-byte KeyboardConfig. These offsets match LASRecomp's hint.
- `ReadCloseResultAndString` (`sdk+0x371540`) reads a u32 CloseResult, then copies `out->size` bytes of text into
  `out->ptr`. It copies nothing when either is 0. `ShowKeyboard` returns 0 when CloseResult is 0, and 0x29f
  (ResultCanceled) otherwise.

## Replacement fonts without firmware (tools/acr_build.py)

The runtime is unchanged: it still requires six valid BFTTF files. When a player gives no `--fonts`, the build
script supplies them itself. It downloads Noto Sans Regular (SIL OFL 1.1, a static hinted TrueType file pinned by
commit and SHA-256), wraps it in the BFTTF container with the standard key (the same layout the runtime decodes and
`tests/test_astral_shared_font.py` encodes), and installs that one font in all six slots under
`<data root>/shared-fonts`, next to the OFL text and a `REPLACEMENT.txt` note. `--replacement-font <file>` uses
another TrueType font. A player's own `.bfttf` files, or decoded `.ttf`/`.otf` files with the canonical names,
are checked and installed instead.

Limits: the replacement has none of the Nintendo extended font's button glyphs and no CJK coverage, so those
characters do not display. Six copies of a 0.6 MB font stay well under the 0x1100000 region. The container format
is covered by tests. The replacement fonts are installed and format-checked; **their in-game appearance is not
yet verified**.

## Runtime behaviour (strict)

### Fonts
- **Source:** `<NX_SHARED_FONT_DIR>`, or else `<data root>/shared-fonts`, then the canonical file for each type:

  | type | font | file |
  |---|---|---|
  | 0 | standard | `nintendo_udsg-r_std_003.bfttf` |
  | 1 | Chinese simplified | `nintendo_udsg-r_org_zh-cn_003.bfttf` |
  | 2 | Chinese simplified extension | `nintendo_udsg-r_ext_zh-cn_003.bfttf` |
  | 3 | Chinese traditional | `nintendo_udjxh-db_zh-tw_003.bfttf` |
  | 4 | Korean | `nintendo_udsg-r_ko_003.bfttf` |
  | 5 | Nintendo extended | `nintendo_ext_003.bfttf` |
- **Missing or bad fonts are fatal**, with a message that names the file and the extractor. This covers a missing
  file, a bad magic, a size that does not fit, data that does not decode to TrueType/OpenType, and a total above
  0x1100000. There is no host-font fallback and no fake font.
- **Layout:** as pl's: a single 0x1100000 region, with types 0..5 back to back from offset 0. Each font is
  `{0x18029A7F, bswap(size ^ 0x49621806)}` followed by the decoded TrueType. Nothing is mapped until every font is
  valid.
- **Hooks:**
  - `GetSharedFontAddress(type)` returns region + offset (the TrueType data).
  - `GetSharedFontSize(type)` returns the TrueType size.
  - `GetSharedFontLoadState(type)` returns 1 (Loaded).
  - `GetSharedFont` sets `*outCount = 6`, fills `min(count, 6)` records in type order 0..5, and returns true.
  - A type of 6 or more, or a null output pointer, is fatal.
- **Order:** the order ignores the language, matching observed system behaviour. Astral loads every listed font anyway.

### Software keyboard
- **Name:** `ShowKeyboard` returns 0 with `NX_PLAYER_NAME`. When that is unset or empty it uses `Player`.
- **Lengths:** the text is repeated up to `TextMinLength`, the same as observed system behaviour. It is then cut
  to whole characters within `TextMaxLength` UTF-16 units; 0 means 500, and values above 500 are capped at 500.
- **Encoding:** the text is UTF-16LE unless `IsUseUtf8` is set. It is NUL-terminated and always fits `out->size`,
  and the rest of the buffer is zeroed.
- **Cancel:** `NX_SWKBD_CANCEL=1` returns 0x29f with empty text, which exercises the game's cancel path.
- **Failures:**
  - Invalid UTF-8 in `NX_PLAYER_NAME`, a null `String` or argument, and `IsUseTextCheck` are all fatal.
  - With a null `out->ptr` or a zero `out->size`, the overlay writes nothing, as the SDK does.
- **Not used:** strict mode never reaches am `CreateLibraryApplet`.

## Tests

| test | what it covers |
|---|---|
| `tests/test_astral_shared_font.py` | Before the overlay, `GetSharedFont` is unhooked and the address is the header's. After it, an independent encoder covers both keys and odd sizes. The test checks the region layout, the header words, the TrueType address and size, `GetSharedFont` records (count 0, 3 and 9, untouched padding and slots), every failure message, and identical default preprocessing. |
| `tests/test_astral_swkbd.py` | UTF-16 and UTF-8 output, the max and min limits, surrogate pairs, small or missing buffers, cancel, strict failures, the CMake listing for Astral only, and the empty default TU. |

## Risks

- **No game-run evidence.** The game was not launched. Whether iType's `FSS_load_font` renders the real fonts at
  these addresses, and whether name entry completes, still has to be confirmed in a run.
- **Font order.** The order ignores the language. Real pl puts the language's own font first, which could change
  glyph fallback for zh/ko system languages.
- **Text check.** Fatal if a future path enables it; Astral's current path does not.
- **Other platforms.** The extractor needs macOS (CommonCrypto). Extraction is a one-time owner step, and the fonts
  are platform-neutral.
