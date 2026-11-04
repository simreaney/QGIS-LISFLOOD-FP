"""Make the film's demo inputs: a synthetic river valley and the layers the panel reads.

Nothing here is a real place. The valley is 4.8 km by 3.2 km at 10 m: a floodplain
with a meandering channel about 30 m wide and 2.6 m deep, low levees, valley sides
rising 50 m or so, and a side valley from the north. A village sits on the edge of
the floodplain on the outside of a bend, where a flood would find it.

    ./run_qgis.sh prep_data.py

Writes build/data/: dem.tif, inflow.gpkg (the QVAR point), hydrograph.gpkg (its
series, no geometry), and river.gpkg, buildings.gpkg, roads.gpkg for the map.
The field names are the ones the panel reads without being told: bctype, value,
series on the points, and name, time, value on the table.
"""
import math
import os

import numpy as np
from osgeo import gdal, ogr, osr
from scipy import ndimage

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "build", "data")
NX, NY, CS = 480, 320, 10.0
X0, Y0 = 386000.0, 512000.0          # south-west corner, British National Grid
EPSG = 27700
rng = np.random.default_rng(11)


def smoothstep(a, b, v):
    u = np.clip((v - a) / (b - a), 0.0, 1.0)
    return u * u * (3 - 2 * u)


def noise(sigma_m, amplitude):
    field = ndimage.gaussian_filter(rng.standard_normal((NY, NX)), sigma_m / CS, mode="reflect")
    return field / field.std() * amplitude


# Distances along (x, east) and across (y, north) the valley, in metres from the corner.
x = (np.arange(NX) + 0.5) * CS
y = (NY - np.arange(NY) - 0.5) * CS              # row 0 is the north edge
X, Y = np.meshgrid(x, y)


def axis(xm):
    """The valley's centre line."""
    return 1600 + 230 * np.sin(2 * np.pi * xm / 5600 + 0.5) + 70 * np.sin(2 * np.pi * xm / 1900)


def channel(xm):
    """The river: meanders inside the floodplain, on the valley axis at both edges."""
    taper = smoothstep(150, 800, xm) * (1 - smoothstep(4000, 4650, xm))
    return axis(xm) + taper * 175 * np.sin(2 * np.pi * xm / 1250 + 0.9)


half_width = 390 + 90 * np.sin(2 * np.pi * X / 3100 + 2.0)
d = np.abs(Y - axis(X))
s = np.maximum(d - half_width, 0.0)              # distance up the valley side

z = 63.0 - 0.0017 * X + 0.0012 * d + noise(40, 0.1) + noise(160, 0.18)
z += 52 * (1 - np.exp(-(s / 480) ** 1.5))
hills = noise(600, 1.0) * 0.55 + noise(260, 1.0) * 0.3 + noise(110, 1.0) * 0.15
z += hills * 16 * (1 - np.exp(-s / 180))
# Spurs and gullies running down the valley sides, their spacing wandering.
warp = noise(400, 120.0)
z += 5.5 * np.sin(2 * np.pi * (X + warp) / 380) * smoothstep(20, 260, s) * np.exp(-s / 1400)
z += 1.0 - 2.0 * np.abs(noise(70, 1.0)) * smoothstep(40, 300, s)

# A side valley from the north, meeting the floodplain at about 2.9 km.
join = 2900.0
tx = join + 0.45 * np.maximum(Y - (axis(join) + 390), 0) + 60 * np.sin(Y / 260)
across = np.abs(X - tx)
up = np.maximum(Y - axis(X) - half_width, 0)
z -= 30 * (1 - np.exp(-up / 350)) * np.exp(-(across / 170) ** 2)

# The river, burned in by its distance from a densely sampled centre line.
cx = np.linspace(0, NX * CS, 6000)
cy = channel(cx)
mask = np.ones((NY, NX), bool)
cols = np.clip((cx / CS).astype(int), 0, NX - 1)
rows = np.clip(((NY * CS - cy) / CS).astype(int), 0, NY - 1)
mask[rows, cols] = False
dc = ndimage.distance_transform_edt(mask) * CS
z += 0.45 * np.exp(-((dc - 26) / 14) ** 2)       # low natural levees
z -= np.where(dc < 16, 2.7 * (1 - (dc / 16) ** 2), 0.0)
z = z.astype("float32")

os.makedirs(DATA, exist_ok=True)
srs = osr.SpatialReference()
srs.ImportFromEPSG(EPSG)
ds = gdal.GetDriverByName("GTiff").Create(os.path.join(DATA, "dem.tif"), NX, NY, 1, gdal.GDT_Float32,
                                          ["COMPRESS=DEFLATE"])
ds.SetGeoTransform((X0, CS, 0, Y0 + NY * CS, 0, -CS))
ds.SetProjection(srs.ExportToWkt())
band = ds.GetRasterBand(1)
band.WriteArray(z)
band.SetNoDataValue(-9999)
ds = None
print(f"DEM {z.min():.1f} to {z.max():.1f} m")


