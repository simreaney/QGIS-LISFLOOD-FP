"""
End-to-end workflow tests. These need a real QGIS and a built LISFLOOD-FP binary.

    GDAL_DRIVER_PATH= PROJ_LIB=/Applications/QGIS.app/Contents/Resources/proj \
    PYTHONPATH="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins" \
    /Applications/QGIS.app/Contents/MacOS/bin/python3 test/integration/test_workflows.py

They exist because the unit tests cannot catch the failure mode that matters most:
LISFLOOD-FP applies wrong units and wrong timings without complaining. The only
reliable check is to ask for a known discharge and read back what the model reports.
"""

import os
import sys
import tempfile

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFeature,
                       QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
                       QgsVectorLayer)
from qgis.PyQt.QtCore import QVariant

QGIS_PREFIX = "/Applications/QGIS.app/Contents/MacOS"


def check(condition, message="check failed"):
    # explicit raise rather than assert, which python -O strips (and the QGIS
    # plugin validator rejects)
    if not condition:
        raise AssertionError(message)


def _start():
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    app = QgsApplication([], False)
    app.initQgis()
    sys.path.append(os.path.join(QGIS_PREFIX, "..", "Resources", "python", "plugins"))
    sys.path.append("/Applications/QGIS.app/Contents/Resources/python/plugins")
    from processing.core.Processing import Processing
    Processing.initialize()
    from lisflood_fp.provider import LisfloodProvider
    provider = LisfloodProvider()           # kept alive: the registry does not own it
    QgsApplication.processingRegistry().addProvider(provider)
    return app, provider


def _dem(work, nx, ny, cs, x0, y0, builder, epsg=27700):
    from osgeo import gdal, osr
    import numpy as np
    path = os.path.join(work, "dem.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, cs, 0, y0 + ny * cs, 0, -cs))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    xx, yy = np.meshgrid(np.arange(nx), np.arange(ny))
    ds.GetRasterBand(1).WriteArray(builder(xx, yy).astype("float32"))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds = None
    layer = QgsRasterLayer(path, "dem")
    check(layer.isValid(), "test DEM failed to load")
    return layer


def _mass(deck):
    path = os.path.join(deck, "results", "res.mass")
    with open(path) as fh:
        return [line.split() for line in fh if line.strip() and not line.startswith("Time")]


def test_point_inflow_hydrograph():
    """A 40 m3/s hydrograph must come back as 40 m3/s, not 40 x cellsize."""
    import processing
    work = tempfile.mkdtemp(prefix="lf_it_bc_")
    cs, n, x0, y0 = 10.0, 60, 400000.0, 300000.0
    dem = _dem(work, n, n, cs, x0, y0,
               lambda xx, yy: 10.0 + xx * 0.05 + abs(yy - n / 2.0) * 0.08)

    pts = QgsVectorLayer("Point?crs=EPSG:27700", "bc", "memory")
    pts.dataProvider().addAttributes([
        QgsField("bctype", QVariant.String), QgsField("value", QVariant.Double),
        QgsField("series", QVariant.String)])
    pts.updateFields()
    f = QgsFeature(pts.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x0 + 55 * cs, y0 + 30 * cs)))
    f.setAttributes(["QVAR", None, "inflow"])
    pts.dataProvider().addFeature(f)

    ts = QgsVectorLayer("None", "hydro", "memory")
    ts.dataProvider().addAttributes([
        QgsField("name", QVariant.String), QgsField("time", QVariant.Double),
        QgsField("value", QVariant.Double)])
    ts.updateFields()
    for t, q in [(0, 0.0), (600, 0.0), (900, 40.0), (2400, 40.0), (3000, 0.0), (3600, 0.0)]:
        g = QgsFeature(ts.fields()); g.setAttributes(["inflow", float(t), float(q)])
        ts.dataProvider().addFeature(g)

    for layer in (dem, pts, ts):
        QgsProject.instance().addMapLayer(layer, False)

    deck = os.path.join(work, "deck")
    processing.run("lisfloodfp:simulate", {
        "DEM": dem, "CRS": QgsCoordinateReferenceSystem("EPSG:27700"),
        "MANNING_VALUE": 0.03,
        "BOUNDARY_POINTS": pts, "BC_TYPE_FIELD": "bctype",
        "BC_VALUE_FIELD": "value", "BC_SERIES_FIELD": "series",
        "TIMESERIES": ts, "TS_NAME_FIELD": "name", "TS_TIME_FIELD": "time",
        "TS_VALUE_FIELD": "value", "TS_UNITS": 0,
        "EDGE_BOUNDARIES": ["W", str(y0), str(y0 + n * cs), "FREE", ""],
        "SIM_TIME": 3600, "SAVEINT": 300, "SOLVER": 0, "OUTPUTS": [0],
        "OUTPUT": deck})

    rows = _mass(deck)
    peak = max(float(r[6]) for r in rows)
    check(abs(peak - 40.0) < 0.01, "asked for 40 m3/s, model reports %.3f" % peak)

    # and the deck itself must carry the per-metre value, not the raw hydrograph
    bdy = open(os.path.join(deck, "bc.bdy")).read()
    check("\t4\t" in bdy.replace("\n", "\t"), "expected 40/10 = 4 m2/s in the .bdy")

    # dry before the wave arrives, wet after
    dry = [float(r[4]) for r in rows if float(r[0]) < 600]
    check(max(dry) == 0.0, "domain wetted before the hydrograph started")
    print("  point inflow: peak Qin = %.3f m3/s (asked 40) OK" % peak)


