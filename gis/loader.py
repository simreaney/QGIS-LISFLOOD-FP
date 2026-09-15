"""
Model output -> styled, georeferenced QGIS layers.

Three things need care.

**No CRS.** LISFLOOD-FP never writes a .prj, so every output loads as CRS-less. The
plugin writes sidecars *and* sets the CRS on the layer. The sidecars are cheap: GDAL
finds them by swapping the extension, so one `res-0001.prj` serves `res-0001.wd`,
`.elev`, `.Qx` and `.Qy` at once.

**Depth grids have no nodata.** `write_ascfile` writes `H` for every cell, so dry land
is a literal 0.000 and the declared `NODATA_value -9999` never appears in a `.wd`.
Without an explicit transparency range the whole domain renders as solid blue. By
contrast `.elev`/`.mxe` *are* masked with -9999, so they need the opposite treatment.

**Flux grids are edge-centred and already offset.** `.Qx` carries ncols+1 and an
origin shifted by -dx/2; the model applies that when writing, so the file is correct
as delivered. Shifting it again on load is the bug.
"""

import os

from qgis.core import (QgsRasterLayer, QgsProject, QgsDateTimeRange,
                       QgsColorRampShader, QgsRasterShader, QgsRasterTransparency,
                       QgsSingleBandPseudoColorRenderer, QgsInterval)
from qgis.PyQt.QtCore import QDateTime, QDate, QTime
from qgis.PyQt.QtGui import QColor

from ..core import gridio, results as R
from ..qt_compat import crs_to_esri_wkt, raster_temporal_mode, temporal_unit_seconds

#: depth classes in metres, with colours. Fixed, never a per-layer stretch: a stretch
#: makes a spreading flood look like it is shrinking as the maximum rises.
DEPTH_CLASSES = [
    (0.05, "#d6ecfa"), (0.10, "#abd9f0"), (0.25, "#74b8e3"),
    (0.50, "#4292c6"), (1.00, "#2166ac"), (2.00, "#15497d"), (5.00, "#0b2a4f"),
]
ELEV_RAMP = [(0.0, "#f7fbff"), (1.0, "#08306b")]


def _shader(classes, minv=None, maxv=None):
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    items = []
    for value, colour in classes:
        items.append(QgsColorRampShader.ColorRampItem(
            value, QColor(colour), "%g" % value))
    ramp.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    return shader


def style_depth(layer, min_depth=0.01):
    """Blue depth ramp with everything below `min_depth` fully transparent."""
    renderer = QgsSingleBandPseudoColorRenderer(
        layer.dataProvider(), 1, _shader(DEPTH_CLASSES))
    transparency = QgsRasterTransparency()
    entry = QgsRasterTransparency.TransparentSingleValuePixel()
    # cover the dry 0.000 cells and anything below the display threshold
    try:
        entry.min = -0.001
        entry.max = float(min_depth)
        entry.percentTransparent = 100.0
    except AttributeError:          # Qt6/QGIS4 spelling
        entry.setMin(-0.001)
        entry.setMax(float(min_depth))
        entry.setPercentTransparent(100.0)
    transparency.setTransparentSingleValuePixelList([entry])
    renderer.setRasterTransparency(transparency)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return layer


def style_elevation(layer):
    """`.elev`/`.mxe` are already masked with -9999, so nodata alone is enough."""
    prov = layer.dataProvider()
    prov.setNoDataValue(1, gridio.NODATA)
    stats = prov.bandStatistics(1)
    lo, hi = stats.minimumValue, stats.maximumValue
    if hi <= lo:
        hi = lo + 1.0
    classes = [(lo + f * (hi - lo), c) for f, c in ELEV_RAMP]
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(prov, 1, _shader(classes)))
    layer.triggerRepaint()
    return layer