def layer(name, geometry, fields):
    path = os.path.join(DATA, f"{name}.gpkg")
    if os.path.exists(path):
        os.remove(path)
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    out = source.CreateLayer(name, srs if geometry != ogr.wkbNone else None, geometry)
    for field, kind in fields:
        out.CreateField(ogr.FieldDefn(field, kind))
    return source, out


def add(out, values, geometry=None):
    feature = ogr.Feature(out.GetLayerDefn())
    for key, value in values.items():
        feature.SetField(key, value)
    if geometry is not None:
        feature.SetGeometry(geometry)
    out.CreateFeature(feature)


def point(xm, ym):
    g = ogr.Geometry(ogr.wkbPoint)
    g.AddPoint_2D(X0 + xm, Y0 + ym)
    return g


def line(points):
    g = ogr.Geometry(ogr.wkbLineString)
    for xm, ym in points:
        g.AddPoint_2D(X0 + xm, Y0 + ym)
    return g


# The inflow: a hydrograph at the river's upstream end.
source, out = layer("inflow", ogr.wkbPoint, [("name", ogr.OFTString), ("bctype", ogr.OFTString),
                                             ("value", ogr.OFTReal), ("series", ogr.OFTString)])
add(out, {"name": "River inflow", "bctype": "QVAR", "series": "upstream"}, point(25.0, float(channel(25.0))))
source = None

source, out = layer("hydrograph", ogr.wkbNone, [("name", ogr.OFTString), ("time", ogr.OFTReal),
                                                ("value", ogr.OFTReal)])
for hours, q in [(0, 15), (0.5, 30), (1, 90), (1.5, 180), (2, 240), (2.5, 250), (3, 220),
                 (3.5, 170), (4, 120), (5, 70), (6, 45)]:
    add(out, {"name": "upstream", "time": hours * 3600.0, "value": float(q)})
source = None

source, out = layer("river", ogr.wkbLineString, [("name", ogr.OFTString)])
add(out, {"name": "River"}, line(zip(cx[::20], cy[::20])))
source = None


# A village on the outside of a bend, partly on the floodplain, and a hamlet upstream.
def ground(xm, ym):
    col = min(max(int(xm / CS), 0), NX - 1)
    row = min(max(int((NY * CS - ym) / CS), 0), NY - 1)
    return z[row, col]


def road_offset(xm, side, gap):
    return float(axis(xm) + side * (390 + 90 * math.sin(2 * math.pi * xm / 3100 + 2.0) + gap))


source, out = layer("roads", ogr.wkbLineString, [("kind", ogr.OFTString)])
xs = np.linspace(0, NX * CS, 120)
add(out, {"kind": "main"}, line([(xm, road_offset(xm, 1, 40)) for xm in xs]))
add(out, {"kind": "main"}, line([(xm, road_offset(xm, -1, 70)) for xm in xs]))
lane = [(3150 + 40 * math.sin(t * 3), road_offset(3150, 1, 40) - t * 820) for t in np.linspace(0, 1, 30)]
add(out, {"kind": "lane"}, line(lane))
add(out, {"kind": "lane"}, line([(3150 + 300 * t, road_offset(3150, 1, 40) - 260 - 30 * math.sin(t * 4))
                                 for t in np.linspace(-1, 1, 30)]))
source = None

buildings = []


def street(x_from, x_to, y_of, spacing, depth, side):
    xm = x_from
    while xm < x_to:
        w = rng.uniform(9, 16)
        h = rng.uniform(8, 12)
        set_back = rng.uniform(12, 22)
        cy_ = y_of(xm) + side * (set_back + h / 2)
        buildings.append((xm, cy_, w, h, rng.uniform(-0.12, 0.12)))
        if rng.random() < 0.35:   # a second row behind
            buildings.append((xm + rng.uniform(-4, 4), cy_ + side * (depth + h), w * 0.8, h, rng.uniform(-0.1, 0.1)))
        xm += w + spacing * rng.uniform(0.6, 1.4)


street(2850, 3650, lambda xm: road_offset(xm, 1, 40), 9, 18, -1)
street(2850, 3650, lambda xm: road_offset(xm, 1, 40), 9, 18, 1)
street(2900, 3420, lambda xm: road_offset(3150, 1, 40) - 260, 10, 16, -1)
street(1050, 1450, lambda xm: road_offset(xm, -1, 70), 14, 16, 1)

source, out = layer("buildings", ogr.wkbPolygon, [("ground", ogr.OFTReal)])
for bx, by, w, h, angle in buildings:
    ring = ogr.Geometry(ogr.wkbLinearRing)
    c, s_ = math.cos(angle), math.sin(angle)
    for px, py in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2), (-w / 2, -h / 2)]:
        ring.AddPoint_2D(X0 + bx + px * c - py * s_, Y0 + by + px * s_ + py * c)
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)
    add(out, {"ground": float(ground(bx, by))}, polygon)
source = None
print(f"{len(buildings)} buildings; inflow at {X0 + 25:.0f}, {Y0 + float(channel(25.0)):.0f}")