def test_channel_network_with_tributary():
    """Channel discharge is m3/s, and junctions must be found and written both ways."""
    import processing
    work = tempfile.mkdtemp(prefix="lf_it_river_")
    cs, nx, ny = 10.0, 100, 60
    dem = _dem(work, nx, ny, cs, 0.0, 0.0, lambda xx, yy: 12.0 - (xx * cs / 1000.0) * 6.0)

    rivers = QgsVectorLayer("LineString?crs=EPSG:27700", "channels", "memory")
    rivers.dataProvider().addAttributes([
        QgsField("width", QVariant.Double), QgsField("manning", QVariant.Double),
        QgsField("bed_up", QVariant.Double), QgsField("bed_dn", QVariant.Double),
        QgsField("bc_up", QVariant.String), QgsField("bc_up_value", QVariant.String),
        QgsField("bc_dn", QVariant.String), QgsField("bc_dn_value", QVariant.String)])
    rivers.updateFields()

    main = QgsFeature(rivers.fields())
    main.setGeometry(QgsGeometry.fromPolylineXY(
        [QgsPointXY(50, 300), QgsPointXY(500, 300), QgsPointXY(950, 300)]))
    main.setAttributes([20.0, 0.035, 10.0, 5.0, "QFIX", "30.0", "FREE", "-1"])
    trib = QgsFeature(rivers.fields())
    # deliberately 2 m off the main channel node: the junction must still be found
    trib.setGeometry(QgsGeometry.fromPolylineXY(
        [QgsPointXY(400, 560), QgsPointXY(460, 420), QgsPointXY(500, 302)]))
    trib.setAttributes([10.0, 0.035, 9.0, 7.5, "QFIX", "10.0", None, None])
    rivers.dataProvider().addFeatures([main, trib])

    for layer in (dem, rivers):
        QgsProject.instance().addMapLayer(layer, False)

    deck = os.path.join(work, "deck")
    processing.run("lisfloodfp:simulate", {
        "DEM": dem, "CRS": QgsCoordinateReferenceSystem("EPSG:27700"),
        "MANNING_VALUE": 0.04,
        "RIVER": rivers, "RIVER_WIDTH": "width", "RIVER_MANNING": "manning",
        "RIVER_BED_UP": "bed_up", "RIVER_BED_DN": "bed_dn",
        "RIVER_BC_UP": "bc_up", "RIVER_BC_UP_VALUE": "bc_up_value",
        "RIVER_BC_DN": "bc_dn", "RIVER_BC_DN_VALUE": "bc_dn_value",
        "SIM_TIME": 3000, "SAVEINT": 1000, "SOLVER": 0, "OUTPUTS": [0],
        "OUTPUT": deck})

    river_text = open(os.path.join(deck, "channel.river")).read()
    check("Tribs 2" in river_text)
    check("QOUT\t0" in river_text, "tributary did not declare its outlet")
    check("TRIB\t1" in river_text, "main channel did not receive the tributary")
    check("500.000000\t300.000000" in river_text, "junction was not snapped to the node")

    rows = _mass(deck)
    qin = float(rows[-1][6])
    check(abs(qin - 40.0) < 0.01,
          "channel Q is m3/s and must not be rescaled; got %.3f for 30 + 10" % qin)
    print("  channel network: Qin = %.3f m3/s (30 + 10), junction snapped OK" % qin)


if __name__ == "__main__":
    app, _provider = _start()
    failures = 0
    for test in (test_point_inflow_hydrograph, test_channel_network_with_tributary):
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print("  FAIL %s: %s" % (test.__name__, exc))
    print("integration: %s" % ("all passed" if not failures else "%d FAILED" % failures))
    app.exitQgis()
    sys.exit(1 if failures else 0)
