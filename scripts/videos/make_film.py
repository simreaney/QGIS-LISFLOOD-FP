"""The walkthrough: lay the captured states on one timeline and render both formats.

    ./run_qgis.sh make_film.py              # out/landscape/*.mp4 (4K) and out/vertical/*.mp4
    ./run_qgis.sh make_film.py 12.5 40      # just stills at these times, in build/stills/

It opens on a slide made to be the thumbnail too: out/thumbnails/ has it at 1920 x 1080
for YouTube and 1080 x 1920 for an Instagram cover. Captions carry the story, since the
film has no sound; the callouts name each control as the cursor reaches it. The YouTube
chapters are written beside the films.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from qgis.core import QgsApplication, QgsRectangle  # noqa: E402

app = QgsApplication([], True)

import cover as C  # noqa: E402
import film as F  # noqa: E402
import style  # noqa: E402
from film import (LANDSCAPE, MUTED, VERTICAL, Clock, Cover, Film, Track, centre, cut, mmss,  # noqa: E402
                  walk, write_chapters)

CAPTURE = os.path.join(HERE, "build", "capture")
OUT = os.path.join(HERE, "out")
SLUG = "lisflood-fp-for-qgis-walkthrough"

with open(os.path.join(CAPTURE, "capture.json")) as handle:
    data = json.load(handle)
F.SCALE = data["scale"]
R = data["rects"]
RUN = data["runs"]["model"]
TIMELINE = data["runs"]["timeline"]


def png(name):
    return os.path.join(CAPTURE, f"{name}.png")


# ── Framings: (centre x, centre y, width) in window pixels ─────────────────

WINDOW = (960, 540, 1920)
PANEL_X = R["panel"][0] + R["panel"][2] / 2


def panel_wide(y):
    """16:9: the right of the window, the panel at full height of the frame."""
    return (1920 - 470, y, 940)


def panel_tall(y):
    """9:16: the panel's full width."""
    return (PANEL_X, y, R["panel"][2] + 16)


def on_panel(rect):
    """Both formats' framings of a panel control: above the caption, room for a note below."""
    return panel_wide(rect[1] + 60), panel_tall(rect[1] + 160)


def toolbox_wide():
    return (1500, 330, 1000)


def toolbox_tall():
    return (1700, 270, 440)


def on_map(rect, wide=1100, tall=560):
    """Both formats' framings of a place on the map."""
    cx, cy = centre(rect)
    return (cx, cy, wide), (cx, cy, tall)


INFO = json.load(open(os.path.join(style.DATA, "info.json")))
film = Film(
    "LISFLOOD-FP FOR QGIS  ·  WALKTHROUGH", "Flood modelling in QGIS",
    "Build, run and map LISFLOOD-FP flood models without leaving QGIS.",
    end_lines=[("github.com/simreaney/QGIS-LISFLOOD-FP", F.ACCENT, 40),
               ("LISFLOOD-FP itself is not bundled: the plugin builds it from your own copy "
                "of the source (Zenodo, GPL-2.0).", MUTED, 27),
               ("Appleby-in-Westmorland, Cumbria: a 1 m DTM, run at 5 m with a steady 150 m³/s. "
                "Flood defences are not represented: a demonstration, not a flood map of the town.", MUTED, 27)])
film.capture = CAPTURE
film.title_window = (-1.0, -1.0)  # the opening slide carries the title

# ── The opening slide, also the thumbnail: the run's own flood ──────────────
COVER_END = 4.0
# Full bleed, so the DTM's rectangular edges stay out of the frame: its full width
# through the meander and the town in 16:9, its full height in 9:16.
x0, y0, x1, y1 = INFO["extent"]
middle = style.TOWN.center()
height = (x1 - x0) * 9 / 16
width = (y1 - y0) * 9 / 16
areas = {"landscape": QgsRectangle(x0, middle.y() - height / 2, x1, middle.y() + height / 2),
         "vertical": QgsRectangle(middle.x() - width / 2, y0, middle.x() + width / 2, y1)}
pictures = C.pictures(os.path.join(style.DATA, "dem.tif"), os.path.join(CAPTURE, "res.max"), CAPTURE,
                      boxes={"landscape": (0.0, 0.0, 1.0, 1.0), "vertical": (0.0, 0.0, 1.0, 1.0)},
                      area=areas, fill=True, z_factor=2.0, water_cell=1.0)
