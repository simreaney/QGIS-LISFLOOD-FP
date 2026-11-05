"""The direct-rainfall film: lay the captured states on one timeline and render both formats.

    ./run_qgis.sh make_rain_film.py              # out/<format>/lisflood-fp-direct-rainfall.mp4
    ./run_qgis.sh make_rain_film.py 1 40 72      # just stills at these times, in build/stills/

It opens on a slide made to be the thumbnail too: out/thumbnails/ has it at 1920 x 1080
for YouTube and 1080 x 1920 for an Instagram cover. The YouTube chapters are written
beside the films, as out/direct-rainfall-chapters.txt.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from qgis.core import QgsApplication  # noqa: E402

app = QgsApplication([], True)

import film as F  # noqa: E402
import cover as C  # noqa: E402
import style  # noqa: E402
from film import (LANDSCAPE, MUTED, VERTICAL, Clock, Cover, Film, Track, centre, cut, mmss,  # noqa: E402
                  walk, write_chapters)

CAPTURE = os.path.join(HERE, "build", "capture-rain")
OUT = os.path.join(HERE, "out")
SLUG = "lisflood-fp-direct-rainfall"

with open(os.path.join(CAPTURE, "capture.json")) as handle:
    data = json.load(handle)
F.SCALE = data["scale"]
R = data["rects"]
RUN = data["runs"]["model"]
TIMELINE = data["runs"]["timeline"]
STORM = data["runs"]["storm"]
INFO = data["runs"]["outlet"]
AREA = f"{INFO['area_km2']:.0f} km²"


def png(name):
    return os.path.join(CAPTURE, f"{name}.png")


def rain_at(seconds):
    """The storm's intensity at a model time, as LISFLOOD-FP interpolates it."""
    for (t0, v0), (t1, v1) in zip(STORM, STORM[1:]):
        if t0 <= seconds <= t1:
            return v0 + (v1 - v0) * (seconds - t0) / (t1 - t0)
    return STORM[-1][1] if seconds > STORM[-1][0] else STORM[0][1]


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


def on_map(rect, wide=None, tall=None):
    """A map rectangle, framed: the whole of it in 9:16, with a little room around."""
    cx, cy = centre(rect)
    return ((cx, cy, wide or rect[2] * 1.25), (cx, cy, tall or rect[2] * 1.08))


film = Film(
    "LISFLOOD-FP FOR QGIS  ·  DIRECT RAINFALL", "Rain on the DEM",
    "Rain on every cell of a DEM: build, run and map it without leaving QGIS.",
    end_lines=[("github.com/simreaney/QGIS-LISFLOOD-FP", F.ACCENT, 40),
               ("LISFLOOD-FP itself is not bundled: the plugin builds it from your own copy "
                "of the source (Zenodo, GPL-2.0).", MUTED, 27),
               ("DEM: the River Axe catchment, Devon and Dorset, at 20 m. The storm is made up: "
                "50 mm in three hours, with nothing lost to the ground.", MUTED, 27)])
film.capture = CAPTURE
film.title_window = (-1.0, -1.0)  # the opening slide carries the title

# ── The opening slide: the model's own flood, and what the film is ─────────
pictures = C.pictures(os.path.join(style.AXE, "dem.tif"), os.path.join(CAPTURE, "res.max"),
                               CAPTURE)
COVER_END = 4.0
cover = Cover("LISFLOOD-FP FOR QGIS", "Rain on\nthe DEM",
              "Direct rainfall flood modelling in QGIS",
              f"River Axe  ·  {AREA}  ·  20 m grid  ·  a 50 mm storm", pictures)
film.cover(0.0, COVER_END, cover)

film.state(0, png("00_project"))
catchment = R["catchment"]
film.camera("landscape", start=WINDOW)
film.camera("vertical", start=(centre(catchment)[0], centre(catchment)[1], catchment[2] * 0.62))
film.cursor = Track((1100, 640), arc=0.08)
clock = Clock(COVER_END + 0.6)
chapters = [(0.0, "A catchment DEM")]
ROWS_TALL = (165, 380, 330)  # 9:16: the top of the Layers panel, close up

# ── The DEM ────────────────────────────────────────────────────────────────
start = clock.t - 0.6
walk(film, clock, [
    (R["row_dem"], "River Axe DEM (20 m)",
     f"The catchment of the River Axe in Devon and Dorset: {AREA} of 20 m cells, no data outside it.",
     None, False, None, (None, ROWS_TALL)),
    (R["outlet"], "The outlet", f"Where the Axe leaves its catchment, {INFO['outlet_elevation']:.1f} m above sea level.",
     None, False, None, on_map(R["outlet"], 900, 560)),
], per=3.4)
film.state(clock.t, png("01_outlet"), crossfade=0.35)
edge = R["edge_close"]
cut(film, clock.t, (centre(edge)[0], centre(edge)[1] - 140, 1400), (centre(edge)[0], centre(edge)[1] - 100, 640))
clock.wait(0.8)
walk(film, clock, [(edge, "Trimmed at the outlet",
                    "LISFLOOD-FP lets water out only across the DEM's edges, and no-data cells are walls. "
                    "So this DEM ends along the outlet.")], per=4.6)
