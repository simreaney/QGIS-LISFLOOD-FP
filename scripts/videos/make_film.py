"""The walkthrough: lay the captured states on one timeline and render both formats.

    ./run_qgis.sh make_film.py              # out/landscape/*.mp4 (4K) and out/vertical/*.mp4
    ./run_qgis.sh make_film.py 12.5 40      # just stills at these times, in build/stills/

Captions carry the story, since the film has no sound; the callouts name each
control as the cursor reaches it. The YouTube chapters are written beside the films.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], True)

import film as F  # noqa: E402
from film import LANDSCAPE, MUTED, VERTICAL, Film, Track, centre, mmss  # noqa: E402

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


def left_part(rect, inset=14):
    x, y, w, h = rect
    return (x + inset, y + h / 2)


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def wait(self, seconds):
        self.t += seconds
        return self.t


def cut(film, t, landscape=None, vertical=None, duration=0.8):
    if landscape is not None:
        film.camera("landscape", moves=[(t, t + duration, landscape)])
    if vertical is not None:
        film.camera("vertical", moves=[(t, t + duration, vertical)])


def walk(film, clock, items, per=3.0, gap=0.2):
    """Point at each control, box it and say what it is; click it if asked.

    Each item is (rect, title, text) and optionally the state shown once it is
    reached (or clicked), whether it is clicked, a state that follows, and the
    (16:9, 9:16) framings to move to as it is reached (either may be None).
    """
    for item in items:
        rect, title, text = item[:3]
        state = item[3] if len(item) > 3 else None
        click = item[4] if len(item) > 4 else False
        after = item[5] if len(item) > 5 else None
        views = item[6] if len(item) > 6 else (None, None)
        t = clock.t
        cut(film, t - 0.3, *views)
        film.move_cursor(t, t + 0.5, left_part(rect, min(18, rect[2] / 2)) if rect[2] > 300 else centre(rect))
        if click:
            film.click(t + 0.55)
        if state:
            film.state(t + (0.62 if click else 0.1), png(state), crossfade=0.12)
        if after:
            film.state(t + 1.7, png(after), crossfade=0.15)
        film.highlight(t + 0.45, t + per, rect, pad=3)
        film.note(t + 0.5, t + per, title, text, rect)
        clock.wait(per + gap)


film = Film(
    "LISFLOOD-FP FOR QGIS  ·  WALKTHROUGH", "Flood modelling in QGIS",
    "Build, run and map LISFLOOD-FP flood models without leaving QGIS.",
    end_lines=[("github.com/simreaney/QGIS-LISFLOOD-FP", F.ACCENT, 40),
               ("LISFLOOD-FP itself is not bundled: the plugin builds it from your own copy "
                "of the source (Zenodo, GPL-2.0).", MUTED, 27),
               ("The valley in this film is synthetic, made for the demonstration.", MUTED, 27)])
film.state(0, png("00_project"))
film.camera("landscape", start=WINDOW)
film.camera("vertical", start=(1113, 572, 640))
film.cursor = Track((900, 700), arc=0.08)
clock = Clock(3.2)
chapters = [(0.0, "The inputs")]
ROWS_TALL = (165, 380, 330)  # 9:16: the top of the Layers panel, close up

# ── The inputs ─────────────────────────────────────────────────────────────
start = clock.t
cut(film, start - 0.4, (700, 500, 1400))
table = R["table"]
walk(film, clock, [
    (R["row_dem"], "DEM (10 m)", "A synthetic valley made for this film: 4.8 by 3.2 km, a river channel cut into it.",
     None, False, None, (None, ROWS_TALL)),
    (R["row_inflow"], "Inflow point", "Where the river enters. Its fields say QVAR, a varying inflow, and name its series."),
    (R["inflow_point"], "River inflow", "At the upstream end of the channel.",
     None, False, None, (None, (480, 560, 420))),
    (R["row_hydro"], "Inflow hydrograph", "A table with no geometry: series name, time in seconds, discharge in m³/s.",
     None, True, "01_table", (None, ROWS_TALL)),
], per=3.0)
walk(film, clock, [(table, "The hydrograph", "From 15 m³/s up to 250 m³/s at two and a half hours, then falling.",
                    None, False, None, (None, (table[0] + table[2] / 2, table[1] + 300, table[2] + 50)))],
     per=3.4)
film.state(clock.t - 0.1, png("00_project"), crossfade=0.2)
film.caption(start, clock.t, "Start with ordinary QGIS layers: a DEM, an inflow point and its hydrograph.")

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
    (R["dem"], "DEM", "Any raster layer. The model grid is the DEM's own, unless you set an extent or cell size.",
     "06_dem_open", True, "07_dem", on_panel(R["dem"])),
    (R["manning"], "Manning's n: 0.040", "One roughness for the whole valley, or a Manning's n grid for one per cell.",
     "08_manning", True, None, on_panel(R["manning"])),
], per=3.4)
film.caption(start, clock.t, "Choose the DEM and set the roughness.")

# ── Boundaries ─────────────────────────────────────────────────────────────
start = clock.t
walk(film, clock, [
    (R["bc_points"], "Point boundaries: Inflow point", "Its bctype, value and series fields say what each point is.",
     "09_points_open", True, "10_points", on_panel(R["bc_points"])),
    (R["ts_table"], "Time series table: Inflow hydrograph",
     "In m³/s. LISFLOOD-FP wants discharge per metre of cell width, so the plugin converts it.", "11_series", True,
     None, on_panel(R["ts_table"])),
    (R["auto_outflow"], "Auto outflow, 80 cells wide",
     "A free boundary where the valley leaves the DEM, centred on its lowest edge cell.", "12_outflow", True,
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
                    "This valley's river is already in the DEM.")], per=4.0)
film.caption(start, clock.t, "Channel networks and rainfall are there when you need them.")

# ── Run control ────────────────────────────────────────────────────────────
start = clock.t
film.state(start, png("14_sim_time"), crossfade=0.25)
cut(film, start, *on_panel(R["sim_time"]))
clock.wait(0.4)
walk(film, clock, [
    (R["sim_time"], "Simulation time: 21,600 s", "Six hours of model time.", None, True),
    (R["saveint"], "Save interval: 600 s", "A depth grid every ten minutes, 37 in all.", "15_saveint", True),
    (R["solver"], "Solver: acceleration", "The local inertial solver, recommended for most floodplains."),
    (R["deck"], "Deck folder", "Where the model files and results go. A space in the path is fine.", "16_deck", True,
     None, on_panel(R["deck"])),
], per=3.0)
film.caption(start, clock.t, "Run for six hours, saving the water depth every ten minutes.")

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
film.caption(start, clock.t, "Step through the flood with QGIS's Temporal Controller.")

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

film.cursor_window = (3.4, clock.t - 0.2)
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
    for fmt in (LANDSCAPE, VERTICAL):
        os.makedirs(os.path.join(OUT, fmt.name), exist_ok=True)
        path = os.path.join(OUT, fmt.name, f"{SLUG}.mp4")
        film.render(path, fmt)
        print("rendered", path, flush=True)
    with open(os.path.join(OUT, "youtube-chapters.txt"), "w") as handle:
        for t, title in chapters:
            handle.write(f"{mmss(t)} {title}\n")
print(f"duration {film.duration:.1f} s")
for t, title in chapters:
    print(mmss(t), title)
