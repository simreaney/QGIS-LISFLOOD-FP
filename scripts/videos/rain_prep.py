"""The direct-rainfall film's DEM: the River Axe catchment, trimmed so its outlet is on the edge.

    ./run_qgis.sh rain_prep.py [path to the Axe DEM]

The DEM (LISFLOOD_AXE_DEM, default ~/Desktop/Axe20/AxeDEM20_COG.tif) is clipped to the
catchment, with no data outside it. LISFLOOD-FP treats no-data cells as walls and lets
water out only across the DEM's four edges, but this catchment's outlet is inside the
raster, so the water would have nowhere to go. Trimming the rows below the outlet puts
it on the southern edge, where the plugin's auto outflow finds it: the lowest edge cell.
Writes build/axe/dem.tif and build/axe/outlet.json.
"""
import json
import os
import sys

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build", "axe")
SOURCE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "LISFLOOD_AXE_DEM", os.path.expanduser("~/Desktop/Axe20/AxeDEM20_COG.tif"))

source = gdal.Open(SOURCE)
band = source.GetRasterBand(1)
z = band.ReadAsArray().astype(float)
nodata = band.GetNoDataValue()
valid = z != nodata if nodata is not None else np.isfinite(z)
x0, cell, _, y0, _, _ = source.GetGeoTransform()

# The outlet: the catchment's lowest cell. It must be in the southern part for a trim
# along the bottom to work; another catchment would need its own side.
row, col = np.unravel_index(np.where(valid, z, np.inf).argmin(), z.shape)
if row < 0.8 * z.shape[0]:
    sys.exit(f"the lowest cell is at row {row} of {z.shape[0]}: not near the southern edge")
kept = valid[:row + 1].sum()
os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, "dem.tif")
gdal.Translate(path, source, srcWin=[0, 0, z.shape[1], row + 1],
               creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"])
trimmed = gdal.Open(path, gdal.GA_Update)
trimmed.BuildOverviews("AVERAGE", [2, 4, 8])  # quick to draw zoomed out
trimmed = None
edge = valid[row]
lo = hi = col  # the stretch of real data along the new edge that the outlet is in
while lo > 0 and edge[lo - 1]:
    lo -= 1
while hi < len(edge) - 1 and edge[hi + 1]:
    hi += 1
info = {
    "source": os.path.basename(SOURCE),
    "outlet": [x0 + (col + 0.5) * cell, y0 - (row + 0.5) * cell],
    "outlet_elevation": float(z[row, col]),
    "cell": cell,
    "rows": int(row + 1), "cols": int(z.shape[1]),
    "cells": int(kept), "area_km2": float(kept * cell * cell / 1e6),
    "dropped_cells": int(valid.sum() - kept),
    "edge_cells": int(edge.sum()),
    "outlet_run": [x0 + lo * cell, x0 + (hi + 1) * cell],
}
with open(os.path.join(OUT, "outlet.json"), "w") as handle:
    json.dump(info, handle, indent=1)
print(json.dumps(info, indent=1))
