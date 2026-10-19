# Linux NVIDIA and original-runtime preflight

LINUX-GPU-002, 2026-10-18. Actual execution was over `ssh acs-recovery-linux`
on the parent's already-owned Ubuntu 22.04.5 x86-64 pod. Work and dependency
builds are isolated under `/root/acs-units/LINUX-GPU-002`; compile parallelism
was three. No provider lifecycle actions, host-driver replacements, game-input
reads, credentials, game execution or nested workers were involved. The host
and installed dependencies remain available for subsequent units. Parent owns
independent review, landing and eventual host deletion.

## Observed results

- **GPU readback passed:** NVIDIA RTX A5000, vendor `0x10de`, device `0x2231`,
  proprietary driver `580.159.04`, Vulkan physical-device API `1.4.312`, graphics
  queue family 0. The original probe selected a discrete NVIDIA device, allocated
  an optimal device-local RGBA8 image, submitted layout transitions and a red
  clear, copied it into coherent host-visible staging memory, waited for the
  queue, and checked all 4,096 pixels against `[255,0,0,255]`. Khronos validation
  was enabled; **zero validation errors**. Output is a 64×64 PPM and JSON receipt.
- **Synthetic X11 surface capture passed:** distro `vkcube --validate` selected
  `GPU 0: NVIDIA RTX A5000`. Under a private Xvfb server, the captured root image
  visibly contains the rendered LunarG cube. The reusable command runs it for
  six seconds and expects timeout exit 124, records the live window tree and
  checks a nonuniform screenshot. This is accelerated synthetic presentation
  into a virtual X11 surface, not a physical display or a game frame.
- **Pinned original-runtime smoke passed:** exact Wonder revision
  `010ed7a596a621c15d3a8dfa5795ca8c3668b066`; native Release builds of
  `gpu_pick_test`, `tiling_test`, `astc_test`, `shader_cache_test` succeeded.
  CTest passed `gpu_pick`, `tiling --selftest`, `astc --selftest` (3/3, 3.40 s).
  Shader-cache was **compiled only**; its private shader-dependent test was not
  run. This verifies original runtime pieces, not generated modules or startup.
- **Toolchain ready:** pinned SDL3 built and installed locally; a native C++20
  executable including SDL3, `nx/cpu.h`, `vk_gen.h` and the pinned Vulkan headers
  compiled, linked and exited 0 with `-march=x86-64-v3 -ffp-contract=off`.
  This tests the header/compiler interface, not the whole game runtime.

The NVIDIA ICD is `/etc/vulkan/icd.d/nvidia_icd.json`, naming
`libGLX_nvidia.so.0`, API `1.4.312`. Initially the ICD could not initialize;
`strace` exposed missing `libEGL.so.1`. Installing distro `libegl1`/`libgl1`
fixed it without changing NVIDIA driver files. Mesa software ICDs also exist;
the probe explicitly refuses to accept them. A warning about an unrelated ICD
being skipped appears in the successful mixed-ICD run; the selected NVIDIA
probe reports zero validation errors. Full instance/device extensions and
features are retained in `vulkaninfo.txt`, and selected device extensions in
`receipt.json`.

NVIDIA feature inspection reports geometry/tessellation, BC compression,
shaderInt64, timelineSemaphore, synchronization2 and dynamicRendering available;
ASTC LDR compression is **false**. Runtime ASTC decode/format behavior therefore
still needs testing. Header version 1.4.357 exceeds this driver's 1.4.312 API:
header compilation does not establish availability of every bridged entry point
or extension. Real pipeline/resource/shader compatibility remains unverified.

## Versions and private evidence

Tools used: Clang `14.0.0` (Ubuntu package `clang 1:14.0-55~exp2`), Ninja
`1.10.1`, local CMake/CTest `3.31.6` in the task venv. Distro CMake
`3.22.1-1ubuntu1.22.04.2` is too old for upstream's minimum 3.25 and was not
used for the runtime/SDL builds. The system Vulkan loader/headers package is
`1.3.204.1-2`, vulkan-tools `1.3.204.0+dfsg1-1`, validation layers
`1.3.204.1-2`. Xvfb is `2:21.1.4-2ubuntu1.7~22.04.16`, ImageMagick
`8:6.9.11.60+dfsg-1.3ubuntu0.22.04.5`; libegl1/libgl1 are `1.4.0-1`.
`package-versions.txt` and `distro-packages.txt` retain exact package versions.

Dependencies are anonymous public clones in the ignored remote
`repo/.local/references/` directory:

| Dependency | Immutable revision | Ready path |
| --- | --- | --- |
| Wonder | `010ed7a596a621c15d3a8dfa5795ca8c3668b066` | `repo/.local/references/wonder` |
| SDL3 3.2.24 | `a8589a84226a6202831a3d49ff4edda4acab9acd` | `repo/.local/sdl3` (installed prefix) |
| Vulkan-Headers 1.4.357 | `e3b1eec08173d6b825cd3ac88c885a63b621504a` | `repo/.local/references/Vulkan-Headers/include` |

