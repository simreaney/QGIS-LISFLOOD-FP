"""LISFLOOD-FP for QGIS."""


def classFactory(iface):
    from .lisflood_plugin import LisfloodPlugin
    return LisfloodPlugin(iface)
