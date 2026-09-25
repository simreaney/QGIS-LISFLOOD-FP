# LISFLOOD-FP for QGIS

Drives the [LISFLOOD-FP](https://www.seamlesswave.com/) 2D hydraulic flood model from
QGIS: builds the model deck from your layers, runs it with live progress, and loads the
results as styled, georeferenced layers.

Verified against LISFLOOD-FP **8.1.0** (SEAMLESS-WAVE fork) on macOS 26 / Apple Silicon,
under both **QGIS 3.42 (Qt 5)** and **QGIS 4.0.1 (Qt 6)**.

## Installing

The plugin does **not** ship LISFLOOD-FP. You need a source checkout; the plugin builds
it for you. 

1. You need to get the source code for LISFLOOD-FP 8.2 from the public repositery at [Zenodo](https://zenodo.org/records/13121102). Download and unzip the folder. 

2. Downlaod this repo as a zip and use the 'Install from Zip' option in the plugins
3. Enable **LISFLOOD-FP** in Plugins → Manage and Install Plugins.
4. Install the build prerequisites for your platform (below).
5. Run **LISFLOOD-FP ▸ Setup ▸ Build or locate LISFLOOD-FP executable**, pointing it at
   your source checkout.

Step 4 does the whole build of LISFLOOD-FP for you and registers the result. The per-platform notes below say what it does and how to reproduce it by hand if you would rather.

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

## Notes:

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
That is not possible on macOS, but is possible on Linux and Windows — see those
sections. Where the binary reports `CUDA supported`, the plugin stops disabling the GPU
options. `mwdg2` and `hwfv1` additionally use a separate `.par` dialect that the deck
builder does not generate; run those from a hand-written deck.

**`dg2`** needs a slope-coefficient preprocessing pass (`generateDG2DEM` /
`generateDG2start`) that is not yet wired up.

**Sub-grid channels** (`SGCwidth` and friends) and **weirs** can be supplied through the
advanced keyword field, but have no dedicated UI.


## Licensing and References

This plugin does not distribute the source code or the binaries for LISFLOOD-FP. The repo on Zenodo uses a GNU General Public License v2.0 only.  
References:
LISFLOOD-FP developers. (2024). LISFLOOD-FP v8.2 hydrodynamic model (Version 8.2) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.13121102.  
Bates, P. D., & de Roo, A. P. J. (2000). A simple raster-based model for flood inundation simulation. Journal of Hydrology, 236(1-2), 54-77
