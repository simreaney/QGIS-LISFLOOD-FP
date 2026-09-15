"""
Qt5/Qt6 and QGIS 3.x/4.x compatibility.

This machine carries QGIS 3.42 (Qt 5.15, Python 3.9) and QGIS 4.0.1 (Qt 6), and the
plugin targets both. The differences that actually bite are enum relocations: Qt 6
scoped its enums, and QGIS 4 removed several long-deprecated flat aliases such as
QgsProcessingParameterDefinition.FlagAdvanced.

Everything here resolves at import time with try/except rather than version sniffing,
so a future relocation degrades to a sensible default instead of an AttributeError
at plugin load.
"""

from qgis.PyQt import QtCore

QT_VERSION = int(QtCore.QT_VERSION_STR.split(".")[0])


def is_qt6():
    return QT_VERSION >= 6


def advanced_flag():
    """The 'advanced parameter' flag, which moved in QGIS 4."""
    try:
        from qgis.core import Qgis
        return Qgis.ProcessingParameterFlag.Advanced
    except (ImportError, AttributeError):
        pass
    try:
        from qgis.core import QgsProcessingParameterDefinition
        return QgsProcessingParameterDefinition.FlagAdvanced
    except (ImportError, AttributeError):
        return 0


def wkt_esri_variant():
    """WKT1-ESRI, the dialect a .prj sidecar should carry."""
    try:
        from qgis.core import Qgis
        return Qgis.CrsWktVariant.Esri
    except (ImportError, AttributeError):
        pass
    try:
        from qgis.core import QgsCoordinateReferenceSystem
        return QgsCoordinateReferenceSystem.WKT1_ESRI
    except (ImportError, AttributeError):
        return None


def crs_to_esri_wkt(crs):
    variant = wkt_esri_variant()
    if variant is None:
        return crs.toWkt()
    try:
        return crs.toWkt(variant)
    except (TypeError, AttributeError):
        return crs.toWkt()


def raster_temporal_mode(name):
    """Qgis.RasterTemporalMode.<name>, present in 3.40+ and 4.x."""
    from qgis.core import Qgis
    try:
        return getattr(Qgis.RasterTemporalMode, name)
    except AttributeError:
        from qgis.core import QgsRasterLayerTemporalProperties
        return getattr(QgsRasterLayerTemporalProperties, "ModeFixed" + name, 0)


def temporal_unit_seconds():
    from qgis.core import Qgis
    try:
        return Qgis.TemporalUnit.Seconds
    except AttributeError:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.TemporalSeconds


def message_level(name):
    """Qgis.MessageLevel member by name, e.g. 'Warning'."""
    from qgis.core import Qgis
    try:
        return getattr(Qgis.MessageLevel, name)
    except AttributeError:
        return getattr(Qgis, name)


def distance_unit_meters():
    from qgis.core import Qgis
    try:
        return Qgis.DistanceUnit.Meters
    except AttributeError:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.DistanceMeters


def monospace_font(point_size=10):
    """A monospace QFont. Qt 6 scoped the StyleHint enum; Qt 5 has it flat."""
    from qgis.PyQt.QtGui import QFont
    font = QFont("Menlo")
    try:
        hint = QFont.StyleHint.Monospace
    except AttributeError:
        hint = QFont.Monospace
    font.setStyleHint(hint)
    font.setPointSize(point_size)
    return font


def enum_value(owner, *names):
    """First attribute of `owner` that exists, tried in order.

    Bridges Qt 5's flat enums and Qt 6's scoped ones, e.g.
    enum_value(Qt, "DockWidgetArea.RightDockWidgetArea", "RightDockWidgetArea").
    """
    for name in names:
        target = owner
        try:
            for part in name.split("."):
                target = getattr(target, part)
            return target
        except AttributeError:
            continue
    raise AttributeError("none of %s found on %r" % (names, owner))
