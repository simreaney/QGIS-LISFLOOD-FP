# LISFLOOD-FP for QGIS: the films

Silent, captioned films of the plugin, each in two formats: 16:9 in 4K for YouTube
(`out/landscape/`) and 9:16 at 1080 × 1920 for Instagram Reels (`out/vertical/`).

- **The walkthrough** (`lisflood-fp-for-qgis-walkthrough.mp4`): the whole plugin, from
  building LISFLOOD-FP to the Processing tools, on a 1 m DTM of Appleby-in-Westmorland
  run at 5 m, with a steady 150 m³/s coming down the River Eden. Flood defences are not
  represented, and the film says so. `youtube-description.txt` is its YouTube
  description; the chapters in it come from `out/youtube-chapters.txt`, which the
  render writes.
- **Direct rainfall** (`lisflood-fp-direct-rainfall.mp4`): rain on every cell of the
  River Axe catchment's DEM, with no inflows at all. Its chapters are in
  `out/direct-rainfall-chapters.txt`.

Each opens on a slide made to be the thumbnail as well, drawn from the film's own
model run: `out/thumbnails/` has it at 1920 × 1080 for YouTube and 1080 × 1920 for an
Instagram cover.

Nothing on screen is mocked up. The capture scripts (`drive.py`, `drive_rain.py`) run
inside the real QGIS 4 application, offscreen at 4x with a throwaway profile that has
this checkout installed as the plugin. They open the panel from its toolbar button,
fill in the Model tab, build and run the model with the LISFLOOD-FP you have built
(`~/.lisflood-fp/build/lisflood`), load the results and step the Temporal Controller
through the flood, grabbing each state. The film scripts (`make_film.py`,
`make_rain_film.py`) then add what a screen recorder would: the camera, cursor,
highlights, captions, callouts, the run-time badge and the cards. The compositor,
`film.py`, is adapted from the SCIMAP for QGIS films.

## Running it

```sh
./make_video.sh          # the walkthrough
./make_video.sh rain     # direct rainfall
```

It needs QGIS 4 (`LISFLOOD_QGIS_APP`, default `/Applications/QGIS-master-6ece892.app`,
a 4.3 build), a built LISFLOOD-FP, ffmpeg with libx264, and a `python3` with Pillow for
`run_app.py`. Each film needs its DEM the first time it is made: the walkthrough the
Appleby 1 m DTM (`LISFLOOD_APPLEBY_DEM`, an ESRI ASCII grid), the rainfall film the
River Axe DEM (`LISFLOOD_AXE_DEM`, default `~/Desktop/Axe20/AxeDEM20_COG.tif`).

The walkthrough's capture takes about two and a half minutes. The rainfall film's takes
about ten minutes, most of it the model run itself. Rendering, mostly the 4K encode,
takes longer.

| File | What it does |
|---|---|
| `prep_data.py` | The walkthrough's data: the Appleby DTM as a GeoTIFF, and the inflow point on the Eden. |
| `rain_prep.py` | The River Axe DEM, trimmed so its outlet is on its southern edge. |
| `style.py` | The demo layers and their map styles. |
| `run_app.py` | Starts QGIS offscreen with the throwaway profile. |
| `capture.py` | What the capture scripts share: grabbing the window, noting where controls are, pacing. |
| `drive.py` | Drives QGIS and the plugin for the walkthrough; writes `build/capture/`. |
| `drive_rain.py` | The same for direct rainfall; writes `build/capture-rain/`. |
| `film.py` | Lays out and renders a film: camera, cursor, notes, captions, cards, opening slide. |
| `make_film.py` | The walkthrough's timeline; renders both formats. |
| `make_rain_film.py` | The direct-rainfall timeline; renders both formats and the thumbnails. |
| `cover.py` | The opening slides' pictures: each run's maximum depth, drawn by QGIS. |
| `run_qgis.sh` | Runs a script in QGIS's own Python (GDAL, PROJ, PyQt). |
| `youtube-description.txt` | The walkthrough's YouTube description, chapters included. Update the chapters if the timeline changes. |

## Things to know

- **macOS 27.2 and QGIS 4.2.3.** QGIS 4.2.3 dies at start-up making its Dock icon:
  CoreGraphics now rejects the colour space Qt builds from the icon's sRGB tag. The
  4.3 master build starts normally. To film with 4.2.3, set
  `LISFLOOD_ICON_WORKAROUND=1`: `run_app.py` then sets `QGIS_PREFIX_PATH` to a tree
  of links to the app in which only that icon is replaced by an untagged copy. The
  app itself is not touched.
- **QGIS 4.3 renamed the Processing Toolbox dock**, so `capture.py` finds docks by
  their title as well as their object name.
- **Respect screen DPI is off** in the throwaway profile. Offscreen, QGIS invents a
  physical DPI (25 at 4x) and every map symbol shrinks.
- **The decks are written to `/Users/Shared/LISFLOOD-FP demo/`**, a short path with
  no home folder in it, since it shows on screen. The space is deliberate: the plugin
  should cope with it, and does. `make_video.sh` deletes each deck once its capture is
  done; the rainfall film's is several hundred megabytes.
- **The capture is at 4x** (7680 × 4320 per state) so the 4K film can zoom to 2x
  and stay sharp. Saving one of those over the 1 m DTM takes seconds, so during the
  walkthrough's short run only the panel is grabbed, and pasted onto a whole-window
  grab afterwards.
- **The walkthrough's model grid is 5 m**, set with the panel's cell size: at the
  DTM's own 1 m the run would take far longer than the film can wait.
- **The Axe DEM is trimmed at its outlet.** It is clipped to the catchment, and
  LISFLOOD-FP treats no-data cells as walls and lets water out only across the DEM's
  four edges, so with the outlet inside the raster the water would have nowhere to
  go. `rain_prep.py` drops the rows below the outlet (about 1% of the catchment), and
  the plugin's auto outflow then finds the outlet as the lowest edge cell.
