#!/bin/sh
# Rebuild the walkthrough: make the demo valley (once), capture the real QGIS states,
# render both formats into out/.
set -e
cd "$(dirname "$0")"
[ -f build/data/dem.tif ] || ./run_qgis.sh prep_data.py
rm -rf build/capture
# QGIS can crash on exit after saving, so trust capture.json, not the exit status.
python3 run_app.py drive.py build/capture 900 || true
python3 -c "import json, sys; sys.exit('timeline' not in json.load(open('build/capture/capture.json'))['runs'])" \
  || { echo "capture incomplete: see the log in build/capture/capture.json"; exit 1; }
./run_qgis.sh make_film.py