film.cover(0.0, COVER_END, Cover(
    "LISFLOOD-FP FOR QGIS", "Flood modelling\nin QGIS", "Build, run and map\nLISFLOOD-FP flood models",
    f"Appleby-in-Westmorland  ·  River Eden  ·  {INFO['inflow_m3s']:.0f} m³/s", pictures,
    title_sizes={"landscape": 118, "vertical": 110}, shade_top=700))

film.state(0, png("00_project"))
film.camera("landscape", start=WINDOW)
film.camera("vertical", start=(1113, 572, 640))
film.cursor = Track((900, 700), arc=0.08)
clock = Clock(COVER_END + 0.6)
chapters = [(0.0, "The inputs")]
ROWS_TALL = (165, 380, 330)  # 9:16: the top of the Layers panel, close up

# ── The inputs ─────────────────────────────────────────────────────────────
start = clock.t
cut(film, start - 0.4, (700, 500, 1400))
table = R["table"]
walk(film, clock, [
    (R["row_dem"], "Appleby DTM (1 m)",
     "Appleby-in-Westmorland and the River Eden: 1.6 by 1.4 km of terrain, at 1 m.",
     None, False, None, (None, ROWS_TALL)),
    (R["inflow_point"], "River Eden", "The inflow point, on the channel just inside the DTM's southern edge.",
     None, False, None, on_map(R["inflow_point"], 1000, 420)),
    (R["row_inflow"], "Inflow point",
     "A point layer: its fields say what kind of boundary each point is, and how much.",
     None, True, "01_table", ((700, 500, 1400), ROWS_TALL)),
], per=3.0)
walk(film, clock, [(table, "Its attributes",
                    "bctype QFIX, a fixed inflow, and value 150: a steady 150 m³/s for the whole run.",
                    None, False, None, ((table[0] + table[2] / 2 + 200, table[1] + 260, 1100),
                                        (table[0] + table[2] / 2, table[1] + 200, table[2] + 50)))],
     per=3.6)
film.state(clock.t - 0.1, png("00_project"), crossfade=0.2)
film.caption(start, clock.t, "Start with ordinary QGIS layers: a DTM and an inflow point.",
             {"landscape": "left"})  # the inflow point is low on the right
start = clock.t
walk(film, clock, [(R["town"], "Flood defences are not represented",
                    "Appleby's flood defences are not in this model, so it is a demonstration, "
                    "not a flood map of the town.", None, False, None, on_map(R["town"], 1100, 600))], per=4.8)
film.caption(start, clock.t, "Flood defences are not represented in this model.")
cut(film, clock.t - 0.2, WINDOW, None)

# ── Set up once ────────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Set up once: build LISFLOOD-FP"))
film.state(start, png("02_toolbox"), crossfade=0.25)
cut(film, start, toolbox_wide(), toolbox_tall())
clock.wait(0.6)
walk(film, clock, [(R["tool_build"], "Processing ▸ LISFLOOD-FP ▸ Setup",
                    "Build or locate LISFLOOD-FP executable.")], per=3.0)
dialog = R["build_dialog"]
film.click(clock.t - 0.3)  # a double-click opens it
film.click(clock.t - 0.15)
film.state(clock.t, png("03_build_dialog"), crossfade=0.2)
cut(film, clock.t, (dialog[0] + dialog[2] / 2, dialog[1] + dialog[3] / 2, 1000),
    (dialog[0] + dialog[2] / 2, dialog[1] + dialog[3] / 2, dialog[2] + 40))
clock.wait(0.9)
walk(film, clock, [
    (R["build_source"], "LISFLOOD-FP source directory",
     "Your copy of the source, from Zenodo. The plugin compiles it with CMake, checks it and remembers it."),
    (R["build_run"], "Run, once", "A few minutes. Every model after that uses this build."),
], per=3.4)
film.caption(start, clock.t, "Once: point the plugin at LISFLOOD-FP's source, and it builds the model for you.")

# ── Open the panel ─────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Set up a model in the panel"))
film.state(start, png("04_before_panel"), crossfade=0.25)
cut(film, start, (1000, 300, 1200), (1180, 420, 700))
clock.wait(0.5)
walk(film, clock, [(R["plugin_button"], "LISFLOOD-FP",
                    "The plugin's toolbar button. It is in the Raster menu too.", "05_panel", True)], per=3.0)