film.caption(start, clock.t, "Start with just a DEM: a whole catchment, its outlet on the edge.",
             {"landscape": "right"})  # the outlet is low on the left

# ── Set up the model ───────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Set up the model"))
film.state(start, png("04_before_panel"), crossfade=0.3)
cut(film, start, (1000, 300, 1200), (1180, 420, 700))
clock.wait(0.5)
walk(film, clock, [(R["plugin_button"], "LISFLOOD-FP", "Open the panel from the plugin's toolbar button.",
                    "05_panel", True)], per=2.8)
walk(film, clock, [
    (R["dem"], "DEM: River Axe DEM (20 m)",
     "No inflows and no channel network: the DEM is the whole model, at its own 20 m.",
     "06_dem_open", True, "07_dem", on_panel(R["dem"])),
    (R["manning"], "Manning's n: 0.06", "The default: one roughness for the whole catchment.",
     None, False, None, on_panel(R["manning"])),
], per=3.4)
cells = data["runs"]["outflow_cells"]
walk(film, clock, [(R["auto_outflow"], f"Auto outflow, up to {data['runs']['outflow']} cells",
                    f"A free boundary at the DEM's lowest edge cell: the outlet. It grows only into real "
                    f"data, so here it spans the {cells} cells ({cells * INFO['cell']:.0f} m) where the "
                    f"floodplain meets the edge.", "08_outflow", True, None, on_panel(R["auto_outflow"]))],
     per=4.4)
film.caption(start, clock.t, "Choose the DEM, and give the water a way out at the outlet.")

# ── The rain ───────────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Add the rain"))
film.state(start, png("09_rain"), crossfade=0.3)
box = R["rain_box"]
cut(film, start, panel_wide(box[1] + box[3] / 2), panel_tall(box[1] + 270))  # 9:16: above the caption
clock.wait(0.5)
walk(film, clock, [(box, "Rainfall", "A time series in mm/hr. It falls on every cell of the DEM.")], per=3.2)
rows = [("0 s: 0 mm/hr", "Dry to begin with."),
        ("5,400 s: 33 mm/hr", "The peak, an hour and a half in."),
        ("10,800 s: 0 mm/hr", "Dry again at three hours: 50 mm in all. After the last row, its value holds.")]
for i, (title, text) in enumerate(rows):
    walk(film, clock, [(R["rain_add"], "Add row", None, f"10_rain_{i}_row", True)], per=1.0, gap=0.1)
    film.state(clock.t, png(f"10_rain_{i}"), crossfade=0.12)
    walk(film, clock, [(R[f"rain_row_{i}"], title, text)], per=3.0 if i < 2 else 4.0)
film.caption(start, clock.t, "Type in a storm: 50 mm in three hours, peaking at 33 mm/hr.")

# ── Build and run ──────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Build and run"))
film.state(start, png("11_sim_time"), crossfade=0.3)
cut(film, start, *on_panel(R["sim_time"]))
clock.wait(0.4)
walk(film, clock, [
    (R["sim_time"], "Simulation time: 28,800 s", "Eight hours: the storm, and the flood draining away after it.",
     None, True),
    (R["saveint"], "Save interval: 900 s", "A depth grid every 15 minutes, 33 in all.", "12_saveint", True),
    (R["deck"], "Deck folder", "Where the model files and results go.", "13_deck", True, None, on_panel(R["deck"])),
], per=2.8)
film.caption(start, clock.t, "Run for eight hours of model time, saving the depth every 15 minutes.")
start = clock.t
walk(film, clock, [(R["run_button"], "Build and run", "Writes the deck, checks it, and starts LISFLOOD-FP.",
                    None, False, None, on_panel(R["run_button"]))], per=2.4)
film.click(clock.t - 0.5)
frames = RUN["frames"]
cut(film, clock.t - 0.3, panel_wide(400), panel_tall(450), duration=0.6)
t0, length = clock.t - 0.2, 8.0
for i, (_, _, name) in enumerate(frames):
    film.state(t0 + i * length / len(frames), png(name), crossfade=0)
film.badge(t0 + 0.8, t0 + length + 0.2, mmss(RUN["elapsed"]))
film.note(t0 + 1.2, t0 + 5.2, "Live mass balance",
          "Wetted area, the water on the catchment, and Qout: the flood leaving at the outlet.", R["live"])
