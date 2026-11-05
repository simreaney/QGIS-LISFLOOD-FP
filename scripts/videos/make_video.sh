#!/bin/sh
# Rebuild a film: make its data (once), capture the real QGIS states, render both formats into out/.
#   ./make_video.sh              the walkthrough, on the Appleby DTM (see prep_data.py)
#   ./make_video.sh rain         direct rainfall on the River Axe DEM (see rain_prep.py)
set -e
cd "$(dirname "$0")"
case "${1:-walkthrough}" in
  walkthrough) data=build/appleby/dem.tif prep=prep_data.py drive=drive.py capture=build/capture
               film=make_film.py deck=appleby timeout=900 ;;
  rain)        data=build/axe/dem.tif prep=rain_prep.py drive=drive_rain.py capture=build/capture-rain
               film=make_rain_film.py deck=axe-rain timeout=1800 ;;
  *) echo "usage: $0 [walkthrough|rain]"; exit 2 ;;
esac
[ -f "$data" ] || ./run_qgis.sh "$prep"
rm -rf "$capture"
# QGIS can crash on exit after saving, so trust capture.json, not the exit status.
python3 run_app.py "$drive" "$capture" "$timeout" || true
python3 -c "import json, sys; sys.exit('timeline' not in json.load(open(sys.argv[1]))['runs'])" "$capture/capture.json" \
  || { echo "capture incomplete: see the log in $capture/capture.json"; exit 1; }
rm -rf "/Users/Shared/LISFLOOD-FP demo/$deck"  # the film works from its capture
./run_qgis.sh "$film"