walk(film, clock, [(R["binary"], "Your build, found",
                    "The panel names the executable it will use, and what it can do.",
                    None, False, None, on_panel(R["binary"]))], per=3.0)
film.caption(start, clock.t, "Open the LISFLOOD-FP panel from its toolbar button.")

# ── Domain and roughness ───────────────────────────────────────────────────
start = clock.t
walk(film, clock, [
    (R["dem"], "DEM: Appleby DTM (1 m)",
     "Any raster layer. The model grid is the DEM's own, unless you set an extent or a cell size.",
     "06_dem_open", True, "07_dem", on_panel(R["dem"])),
    (R["cellsize"], "Cell size: 5 m",
     "The 1 m DTM resampled to a 5 m model grid: 25 times fewer cells, and longer timesteps, "
     "so it runs far faster.", "07_cellsize", True, None, on_panel(R["cellsize"])),
    (R["manning"], "Manning's n: 0.06", "The default: one roughness everywhere, or a Manning's n grid for one per cell.",
     "08_manning", False, None, on_panel(R["manning"])),
], per=3.4)
film.caption(start, clock.t, "Choose the DEM, a model cell size and the roughness.")

# ── Boundaries ─────────────────────────────────────────────────────────────
start = clock.t
walk(film, clock, [
    (R["bc_points"], "Point boundaries: Inflow point",
     "Discharge in m³/s. LISFLOOD-FP wants it per metre of cell width, so the plugin converts it.",
     "09_points_open", True, "10_points", on_panel(R["bc_points"])),
    (R["auto_outflow"], "Auto outflow, 40 cells wide",
     "A free boundary where the Eden leaves the DTM, centred on its lowest edge cell.", "12_outflow", True,
     None, on_panel(R["auto_outflow"])),
], per=3.6)
film.caption(start, clock.t, "Bring the river in, and give the water a way out.")

start = clock.t
film.state(start, png("13_optional"), crossfade=0.25)
box = R["channel_box"]
cut(film, start, panel_wide(box[1] + box[3] / 2), panel_tall(box[1] + 300))
clock.wait(0.4)
walk(film, clock, [(box, "Optional: channels and rainfall",
                    "A channel network from lines, junctions found for you, and rainfall as a time series. "
                    "Here the river is already in the DTM.")], per=4.0)
film.caption(start, clock.t, "Channel networks and rainfall are there when you need them.")

# ── Run control ────────────────────────────────────────────────────────────
start = clock.t
film.state(start, png("14_sim_time"), crossfade=0.25)
cut(film, start, *on_panel(R["sim_time"]))
clock.wait(0.4)
walk(film, clock, [
    (R["sim_time"], "Simulation time: 10,800 s", "Three hours of model time.", None, True),
    (R["saveint"], "Save interval: 300 s", "A depth grid every five minutes, 37 in all.", "15_saveint", True),
    (R["solver"], "Solver: acceleration", "The local inertial solver, recommended for most floodplains."),
    (R["deck"], "Deck folder", "Where the model files and results go. A space in the path is fine.", "16_deck", True,
     None, on_panel(R["deck"])),
], per=3.0)
film.caption(start, clock.t, "Run for three hours, saving the water depth every five minutes.")

# ── Build and run ──────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Build and run"))
walk(film, clock, [(R["run_button"], "Build and run", "Writes the deck, checks it, and starts LISFLOOD-FP.",
                    None, False, None, on_panel(R["run_button"]))], per=2.6)
film.click(clock.t - 0.5)
frames = RUN["frames"]
cut(film, clock.t - 0.3, panel_wide(400), panel_tall(450), duration=0.6)
t0, length = clock.t - 0.2, 7.0
for i, (_, _, name) in enumerate(frames):
    film.state(t0 + i * length / len(frames), png(name), crossfade=0)
film.badge(t0 + 0.8, t0 + length + 0.2, mmss(RUN["elapsed"]))
film.note(t0 + 1.2, t0 + 4.4, "Live mass balance",
          "Wetted area, volume and flow in and out, read as the model writes them.", R["live"])
film.move_cursor(t0 + 0.6, t0 + 1.4, (R["live"][0] + 400, R["live"][1] + 160))
clock.wait(length)
film.state(clock.t - 0.1, png("20_done"), crossfade=0.15)
walk(film, clock, [(R["status"], "Run completed", "And all six result grids load into the project.")], per=2.4)
film.caption(start, clock.t, "Build and run: the model runs in the background, with live progress.")

