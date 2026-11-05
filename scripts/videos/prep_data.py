"""The walkthrough's data: the Appleby 1 m DTM and an inflow point on the River Eden.

    ./run_qgis.sh prep_data.py [path to the DTM]

The DTM (LISFLOOD_APPLEBY_DEM) is an ESRI ASCII grid on the British National Grid,
1.6 by 1.4 km of Appleby-in-Westmorland at 1 m. It is written as a GeoTIFF with its
CRS and overviews, so QGIS draws it quickly. The Eden enters across the DTM's
southern edge and leaves across its northern edge; the inflow point goes on the
channel just inside the southern edge, with a steady 150 m3/s (bctype QFIX). Flood
defences are not in the DTM, so the model does not represent them.
Writes build/appleby/dem.tif, inflow.gpkg and info.json.
"""
import json
import os
import sys

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build", "appleby")
SOURCE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LISFLOOD_APPLEBY_DEM")
INFLOW = 150.0  # m3/s, steady
if not SOURCE or not os.path.exists(SOURCE):
    sys.exit("Set LISFLOOD_APPLEBY_DEM to the Appleby 1 m DTM (appleby 1m dtm.asc).")

source = gdal.Open(SOURCE)
z = source.GetRasterBand(1).ReadAsArray().astype(float)
x0, cell, _, y0, _, _ = source.GetGeoTransform()
rows, cols = z.shape
bng = osr.SpatialReference()
bng.ImportFromEPSG(27700)

os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, "dem.tif")
gdal.Translate(path, source, outputSRS=bng.ExportToWkt(), noData=-9999,
               creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=3"])
dem = gdal.Open(path, gdal.GA_Update)
dem.BuildOverviews("AVERAGE", [2, 4, 8, 16])
dem = None

# Where the Eden comes in: the lowest point of the southern edge, then the channel's
# lowest cell a few metres in, so the point sits in the river rather than on the bank.
edge_col = int(np.argmin(z[-1]))
band = z[rows - 25:rows - 10, max(0, edge_col - 30):edge_col + 30]
r, c = np.unravel_index(np.argmin(band), band.shape)
row, col = rows - 25 + r, max(0, edge_col - 30) + c
x, y = x0 + (col + 0.5) * cell, y0 - (row + 0.5) * cell

points = os.path.join(OUT, "inflow.gpkg")
if os.path.exists(points):
    os.remove(points)
ds = ogr.GetDriverByName("GPKG").CreateDataSource(points)
layer = ds.CreateLayer("inflow", bng, ogr.wkbPoint)
for name, kind in (("name", ogr.OFTString), ("bctype", ogr.OFTString), ("value", ogr.OFTReal)):
    layer.CreateField(ogr.FieldDefn(name, kind))
feature = ogr.Feature(layer.GetLayerDefn())
feature.SetField("name", "River Eden")
feature.SetField("bctype", "QFIX")
feature.SetField("value", INFLOW)
feature.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT ({x} {y})"))
layer.CreateFeature(feature)
ds = None

info = {"source": os.path.basename(SOURCE), "cell": cell, "rows": rows, "cols": cols,
        "extent": [x0, y0 - rows * cell, x0 + cols * cell, y0],
        "elevation": [float(z.min()), float(z.max())],
        "inflow": [x, y], "inflow_m3s": INFLOW, "inflow_bed": float(z[row, col])}
with open(os.path.join(OUT, "info.json"), "w") as handle:
    json.dump(info, handle, indent=1)
print(json.dumps(info, indent=1))