All paths above are relative to `/root/acs-units/LINUX-GPU-002`.
Local ignored evidence is retained in this worker's `.local/evidence/`:

- `gpu-final/receipt.json`, `nvidia-clear.ppm`, `check.log`, `vulkan-summary.txt`,
  `vulkaninfo.txt`, `surface.png`, `surface-receipt.json`, `vkcube.log`, `windows.txt`.
- `smoke/receipt.json` and numbered logs `0.log`–`7.log`.
- `fixture-tests.log`, `package-versions.txt`, `distro-packages.txt`,
  `sdl-configure.log`, `sdl-build.log`, `sdl-install.log`, `toolchain.json`,
  `header-check.log`, `header-check.cpp`.

The earlier `surface/` image was captured after a short cube run had already
exited and is black; it is **not** accepted evidence. `surface-live/` and the
final reusable command's `gpu-final/surface.png` were captured while rendering.
Private evidence is not tracked or distributed with the source.

## Reusable commands

On the Linux host, from the transferred scoped source checkout:

```sh
cd /root/acs-units/LINUX-GPU-002/repo
export PATH=/root/acs-units/LINUX-GPU-002/venv/bin:$PATH
# Use fresh, ignored output directories for each invocation.
bash scripts/check-linux-gpu "$PWD/.local/gpu-next" --surface
python3 tools/runtime_smoke.py \
  --source "$PWD/.local/references/wonder" \
  --output "$PWD/.local/smoke-next" --jobs 3 \
  --cmake /root/acs-units/LINUX-GPU-002/venv/bin/cmake \
  --ctest /root/acs-units/LINUX-GPU-002/venv/bin/ctest
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_runtime_smoke.py' -v
bash -n scripts/check-linux-gpu
```

Omit `--surface` for device-only clear/readback. The GPU entry point compiles
`clang++ -std=c++20 -O2 ... tools/linux_gpu_probe.cpp -lvulkan`, records compiler,
CMake, Ninja, Vulkan package and ICD details, then runs the probe. Its device
JSON explicitly says offscreen and `presentation_verified:false`; the optional
presentation check has a separate receipt. A failure must not be reported as a
frame or hidden with a software ICD.

The runtime wrapper requires source and output to be gitignored inside the
wrapper repository's `.local`, rejects symlinks, tracked paths, wrong lock/pin,
dirty source, overlapping paths and reused output. It sets `NX_TESTS=ON`,
`NX_GAME=wonder`, and an empty `NX_GEN_DIR`, builds only the four named targets,
then verifies CTest registered exactly the three selected synthetic checks.
Every command/exit/log is recorded, including failures. Seven fixture tests
passed on Linux, including real temporary Git/CMake/Ninja build/test execution
and a missing-test rejection. On this Mac the exact unittest command passed
with two native fixture tests skipped because Ninja is absent; no Mac global
tool installation was performed.

Preparation commands used on the disposable Linux host (never the Mac):

```sh
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential clang ninja-build cmake pkg-config libvulkan-dev vulkan-tools \
  vulkan-validationlayers xvfb x11-apps x11-utils imagemagick libx11-dev git \
  python3-venv libegl1 libgl1 libxext-dev libxrandr-dev libxcursor-dev libxi-dev \
  libxfixes-dev libxss-dev libxtst-dev libasound2-dev libpulse-dev libudev-dev \
  libwayland-dev libxkbcommon-dev libdrm-dev libgbm-dev strace
python3 -m venv /root/acs-units/LINUX-GPU-002/venv
/root/acs-units/LINUX-GPU-002/venv/bin/pip install cmake==3.31.6
# SDL checkout and Vulkan-Headers checkout must first match the table above.
cmake -S .local/references/SDL -B .local/sdl-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PWD/.local/sdl3" \
  -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF
cmake --build .local/sdl-build --parallel 3
cmake --install .local/sdl-build
```

## Next integration gate

The host is suitable for the next native Vulkan build and synthetic X11
presentation check. No host blocker remains for those tested paths. Reuse the
local CMake, SDL3 prefix and pinned Vulkan include directory above. The parent
should run the reviewed `tools/prepare_runtime.py --configure --build --jobs 3`
on its own prepared Astral source/input/generated-code workspace, passing:

```sh
--cmake /root/acs-units/LINUX-GPU-002/venv/bin/cmake \
--ninja /usr/bin/ninja \
--prefix /root/acs-units/LINUX-GPU-002/repo/.local/sdl3 \
--vulkan-include /root/acs-units/LINUX-GPU-002/repo/.local/references/Vulkan-Headers/include
```

The parent must supply the reviewed `--repo`, `--reference`, `--inputs`, `--gen`
and fresh `--out` paths; this unit deliberately did not inspect game inputs or
build generated modules. Configure must produce the actual Astral target and
compile commands, rather than upstream's no-generated-code early return. Then
build with three jobs and diagnose strict startup imports/services and shader
pipelines. Validate real shader/texture features against NVIDIA's capabilities,
including ASTC decode, before claiming a game frame. Windows and Apple remain
separate acceptance gates; this result does not establish their graphics or
runtime compatibility.