# ── Results ────────────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Results, and the flood through time"))
film.state(start, png("21_max"), crossfade=0.3)
cut(film, start, WINDOW, (850, 560, 640))
clock.wait(1.6)
walk(film, clock, [
    (R["row_group"], "LISFLOOD-FP: res", "Depth through time, maximum depth, arrival time and more, georeferenced.",
     None, False, None, (None, (170, 330, 360))),
    (R["row_max"], "Maximum depth", "Blue by depth on fixed classes; dry land is left clear."),
], per=3.2)
film.caption(start, clock.t, "Untick what you don't need: here, just the maximum depth.")

start = clock.t
film.state(start, png(TIMELINE[0]), crossfade=0.3)
temporal = R["temporal"]
village = centre(R["village"])
cut(film, start, (1113, 560, 1614), (village[0], 520, 680))
clock.wait(0.6)
film.note(clock.t, clock.t + 3.2, "Temporal Controller",
          "Every saved depth grid is a band, stamped with its model time.", temporal)
# The dock reports its Play button where it was before the dock was shrunk; on screen it
# sits on the controls row, 56 px below the dock's top edge.
play = (R["play"][0], temporal[1] + 56, R["play"][2], R["play"][3])
film.move_cursor(clock.t, clock.t + 0.6, centre(play))
film.click(clock.t + 0.7)
step = 0.32
times = {state["name"]: state.get("time", "") for state in data["states"]}
readout = []
for i, name in enumerate(TIMELINE):
    film.state(clock.t + 0.4 + i * step, png(name), crossfade=0.1)
    hours, minutes = times[name].split(":")
    readout.append((clock.t + 0.4 + i * step, f"{int(hours)} h {minutes}"))
film.ticker(clock.t + 3.4, clock.t + 0.4 + len(TIMELINE) * step + 1.2, "MODEL TIME", readout)
cut(film, clock.t + 3.4, (village[0], village[1] + 80, 1150), (village[0], 515, 560), duration=6.0)
clock.wait(0.4 + len(TIMELINE) * step + 1.4)
film.caption(start, start + 0.6 + 0.4 + len(TIMELINE) * step / 2, "Step through the flood with QGIS's Temporal Controller.")
film.caption(start + 0.6 + 0.4 + len(TIMELINE) * step / 2, clock.t,
             "Within the hour, the Eden is over its banks around the meander.")

# ── Processing ─────────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Processing tools"))
film.state(start, png("30_toolbox"), crossfade=0.3)
cut(film, start, toolbox_wide(), toolbox_tall())
clock.wait(0.6)
walk(film, clock, [
    (R["alg_build"], "Build model deck", "Layers to a runnable deck. No executable needed."),
    (R["alg_run"], "Run a model deck", "Any .par file, with progress and cancel."),
    (R["alg_simulate"], "Build and run flood simulation", "Both in one step."),
    (R["alg_load"], "Load results", "Styled, time-aware layers from any run."),
], per=2.6)
film.caption(start, clock.t, "Every step is also a Processing tool: for models, batch runs and qgis_process.")

film.cursor_window = (COVER_END + 0.3, clock.t - 0.2)
film.finish(clock.t)


def stills(times):
    folder = os.path.join(HERE, "build", "stills")
    os.makedirs(folder, exist_ok=True)
    for fmt in (LANDSCAPE, VERTICAL):
        for t in times:
            film.frame(t, fmt).save(os.path.join(folder, f"{fmt.name}_{t:05.1f}.png"))
    print("stills in", folder)


if len(sys.argv) > 1:
    stills([float(t) for t in sys.argv[1:]])
else:
    film.thumbnails(os.path.join(OUT, "thumbnails"), SLUG)
    for fmt in (LANDSCAPE, VERTICAL):
        os.makedirs(os.path.join(OUT, fmt.name), exist_ok=True)
        path = os.path.join(OUT, fmt.name, f"{SLUG}.mp4")
        film.render(path, fmt)
        print("rendered", path, flush=True)
    write_chapters(os.path.join(OUT, "youtube-chapters.txt"), chapters)
print(f"duration {film.duration:.1f} s")
for t, title in chapters:
    print(mmss(t), title)