film.move_cursor(t0 + 0.6, t0 + 1.4, (R["live"][0] + 400, R["live"][1] + 160))
clock.wait(length)
film.state(clock.t - 0.1, png("20_done"), crossfade=0.15)
walk(film, clock, [(R["status"], "Run completed", "And the result grids load into the project.")], per=2.4)
film.caption(start, clock.t, f"Eight hours of flood on {INFO['cells'] / 1000:.0f},000 cells, "
                             f"in {RUN['elapsed'] / 60:.0f} minutes of real time.")
start = clock.t
group_rows = F.union(R["row_group"], R["row_wd"])  # the group and its six layers
walk(film, clock, [(group_rows, "LISFLOOD-FP: res",
                    "Depth through time, maximum depth and the time grids, georeferenced. All six load "
                    "switched on: untick the ones you don't need.", None, False, None,
                    ((700, 420, 1400), (175, group_rows[1] + 230, 350)))], per=4.2)
film.caption(start, clock.t, "Keep the water depth through time: one layer, a band for every saved grid.")

# ── Through time ───────────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "The flood through time"))
film.state(start, png(TIMELINE[0]), crossfade=0.3)
temporal = R["temporal"]
wide = R["catchment_wide"]
cut(film, start, WINDOW, (centre(wide)[0], centre(wide)[1] + 40, wide[2] * 0.66))
clock.wait(0.6)
film.note(clock.t, clock.t + 3.0, "Temporal Controller",
          "Every saved depth grid is a band, stamped with its model time.", temporal)
# The dock reports its Play button where it was before the dock was shrunk; on screen it
# sits on the controls row, 56 px below the dock's top edge.
play = (R["play"][0], temporal[1] + 56, R["play"][2], R["play"][3])
film.move_cursor(clock.t, clock.t + 0.6, centre(play))
film.click(clock.t + 0.7)
step = 0.42
states = {state["name"]: state for state in data["states"]}
clock_steps, rain_steps = [], []
for i, name in enumerate(TIMELINE):
    at = clock.t + 0.4 + i * step
    film.state(at, png(name), crossfade=0.12)
    minutes = states[name]["minutes"]
    clock_steps.append((at, f"{int(minutes // 60)} h {int(minutes % 60):02d}"))
    rain_steps.append((at, f"{rain_at(minutes * 60):.0f} mm/hr"))
end = clock.t + 0.4 + len(TIMELINE) * step + 1.2
film.ticker(clock.t + 3.2, end, "MODEL TIME", clock_steps)
film.ticker(clock.t + 3.2, end, "RAIN", rain_steps, slot=1)
outlet = R["outlet_wide"]
cut(film, clock.t + 3.2, (centre(wide)[0], centre(wide)[1] + 30, wide[2] * 1.06), None, duration=1.2)
cut(film, clock.t + 0.4 + 15 * step, (centre(outlet)[0] + 160, centre(outlet)[1] - 260, 1100),
    (centre(outlet)[0] + 90, centre(outlet)[1] - 300, 560), duration=4.0)
clock.wait(0.4 + len(TIMELINE) * step + 1.4)
film.caption(start, start + 0.6 + 0.4 + 14 * step,
             "Rain falls on every cell, runs off the hillslopes and finds the river network.")
film.caption(start + 0.6 + 0.4 + 14 * step, clock.t,
             "After the storm, the flood drains down the valley to the outlet.")

# ── The deepest water ──────────────────────────────────────────────────────
start = clock.t
chapters.append((start, "Maximum depth"))
film.state(start, png("30_max"), crossfade=0.35)
canvas = R["canvas_max"]
cut(film, start, WINDOW, (centre(canvas)[0] + 60, centre(canvas)[1], 720))
clock.wait(1.0)
walk(film, clock, [(R["row_max"], "Maximum depth",
                    "The deepest water anywhere in the run, from Axminster down to the outlet. The pale blue "
                    "on the slopes is sheet flow: rain on every cell wets them all.",
                    None, False, None, (None, ROWS_TALL))], per=4.6)
cut(film, clock.t, None, (centre(canvas)[0] + 60, centre(canvas)[1], 720))
clock.wait(2.4)
film.caption(start, clock.t, "Each result is a styled, georeferenced layer, ready to map and measure.")

film.cursor_window = (COVER_END + 0.3, clock.t - 0.2)
film.finish(clock.t)


def stills(times):
    folder = os.path.join(HERE, "build", "stills")
    os.makedirs(folder, exist_ok=True)
    for fmt in (LANDSCAPE, VERTICAL):
        for t in times:
            film.frame(t, fmt).save(os.path.join(folder, f"rain_{fmt.name}_{t:05.1f}.png"))
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
    write_chapters(os.path.join(OUT, "direct-rainfall-chapters.txt"), chapters)
print(f"duration {film.duration:.1f} s")
for t, title in chapters:
    print(mmss(t), title)