def load_raster(path, name, crs=None, kind="depth", min_depth=0.01, write_prj=True):
    """Load one model grid as a styled, georeferenced layer."""
    if write_prj and crs is not None:
        prj = os.path.splitext(path)[0] + ".prj"
        if not os.path.exists(prj):
            gridio.write_prj(prj, crs_to_esri_wkt(crs))
    layer = QgsRasterLayer(path, name, "gdal")
    if not layer.isValid():
        return None
    if crs is not None:
        layer.setCrs(crs)
    if kind == "depth":
        style_depth(layer, min_depth)
    elif kind == "elev":
        style_elevation(layer)
    else:
        layer.dataProvider().setNoDataValue(1, gridio.NODATA)
    return layer


def _t0(start_datetime=None):
    if start_datetime is not None:
        return start_datetime
    return QDateTime(QDate(2000, 1, 1), QTime(0, 0, 0))


def build_series_vrt(paths, vrt_path):
    """Stack a -NNNN series into one multiband VRT.

    One layer with one style and one legend entry beats N layers with N of each, and
    it is what makes the temporal controller usable.
    """
    from osgeo import gdal
    gdal.BuildVRT(vrt_path, list(paths), separate=True)
    return vrt_path if os.path.exists(vrt_path) else None


def load_series(paths, name, crs, saveint, kind="depth",
                min_depth=0.01, start_datetime=None, vrt_dir=None):
    """Load a -NNNN raster series as a single temporal multiband layer."""
    if not paths:
        return None
    if crs is not None:
        for p in paths:
            prj = os.path.splitext(p)[0] + ".prj"
            if not os.path.exists(prj):
                gridio.write_prj(prj, crs_to_esri_wkt(crs))
    vrt_dir = vrt_dir or os.path.dirname(paths[0])
    vrt = build_series_vrt(paths, os.path.join(vrt_dir, "_%s.vrt" % name.replace(" ", "_")))
    if vrt is None:
        return None
    layer = QgsRasterLayer(vrt, name, "gdal")
    if not layer.isValid():
        return None
    if crs is not None:
        layer.setCrs(crs)
    if kind == "depth":
        style_depth(layer, min_depth)
    elif kind == "elev":
        style_elevation(layer)

    try:
        props = layer.temporalProperties()
        props.setMode(raster_temporal_mode("FixedRangePerBand"))
        t0 = _t0(start_datetime)
        ranges = {}
        for i in range(len(paths)):
            ranges[i + 1] = QgsDateTimeRange(
                t0.addSecs(int(i * saveint)), t0.addSecs(int((i + 1) * saveint)))
        props.setFixedRangePerBand(ranges)
        props.setIsActive(True)
    except (AttributeError, TypeError):
        pass       # temporal support is a bonus, not a requirement
    return layer


def load_results(results_dir, resroot, crs, saveint=None, min_depth=0.01,
                 start_datetime=None, project=None, group_name=None, what=None):
    """Discover and load everything a run produced. Returns the layers added."""
    found = R.discover(results_dir, resroot)
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.insertGroup(0, group_name or resroot) if group_name else None
    layers = []

    for ext, path in sorted(found["single"].items()):
        if what and ext not in what:
            continue
        layer = load_raster(path, R.label_for(ext), crs, R.kind_for(ext), min_depth)
        if layer is None:
            continue
        project.addMapLayer(layer, group is None)
        if group is not None:
            group.addLayer(layer)
        layers.append(layer)

    for ext, paths in sorted(found["series"].items()):
        if what and ext not in what:
            continue
        label = "%s (%d steps)" % (R.label_for(ext), len(paths))
        layer = load_series(paths, label, crs, saveint or 1.0,
                            R.kind_for(ext), min_depth, start_datetime)
        if layer is None:
            continue
        project.addMapLayer(layer, group is None)
        if group is not None:
            group.addLayer(layer)
        layers.append(layer)

    return layers


def configure_temporal_controller(iface, n_steps, saveint, start_datetime=None):
    """Point the canvas temporal controller at the run's time span."""
    try:
        controller = iface.mapCanvas().temporalController()
        t0 = _t0(start_datetime)
        controller.setTemporalExtents(
            QgsDateTimeRange(t0, t0.addSecs(int(n_steps * saveint))))
        controller.setFrameDuration(QgsInterval(saveint, temporal_unit_seconds()))
    except (AttributeError, TypeError):
        pass
