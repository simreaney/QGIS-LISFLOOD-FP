"""The films' layers and their map styles."""
import os

from qgis.core import (QgsBilinearRasterResampler, QgsColorRampShader, QgsCoordinateReferenceSystem,
                       QgsHillshadeRenderer, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
                       QgsRasterLayer, QgsRasterShader, QgsRectangle, QgsSingleBandPseudoColorRenderer,
                       QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor, QFont, QPainter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "build", "appleby")  # the walkthrough's: prep_data.py
AXE = os.path.join(HERE, "build", "axe")        # the direct-rainfall film's: rain_prep.py

# Appleby: the Eden's floodplain at 119 m up to the hills at 179 m.
TERRAIN = [(118, "#b3cf8c"), (124, "#c4d796"), (132, "#d8d6a0"), (142, "#d3bf8e"),
           (155, "#b8a07c"), (168, "#a59b8f"), (180, "#ece8e1")]
# The River Axe runs from 300 m on the chalk and greensand hills to 2 m at its outlet.
AXE_TERRAIN = [(0, "#b3cf8c"), (25, "#c4d796"), (70, "#d8d6a0"), (130, "#d3bf8e"),
               (190, "#b8a07c"), (250, "#a59b8f"), (310, "#ece8e1")]
DEM_NAME = "Appleby DTM (1 m)"
# The town beside the Eden where the flood spreads: the east bank and the meander.
TOWN = QgsRectangle(368060, 520180, 368900, 520720)


def smooth(layer):
    """Bilinear when zoomed in, so a coarse grid does not show its cells."""
    layer.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    layer.resampleFilter().setZoomedOutResampler(QgsBilinearRasterResampler())
    return layer


def _blend(name):
    mode = getattr(QPainter, "CompositionMode", QPainter)
    return getattr(mode, name)


def dem(path=None, name=DEM_NAME, stops=TERRAIN):
    layer = QgsRasterLayer(path or os.path.join(DATA, "dem.tif"), name)
    shader = QgsColorRampShader()
    shader.setColorRampType(QgsColorRampShader.Type.Interpolated)
    shader.setColorRampItemList([QgsColorRampShader.ColorRampItem(v, QColor(c), "%g m" % v)
                                 for v, c in stops])
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader))
    return smooth(layer)


def hillshade(path=None, z_factor=2.5):
    layer = QgsRasterLayer(path or os.path.join(DATA, "dem.tif"), "Hillshade")
    renderer = QgsHillshadeRenderer(layer.dataProvider(), 1, 315, 40)
    renderer.setZFactor(z_factor)
    renderer.setMultiDirectional(True)
    layer.setRenderer(renderer)
    layer.setBlendMode(_blend("CompositionMode_Multiply"))
    layer.setOpacity(0.6)
    return smooth(layer)


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
    settings.quadOffset = getattr(QgsPalLayerSettings, "QuadrantLeft", 3)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    return layer


def _add(layers):
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:27700"))
    for layer in layers:
        assert layer.isValid(), layer.name()
    project.addMapLayers(layers, False)
    root = project.layerTreeRoot()
    for layer in layers:
        root.addLayer(layer)
    return {layer.name(): layer for layer in layers}


def load_project():
    """The walkthrough's layers, in Layers-panel order (top first)."""
    return _add([inflow(), hillshade(), dem()])


def load_axe():
    """The direct-rainfall film's project: the River Axe DEM, trimmed at its outlet, and its hillshade."""
    path = os.path.join(AXE, "dem.tif")
    return _add([hillshade(path), dem(path, "River Axe DEM (20 m)", AXE_TERRAIN)])
