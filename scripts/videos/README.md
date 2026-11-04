# LISFLOOD-FP for QGIS: the walkthrough film

One silent, captioned walkthrough of the plugin in two formats: 16:9 in 4K for
YouTube (`out/landscape/`) and 9:16 at 1080 × 1920 for Instagram Reels
(`out/vertical/`). `youtube-description.txt` is the YouTube description; the
chapters in it come from `out/youtube-chapters.txt`, which the render writes.

Nothing on screen is mocked up. `drive.py` runs inside the real QGIS 4 application,
offscreen at 4x with a throwaway profile that has this checkout installed as the
plugin. It loads the demo valley, opens the panel from its toolbar button, fills in
the Model tab, builds and runs the model with the LISFLOOD-FP you have built
(`~/.lisflood-fp/build/lisflood`), loads the results and steps the Temporal
Controller through the flood, grabbing each state. `make_film.py` then adds what a
screen recorder would: the camera, cursor, highlights, captions, callouts, the
run-time badge and the cards. The compositor, `film.py`, is adapted from the SCIMAP
for QGIS films.

## Running it

```sh
./make_video.sh
```

It needs QGIS 4 (`LISFLOOD_QGIS_APP`, default `/Applications/QGIS-master-6ece892.app`, a 4.3 build),
a built LISFLOOD-FP, ffmpeg with libx264, and a `python3` with Pillow for
`run_app.py`. The capture takes about a minute and a half; rendering, mostly the 4K
encode, takes longer.

| File | What it does |
|---|---|
| `prep_data.py` | The synthetic valley: a 10 m DEM, the inflow point and its hydrograph, the river, roads and buildings. |
| `style.py` | The demo layers and their map styles. |
| `run_app.py` | Starts QGIS offscreen with the throwaway profile. |
| `drive.py` | Drives QGIS and the plugin; writes `build/capture/`. |
| `film.py` | Lays out and renders a film: camera, cursor, notes, captions, cards. |
| `make_film.py` | The walkthrough's timeline; renders both formats. |
| `run_qgis.sh` | Runs a script in QGIS's own Python (GDAL, PROJ, PyQt). |
| `youtube-description.txt` | The YouTube description, chapters included. Update the chapters if the timeline changes. |

## Things to know

- **macOS 27.2 and QGIS 4.2.3.** QGIS 4.2.3 dies at start-up making its Dock icon:
  CoreGraphics now rejects the colour space Qt builds from the icon's sRGB tag. The
  4.3 master build starts normally. To film with 4.2.3, set
  `LISFLOOD_ICON_WORKAROUND=1`: `run_app.py` then sets `QGIS_PREFIX_PATH` to a tree
  of links to the app in which only that icon is replaced by an untagged copy. The
  app itself is not touched.
- **QGIS 4.3 renamed the Processing Toolbox dock**, so `drive.py` finds docks by
  their title as well as their object name.
- **Respect screen DPI is off** in the throwaway profile. Offscreen, QGIS invents a
  physical DPI (25 at 4x) and every map symbol shrinks.
- **The deck is written to `/Users/Shared/LISFLOOD-FP demo/valley-flood`**, a
  short path with no home folder in it, since it shows on screen. The space is
  deliberate: the plugin should cope with it, and does.
- **The capture is at 4x** (7680 × 4320 per state) so the 4K film can zoom to 2x
  and stay sharp.
