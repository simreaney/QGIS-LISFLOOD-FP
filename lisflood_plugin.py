"""Plugin entry point: registers the Processing provider."""

import os

from qgis.core import QgsApplication, QgsMessageLog, Qgis
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import LisfloodProvider
from .qt_compat import enum_value


class LisfloodPlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.provider = None
        self.action = None
        self.dock = None

    def initProcessing(self):
        self.provider = LisfloodProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        icon_path = os.path.join(self.plugin_dir, "icons", "lisflood.svg")
        self.action = QAction(QIcon(icon_path), self.tr("LISFLOOD-FP"),
                              self.iface.mainWindow())
        self.action.setObjectName("LisfloodFpAction")
        self.action.setStatusTip(self.tr("LISFLOOD-FP flood modelling tools"))
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(self.tr("&LISFLOOD-FP"), self.action)

        from .gui.dock import LisfloodDock
        self.dock = LisfloodDock(self.iface, self.iface.mainWindow())
        self.iface.addDockWidget(
            enum_value(Qt, "DockWidgetArea.RightDockWidgetArea", "RightDockWidgetArea"),
            self.dock)
        self.dock.hide()
        QgsMessageLog.logMessage("LISFLOOD-FP plugin loaded", "LISFLOOD-FP", Qgis.Info)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginRasterMenu(self.tr("&LISFLOOD-FP"), self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        if self.dock is not None:
            self.dock.show()
            self.dock.raise_()
            self.dock._refresh_binary()
            return
        from .gis import settings
        if not settings.binary_path():
            self.iface.messageBar().pushMessage(
                self.tr("LISFLOOD-FP"),
                self.tr("No executable configured yet. Use 'Build or locate LISFLOOD-FP "
                        "executable' in the Processing toolbox. Building a model deck "
                        "works without one."),
                level=Qgis.Warning, duration=8)
        else:
            self.iface.messageBar().pushMessage(
                self.tr("LISFLOOD-FP"),
                self.tr("Tools are in the Processing Toolbox under LISFLOOD-FP."),
                level=Qgis.Info, duration=5)
        try:
            self.iface.openProcessing()
        except AttributeError:
            pass

    def tr(self, text):
        return QCoreApplication.translate("LisfloodPlugin", text)
