"""The demo project's layers and their styles, shared by the preview and the capture."""
import os

from qgis.core import (QgsBilinearRasterResampler, QgsColorRampShader, QgsCoordinateReferenceSystem, QgsFillSymbol,
                       QgsHillshadeRenderer, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings,
                       QgsProject, QgsRasterLayer, QgsRasterShader, QgsRuleBasedRenderer,
                       QgsSingleBandPseudoColorRenderer, QgsTextBufferSettings, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont, QPainter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "build", "data")

TERRAIN = [(52, "#b9cf8f"), (58, "#cbd99b"), (66, "#dcd6a0"), (80, "#cdb98a"),
           (100, "#b39a76"), (125, "#a39a8c"), (150, "#e9e4dc")]


def smooth(layer):
    """Bilinear when zoomed in: the 10 m grid would otherwise show its cells."""
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    layer.resampleFilter().setZoomedOutResampler(QgsBilinearRasterResampler())
    return layer


def _blend(name):
    mode = getattr(QPainter, "CompositionMode", QPainter)
    return getattr(mode, name)


def dem(path=None):
    layer = QgsRasterLayer(path or os.path.join(DATA, "dem.tif"), "DEM (10 m)")
    shader = QgsColorRampShader()
    shader.setColorRampType(QgsColorRampShader.Type.Interpolated)
    shader.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), "%g m" % v)
                                 for v, c in TERRAIN])
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader))
    return smooth(layer)


def hillshade(path=None):
    layer = QgsRasterLayer(path or os.path.join(DATA, "dem.tif"), "Hillshade")
    renderer = QgsHillshadeRenderer(layer.dataProvider(), 1, 315, 40)
    renderer.setZFactor(2.5)
    renderer.setMultiDirectional(True)
    layer.setRenderer(renderer)
    layer.setBlendMode(_blend("CompositionMode_Multiply"))
    layer.setOpacity(0.6)
    return smooth(layer)


def river():
    layer = QgsVectorLayer(os.path.join(DATA, "river.gpkg"), "River", "ogr")
    layer.setRenderer(layer.renderer().clone())
    layer.renderer().setSymbol(QgsLineSymbol.createSimple(
        {"color": "#3d84c6", "width": "0.5", "capstyle": "round", "joinstyle": "round"}))
    return layer


def roads():
    layer = QgsVectorLayer(os.path.join(DATA, "roads.gpkg"), "Roads", "ogr")
    root = QgsRuleBasedRenderer.Rule(None)
    for kind, width in (("main", 0.9), ("lane", 0.55)):
        symbol = QgsLineSymbol.createSimple({"color": "#8c8173", "width": str(width + 0.35)})
        inner = QgsLineSymbol.createSimple({"color": "#fbf6ea", "width": str(width)})
        symbol.appendSymbolLayer(inner.symbolLayer(0).clone())
        root.appendChild(QgsRuleBasedRenderer.Rule(symbol, filterExp=f"\"kind\" = '{kind}'", label=kind))
    layer.setRenderer(QgsRuleBasedRenderer(root))
    return layer


def buildings():
    layer = QgsVectorLayer(os.path.join(DATA, "buildings.gpkg"), "Buildings", "ogr")
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "#6a5f57", "outline_color": "#3b342f", "outline_width": "0.15"}))
    return layer


def inflow():
    layer = QgsVectorLayer(os.path.join(DATA, "inflow.gpkg"), "Inflow point", "ogr")
    layer.renderer().setSymbol(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#1764ab", "outline_color": "#ffffff",
         "outline_width": "0.6", "size": "4.2"}))
    settings = QgsPalLayerSettings()
    settings.fieldName = "name"
    text = QgsTextFormat()
    font = QFont("Helvetica Neue")
    font.setBold(True)
    text.setFont(font)
    text.setSize(10)
    text.setColor(QColor("#0d3c6e"))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.2)
    buffer.setColor(QColor(255, 255, 255, 230))
    text.setBuffer(buffer)
    settings.setFormat(text)
    settings.dist = 2.5
    try:
        settings.placement = QgsPalLayerSettings.Placement.OverPoint
    except AttributeError:
        settings.placement = QgsPalLayerSettings.OverPoint
    settings.quadOffset = getattr(QgsPalLayerSettings, "QuadrantRight", 5)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    return layer


def hydrograph():
    return QgsVectorLayer(os.path.join(DATA, "hydrograph.gpkg"), "Inflow hydrograph", "ogr")


def load_project():
    """Every demo layer, in Layers-panel order (top first)."""
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:27700"))
    layers = [inflow(), buildings(), river(), roads(), hydrograph(), hillshade(), dem()]
    for layer in layers:
        assert layer.isValid(), layer.name()
    project.addMapLayers(layers, False)
    root = project.layerTreeRoot()
    for layer in layers:
        root.addLayer(layer)
    return {layer.name(): layer for layer in layers}


def village_extent(margin=260.0):
    """The main village, on the outside of the bend, with some floodplain around it."""
    from qgis.core import QgsRectangle
    layer = buildings()
    box = QgsRectangle()
    box.setNull()
    for feature in layer.getFeatures():
        bounds = feature.geometry().boundingBox()
        if bounds.xMinimum() > 386000 + 2500:
            box.combineExtentWith(bounds)
    return box.buffered(margin)
