#!/bin/sh
# Run a script in QGIS 4's Python, offscreen at 2x, with QGIS's own GDAL and PROJ.
Q="${LISFLOOD_QGIS_APP:-/Applications/QGIS-master-6ece892.app}/Contents"
unset GDAL_DRIVER_PATH PROJ_LIB
export GDAL_DATA=$Q/Resources/qgis/gdal PROJ_DATA=$Q/Resources/qgis/proj
export PATH="$Q/MacOS:$PATH" PYTHONHOME=$Q/Frameworks
export QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2
cd "$(dirname "$0")"
exec "$Q/MacOS/python3.12" -X faulthandler "$@"
