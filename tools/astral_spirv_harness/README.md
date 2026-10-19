# Astral offline SPIR-V harness

This directory builds Wonder's offline Maxwell to SPIR-V harness
(`tools/maxwell/spirv_harness` in the pinned runtime, MIT) with one opt-in
change for Astral Chain. The harness uses Ryujinx.Graphics.Shader (MIT) as
the translator. Neither the upstream sources nor the translator binaries are
vendored here: this directory holds only a patch and a build project, and
both upstream license notices continue to apply.

## The change

`astral-headerless-compute.patch` adds the flag `--astral-headerless-compute`.
Upstream treats a block as compute only when the code starts with the NVN
compute header magic `0x12345679`. Astral's compute blocks have no such
header, and their control section records program start (`ctrl+0x708`) 0.
Graphics blocks always start after the 0x30-byte header. With the flag, a
block whose program start is 0 is also treated as compute. Without the flag,
the harness behaves exactly as upstream: the only behavioural line is the
upstream test OR-ed with `(HeaderlessCompute && start == 0)`, and
`HeaderlessCompute` is set only from the flag.

## Build and run

You need a .NET 10 SDK and an already-built translator directory (containing
`Ryujinx.Graphics.Shader.dll`, `Ryujinx.Common.dll` and `Spv.Generator.dll`,
as prepared by `tools/prepare_shader_tools.py`). Nothing is downloaded beyond
the SDK's own restore.

```sh
src=.local/astral-spirv-harness/src          # private, ignored copy
mkdir -p "$src"
git -C "$WONDER" show 010ed7a596a621c15d3a8dfa5795ca8c3668b066:tools/maxwell/spirv_harness/Program.cs > "$src/Program.cs"
git -C "$WONDER" show 010ed7a596a621c15d3a8dfa5795ca8c3668b066:tools/maxwell/spirv_harness/StaticGpuAccessor.cs > "$src/StaticGpuAccessor.cs"
patch -p1 -d "$src" < tools/astral_spirv_harness/astral-headerless-compute.patch
dotnet build tools/astral_spirv_harness/AstralSpirvHarness.csproj -c Release \
  -p:HarnessSourceDir="$PWD/$src" -p:TranslatorDir="$TRANSLATOR"
dotnet .local/astral-spirv-harness/bin/Release/net10.0/astral_spirv_harness.dll \
  --batch <extracted dir> --out <dir> --astral-headerless-compute
```

The project refuses to build when `HarnessSourceDir` is unset, when its
`Program.cs` lacks the patch, or when `TranslatorDir` has no translator.
Build products go to `.local/astral-spirv-harness/`
(`Directory.Build.props`). Inputs and outputs are game-derived and stay in
private ignored storage.

## Regression evidence

The private rebuild was checked in two ways:

- **Equivalence:** a rebuild of the unmodified upstream sources against the
  retained translator reproduced the retained harness's outputs
  byte-for-byte on 80 outputs, so this build route does not itself change
  translation.
- **Patch identity:** applying this patch to the pinned `Program.cs` gives a
  file byte-identical to the private patched copy, and this project built it
  offline with 0 warnings and 0 errors.

`tests/test_astral_spirv_harness.py` checks the patch against the pinned
upstream file in a temporary Git repository and checks the opt-in structure.
It runs no .NET.

## Accepted risks (not independently proven)

The flag routes Astral compute blocks through upstream compute paths that
were written for Wonder. These assumptions mirror the runtime's, but nothing
here proves them for Astral:

- Compute local size is read from `ctrl+0x748/0x74c/0x750` and clamped to at
  least 1.
- Shared-memory size is read from `ctrl+0x754`.
- Constant data appended to the block (`ctrl+0x700`, size `ctrl+0x6fc`) is treated as NVN's `c[1]`; an out-of-range read returns 0.
- `unalignedStorage` (a draw-time query) is answered statically as `false`.
- Program start 0 is taken to mean compute. A graphics block with start 0
  would be misclassified, but none is known.

The cautions in ASTRAL_COMPUTE_METADATA.md
and ASTRAL_COMPUTE_CONTRACT.md remain
open. Successful translation is not evidence of correct GPU results.
