# Simulator external shader-tool boundary

`ios-nvn-compile.patch` is an original incremental overlay for Wonder revision
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. It applies after the reviewed
Apple memory and Astral bootstrap patches and `ios-runtime.patch`. Its only
upstream path is `runtime/src/nvn/nvn_pipeline.cpp`; it changes only the
environment-selected external SPIR-V diagnostic command block.

The dedicated simulator CMake target defines `NX_IOS_RUNTIME=1`. When
`NX_SPIRV_OPT` or `NX_SPIRV_TOOL` requests an external tool, this target calls
`nx::fatal` with the operation name before constructing temporary paths,
opening files, launching a subprocess, or creating a Vulkan shader module.
The unavailable iOS `std::system` reference is excluded at preprocessing time.
Without either request the existing shader path is unchanged; that is no claim
of simulator shader, Vulkan, GPU or presentation support. The platform adapter
still fails explicitly when unsupported graphics/audio operations are reached.
Desktop targets retain the original command construction, return-code handling,
output loading and temporary-file removal, without changes.

`tests/test_ios_nvn_compile.py` extracts the complete conditional command block
from the shipped overlay context and compiles it with a synthetic shader and
fatal handler. Its simulator fixture marks `std::system` unavailable, verifies
both environment selectors produce the explicit fatal, and proves execution
stops before even querying the process ID. Its host fixture runs real synthetic
subprocess tools for both selectors, checks their input bytes and hash argument,
observes replacement output words, and checks temporary-file removal. All tool
scripts, binaries and durable fixture evidence use a temporary directory; the
unchanged desktop command's transient `/tmp/nx_spv_*` files are removed by the
actual tested code. The simulator fixture creates none of them.

`test_ios_runtime.py` independently applies all four overlays to the exact local
upstream pin and configures the actual iOS CMake branch with generated synthetic
modules. The full native build and the separately retained guest measurements
are documented in `IOS_RUNTIME.md`. Compiled fixture success alone does not
establish native linking or guest startup. Independent exact-head Astra/medium
review remains required and is owned by the lead; no review is waived.
