"""The LISFLOOD-FP Processing provider."""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

from .algs.alg_build_binary import BuildBinaryAlgorithm
from .algs.alg_build_model import BuildModelAlgorithm
from .algs.alg_load_results import LoadResultsAlgorithm
from .algs.alg_run import RunModelAlgorithm
from .algs.alg_simulate import SimulateAlgorithm


class LisfloodProvider(QgsProcessingProvider):
    def id(self):
        return "lisfloodfp"

    def name(self):
        return self.tr("LISFLOOD-FP")

    def longName(self):
        return self.tr("LISFLOOD-FP flood inundation model")

    def icon(self):
        path = os.path.join(os.path.dirname(__file__), "icons", "lisflood.svg")
        return QIcon(path) if os.path.exists(path) else QgsProcessingProvider.icon(self)

    def loadAlgorithms(self):
        for cls in (BuildModelAlgorithm, RunModelAlgorithm, SimulateAlgorithm,
                    LoadResultsAlgorithm, BuildBinaryAlgorithm):
            self.addAlgorithm(cls())

    def tr(self, text):
        return QCoreApplication.translate("LisfloodProvider", text)
