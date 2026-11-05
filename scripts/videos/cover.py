"""The opening slide's picture: a film's own flood, drawn by QGIS.

A run's maximum depth over the terrain's relief, in night colours so the water stands
out in light: the deepest brightest, the shallowest left out. One picture per format,
at that format's output size, with the model's area placed clear of where the slide's
type goes. Used by both films; the slide's type is drawn by film.py.
"""
import os

from qgis.core import (QgsColorRampShader, QgsCoordinateReferenceSystem, QgsFillSymbol,
                       QgsHillshadeRenderer, QgsMapRendererParallelJob, QgsMapSettings,
                       QgsRasterLayer, QgsRasterShader, QgsRasterTransparency, QgsRectangle,
                       QgsSingleBandPseudoColorRenderer, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

import style

NIGHT = "#15201e"
RELIEF = ("#203330", "#2c3f3b", "#435650")  # low, middle, high
WATER = [(0.05, "#1f5fa8"), (0.3, "#2b86d9"), (1.0, "#4fb4f2"), (2.5, "#a6e4ff"), (5.0, "#e6f8ff")]
SHOW_FROM = 0.05  # m: shallower is sheet flow, or the very edge of the flood
# Where the area goes, as (x, y, w, h) fractions of the frame: right of the type in
# 16:9, above it in 9:16.
BOXES = {"landscape": (0.455, 0.06, 0.53, 0.88), "vertical": (0.02, 0.125, 0.96, 0.38)}
SIZES = {"landscape": (3840, 2160), "vertical": (1080, 1920)}


def _pseudocolour(layer, stops):
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Type.Interpolated)
    ramp.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c)) for v, c in stops])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    layer.setRenderer(renderer)
    return renderer


def buildings(path):
    """Buildings as pale blocks, so a village reads against the water."""
    layer = QgsVectorLayer(path, "buildings", "ogr")
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "#d9e4e0", "outline_style": "no"}))
    layer.setOpacity(0.85)
    return layer


def finer(depth_path, folder, cell):
    """The depth grid resampled to *cell* metres, bilinear, so a coarse model grid's
    water has smooth edges in a close-up rather than steps."""
    from osgeo import gdal
    gdal.UseExceptions()
    path = os.path.join(folder, "cover_water.tif")
    gdal.Warp(path, depth_path, xRes=cell, yRes=cell, resampleAlg="bilinear",
              srcSRS="EPSG:27700", dstSRS="EPSG:27700")
    return path


def layers(dem_path, depth_path, z_factor=3.0):
    crs = QgsCoordinateReferenceSystem("EPSG:27700")
    relief = style.smooth(QgsRasterLayer(dem_path, "relief"))
    stats = relief.dataProvider().bandStatistics(1)
    lo, hi = stats.minimumValue, stats.maximumValue
    _pseudocolour(relief, [(lo, RELIEF[0]), (lo + 0.4 * (hi - lo), RELIEF[1]), (hi, RELIEF[2])])
    shade = style.smooth(QgsRasterLayer(dem_path, "shade"))
    hill = QgsHillshadeRenderer(shade.dataProvider(), 1, 315, 35)
    hill.setZFactor(z_factor)
    hill.setMultiDirectional(True)
    shade.setRenderer(hill)
    shade.setBlendMode(style._blend("CompositionMode_Multiply"))
    shade.setOpacity(0.85)
    water = style.smooth(QgsRasterLayer(depth_path, "water"))
    water.setCrs(crs)
    renderer = _pseudocolour(water, WATER)
    transparency = QgsRasterTransparency()
    entry = QgsRasterTransparency.TransparentSingleValuePixel()
    try:
        entry.min, entry.max, entry.percentTransparent = -1e9, SHOW_FROM, 100.0
    except AttributeError:
        entry.setMin(-1e9)
        entry.setMax(SHOW_FROM)
        entry.setPercentTransparent(100.0)
    transparency.setTransparentSingleValuePixelList([entry])
    renderer.setRasterTransparency(transparency)
    water.setBlendMode(style._blend("CompositionMode_Screen"))
    for layer in (relief, shade, water):
        assert layer.isValid(), layer.name()
    return [water, shade, relief]  # top first


def placed(area, width, height, box, fill=False):
    """The map extent that puts *area* inside *box* (x, y, w, h as fractions of the frame),
    or, with *fill*, makes it cover the box, the map running on to the frame's edges."""
    bx, by, bw, bh = box
    fit = min if fill else max
    scale = fit(area.width() / (bw * width), area.height() / (bh * height))  # m per pixel
    left = area.xMinimum() - (bx * width + (bw * width - area.width() / scale) / 2) * scale
    top = area.yMaximum() + (by * height + (bh * height - area.height() / scale) / 2) * scale
    return QgsRectangle(left, top - height * scale, left + width * scale, top)


def render(path, size, extent, map_layers):
    settings = QgsMapSettings()
    settings.setLayers(map_layers)
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:27700"))
    settings.setOutputSize(QSize(*size))
    settings.setExtent(extent)
    settings.setBackgroundColor(QColor(NIGHT))
    settings.setOutputDpi(96)
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(path)
    return path


def pictures(dem_path, depth_path, folder, boxes=None, overlays=(), z_factor=3.0, area=None, fill=False,
             water_cell=None):
    """{format name: picture path}, with any *overlays* (vector layers) above the water.

    *area* is the part of the map to show (or {format name: part}), by default all of it. A clipped catchment
    floats on the night background; a rectangular DEM looks better with *fill*, full
    bleed, so its edges stay out of the frame. *water_cell* resamples the water finer
    (see finer) for a close-up of a coarse model grid.
    """
    if water_cell:
        depth_path = finer(depth_path, folder, water_cell)
    map_layers = list(overlays) + layers(dem_path, depth_path, z_factor)
    areas = area if isinstance(area, dict) else {}
    out = {}
    for name, box in dict(BOXES, **(boxes or {})).items():
        width, height = SIZES[name]
        shown = areas.get(name) or (area if not isinstance(area, dict) else None) or map_layers[-1].extent()
        out[name] = render(os.path.join(folder, f"cover_{name}.png"), (width, height),
                           placed(shown, width, height, box, fill), map_layers)
    return out
