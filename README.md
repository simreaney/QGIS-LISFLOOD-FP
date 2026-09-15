# LISFLOOD-FP for QGIS

Drives the [LISFLOOD-FP](https://www.seamlesswave.com/) 2D hydraulic flood model from
QGIS: builds the model deck from your layers, runs it with live progress, and loads the
results as styled, georeferenced layers.

Verified against LISFLOOD-FP **8.1.0** (SEAMLESS-WAVE fork) on macOS 26 / Apple Silicon,
under both **QGIS 3.42 (Qt 5)** and **QGIS 4.0.1 (Qt 6)**.

## Installing

The plugin does **not** ship LISFLOOD-FP. You need a source checkout; the plugin builds
it for you.

1. Copy or symlink this folder into your QGIS profile's `python/plugins` directory:

   | Platform | Profile directory |
   |---|---|
   | macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |
   | Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |
   | Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins` |

2. Enable **LISFLOOD-FP** in Plugins → Manage and Install Plugins.
3. Install the build prerequisites for your platform (below).
4. Run **LISFLOOD-FP ▸ Setup ▸ Build or locate LISFLOOD-FP executable**, pointing it at
   your source checkout.

Step 4 does the whole build for you and registers the result. The per-platform notes
below say what it does and how to reproduce it by hand if you would rather.

---

### macOS

```bash
brew install llvm libomp cmake
```

Apple's own compiler ships no `omp.h`, and LISFLOOD-FP includes it unconditionally, so a
Homebrew LLVM toolchain is required. The plugin finds it under `/opt/homebrew/opt`
(Apple Silicon) or `/usr/local/opt` (Intel).

By hand:

```bash
cmake -S <source> -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_C_COMPILER=/opt/homebrew/opt/llvm/bin/clang \
  -DCMAKE_CXX_COMPILER=/opt/homebrew/opt/llvm/bin/clang++ \
  -DOpenMP_ROOT=/opt/homebrew/opt/libomp \
  -DCMAKE_MODULE_PATH=<plugin>/cmake_shims
cmake --build build -j
```

Two macOS-specific things are going on.

**The NUMA fix.** The stock `CMakeLists.txt` does `if (UNIX) find_package(NUMA
REQUIRED)`. CMake's `UNIX` is true on macOS, but `libnuma` is Linux-only, so configure
fails outright. The plugin supplies a replacement find-module on the command line
(`-DCMAKE_MODULE_PATH=<plugin>/cmake_shims`) rather than editing your checkout. That
works because `CMakeLists.txt` *appends* to `CMAKE_MODULE_PATH`, so the shim is found
first, and it is safe because the only NUMA code in the model sits behind
`#ifdef __unix__`, which Apple's compiler never defines. Your source tree stays
byte-identical and survives a `git pull`. **This shim is applied on macOS only** —
see the Linux note below.

**Architecture on Apple Silicon.** QGIS 3.x is an x86_64 build, so it runs under
Rosetta and everything it launches reports `x86_64` from `platform.machine()`. Left
alone, CMake would configure an x86_64 build and then fail the OpenMP check against an
arm64-only Homebrew libomp. The plugin reads `sysctl -n hw.optional.arm64` instead,
which reports the real hardware, and passes `-DCMAKE_OSX_ARCHITECTURES` explicitly.
If you build by hand from a terminal this does not arise, but set the flag anyway to be
sure of what you get.

No CUDA on macOS, so the GPU solvers are unavailable.

---

### Linux

```bash
# Debian / Ubuntu
sudo apt install build-essential cmake libnuma-dev libnetcdf-dev

# Fedora / RHEL
sudo dnf install gcc-c++ cmake numactl-devel netcdf-devel
```

`libnuma` is a genuine requirement here, not a workaround: the NUMA code at
`lisflood2/lisflood_processing.cpp` is guarded by `#ifdef __unix__`, which GCC and Clang
*do* define on Linux, so it really is compiled. **The plugin therefore does not apply
the macOS shim on Linux** — doing so would quietly disable working NUMA support. If
configure fails with a missing NUMA, install the package above rather than reaching for
the shim.

OpenMP comes with GCC and Clang, so no toolchain flags are needed. CMake needs to be
3.13 or newer; on older distributions `sudo snap install cmake --classic` is the usual
route.

By hand:

```bash
cmake -S <source> -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

The executable is `build/lisflood`.

**CUDA.** Unlike macOS, Linux can build the GPU solvers. If the NVIDIA CUDA Toolkit is
installed, CMake detects it automatically and compiles `fv2`, `acc_nugrid`, `mwdg2` and
`hwfv1` alongside the CPU solvers; `lisflood -version` then reports `CUDA supported`.
The plugin reads that line and stops greying out the GPU options. Note that `mwdg2` and
`hwfv1` use a separate `.par` dialect that this plugin does not generate.

---

### Windows

Install **Visual Studio 2019 or newer** with the *Desktop development with C++*
workload (the standalone *Build Tools for Visual Studio* is enough, and includes CMake).

Windows needs no NUMA handling at all — `if (UNIX)` is simply false, so that block never
runs. NetCDF needs nothing either: the headers and import library are vendored in
`windep/netCDF4-64`, and CMake copies the runtime DLLs from the `DLL's` folder into the
build directory.

From a *Developer Command Prompt for VS*:

```bat
cmake -S <source> -B build -A x64
cmake --build build --config Release --target lisflood
```

Two Windows-specific wrinkles, both of which the plugin handles:

- **Visual Studio is a multi-config generator.** The executable is written to
  `build\Release\lisflood.exe`, not `build\lisflood.exe`, and `--config Release` is
  required at build time rather than `-DCMAKE_BUILD_TYPE`. The plugin passes `--config`
  always (single-config generators ignore it) and searches the per-configuration
  subdirectories when locating the result.
- **The NetCDF DLLs land in the build root**, one level above the executable. The plugin
  puts both directories on `PATH` for the child process. If you run `lisflood.exe`
  yourself from a terminal and it fails to start, that is why — copy the DLLs next to
  the executable or add `build\` to `PATH`.

MSVC provides OpenMP through `/openmp`, which CMake wires up on its own. CUDA is
detected automatically if the toolkit is present.

> Windows and Linux instructions are derived from the project's own `README.md` and from
> reading `CMakeLists.txt`; they have not been executed on this machine, where only the
> macOS path is tested end to end. The plugin code paths for both are in place.

---

## Algorithms

| Algorithm | Purpose |
|---|---|
| `lisfloodfp:buildmodel` | QGIS layers → a complete, runnable deck. No executable needed. |
| `lisfloodfp:runmodel` | Run an existing `.par`, with progress and cancellation. |
| `lisfloodfp:simulate` | Build and run in one step. |
| `lisfloodfp:loadresults` | Load output grids as styled layers. |
| `lisfloodfp:buildbinary` | Compile or locate the executable. |

They also work headlessly:

```bash
qgis_process run lisfloodfp:runmodel -- PAR_FILE=model.par THREADS=4
```

## Things worth knowing

**Discharge is entered in m³/s.** LISFLOOD-FP wants it per metre of cell width, and the
plugin converts — including hydrographs in a time series, where the divisor depends on
how many cells the referencing boundary spans. A series shared by boundaries of
different widths is rejected rather than guessed at.

**Decks use relative filenames and run with the working directory set to the deck.**
The model reads filenames with `sscanf("%255s")`, so any path containing a space is
truncated. Keeping filenames relative means a deck inside `~/Documents/My Project/`
works anyway — the model only ever sees `dem.asc`.

**The results folder is pre-created.** The model otherwise shells out to an unquoted
`system("mkdir ...")`, which breaks on spaces and is not `mkdir -p`.

**Progress comes from the mass balance file, not stdout.** The model's progress line is
never flushed, so through a pipe it arrives in lumps; the mass file is explicitly
flushed after every write. This also makes progress update every mass interval rather
than every save interval.

**`log` and `gzip` are refused.** `log` redirects stdout to a file, hiding progress and
errors; `gzip` is applied through an unquoted shell call.

**Depth grids get an explicit transparency range.** The model writes dry land as a
literal `0.000`, not as nodata, so without it the whole domain renders as solid blue.
`.elev` and `.mxe` are masked with `-9999` and are styled differently.

**Flux grids are edge-centred and already offset.** `.Qx` has one extra column and an
origin shifted half a cell; the model applies that when writing, so the file is correct
as delivered. They are not co-registered with `.wd` — do not mix them in the raster
calculator.

## Channel networks

Each line feature in the channel layer becomes one segment, in feature order. Width,
Manning's n and bed elevation come from attributes and are attached to the segment's two
ends; the model interpolates between them, so a `bed_up`/`bed_dn` pair gives a uniformly
graded bed.

**Junctions are detected, not declared.** This is the fiddliest part of writing a
`.river` by hand: the tributary's downstream end must carry `QOUT <target>` while the
receiving segment carries `TRIB <source>` at *identical* coordinates, both 0-based, and
a mismatch silently drops the inflow. Here, a segment ending within one cell of another
is snapped to that segment's nearest vertex and both halves are written together.

**Channel discharge really is m³/s** and is passed through unchanged — the per-metre
conversion applies only to `.bci` boundaries. A time series used by both a channel and a
`.bci` boundary is rejected rather than silently given the wrong units for one of them.

## Not supported

**GPU solvers.** `cuda`, `fv2`, `acc_nugrid`, `mwdg2` and `hwfv1` need a CUDA build.
That is impossible on macOS, but perfectly possible on Linux and Windows — see those
sections. Where the binary reports `CUDA supported`, the plugin stops disabling the GPU
options. `mwdg2` and `hwfv1` additionally use a separate `.par` dialect that the deck
builder does not generate; run those from a hand-written deck.

**`dg2`** needs a slope-coefficient preprocessing pass (`generateDG2DEM` /
`generateDG2start`) that is not yet wired up.

**Sub-grid channels** (`SGCwidth` and friends) and **weirs** can be supplied through the
advanced keyword field, but have no dedicated UI.

## A note on this machine's environment

`GDAL_DRIVER_PATH` is set to `~/miniconda/lib/gdalplugins`, whose plugins are signed by
a different team and built against a different GDAL. That is the source of the
`dlopen ... not valid for use in process` and `Cannot find proj.db` messages you may see
in QGIS. The plugin strips these variables from the model's environment, and tolerates
the failure when enabling GDAL exceptions, so it does not affect model runs — but QGIS
itself is still affected. Unsetting `GDAL_DRIVER_PATH` in your shell profile would clear
it up.

## Testing

The `core/` package has no QGIS imports, so it tests under any Python:

```bash
python3 -m pytest test/ -q          # 19 unit tests, no QGIS needed
```

The integration tests need a real QGIS and a built binary:

```bash
GDAL_DRIVER_PATH= PROJ_LIB=/Applications/QGIS.app/Contents/Resources/proj \
PYTHONPATH="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins" \
/Applications/QGIS.app/Contents/MacOS/bin/python3 test/integration/test_workflows.py
```

The round-trip test that matters most is end-to-end: build a deck asking for a known
discharge, run it, and check the mass balance reports that same discharge back. That is
what caught the QVAR conversion bug — a 40 m³/s hydrograph arriving as 400 — and neither
the reversed-column nor the unit error produces any message from the model itself.

The channel writer is additionally checked against the shipped `T007_CTBranchFine` case:
regenerating that four-segment branching network through the plugin and re-running it
produces byte-identical mass balance and maximum-depth grids.

## Licensing

This plugin does not distribute LISFLOOD-FP. The fork it was developed against carries a
Bristol University copyright notice and **no top-level licence file**, so redistributing
a compiled binary is not something to assume is permitted — the plugin builds from your
own checkout instead. Worth resolving with the code owners before any public release.
