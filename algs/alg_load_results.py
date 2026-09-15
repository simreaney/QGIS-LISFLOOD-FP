"""Load the results of a finished run as styled layers."""

import os

from qgis.core import (QgsProcessingException, QgsProcessingParameterCrs,
                       QgsProcessingParameterFile, QgsProcessingParameterNumber,
                       QgsProcessingParameterString)

from ..core import results as R
from ..gis.loader import load_results
from .base import LisfloodAlgorithm


class LoadResultsAlgorithm(LisfloodAlgorithm):
    GROUP = "Results"
    GROUP_ID = "results"

    FOLDER = "FOLDER"; RESROOT = "RESROOT"; CRS = "CRS"
    SAVEINT = "SAVEINT"; MIN_DEPTH = "MIN_DEPTH"

    def name(self):
        return "loadresults"

    def displayName(self):
        return self.tr("Load results")

    def shortHelpString(self):
        return self.tr(
            "Loads LISFLOOD-FP output grids as styled layers.\n\n"
            "The model writes no .prj, so the outputs carry no CRS; this writes sidecar "
            "files and sets the CRS on each layer. Depth grids store dry land as a "
            "literal zero rather than as nodata, so they are given an explicit "
            "transparency range -- without it the whole domain renders as solid blue.\n\n"
            "Time series are stacked into a single multiband layer wired to the "
            "temporal controller.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FOLDER, self.tr("Results folder"),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.RESROOT, self.tr("Results prefix"), defaultValue="res"))
        self.addParameter(QgsProcessingParameterCrs(
            self.CRS, self.tr("CRS"), defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SAVEINT, self.tr("Save interval (s), for the time series"),
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_DEPTH, self.tr("Hide depths below (m)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.01, minValue=0.0))

    def processAlgorithm(self, parameters, context, feedback):
        folder = self.parameterAsFile(parameters, self.FOLDER, context)
        resroot = self.parameterAsString(parameters, self.RESROOT, context) or "res"
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException(self.tr("No results folder given."))

        found = R.discover(folder, resroot)
        if not found["single"] and not found["series"]:
            raise QgsProcessingException(self.tr(
                "No LISFLOOD-FP grids starting with %r were found in %s."
                % (resroot, folder)))

        crs = self.parameterAsCrs(parameters, self.CRS, context)
        layers = load_results(
            folder, resroot, crs if crs and crs.isValid() else None,
            saveint=self.parameterAsDouble(parameters, self.SAVEINT, context),
            min_depth=self.parameterAsDouble(parameters, self.MIN_DEPTH, context),
            project=context.project(),
            group_name="LISFLOOD-FP: %s" % resroot)
        feedback.pushInfo("Loaded %d layer(s)." % len(layers))
        return {"LAYER_COUNT": len(layers), "RESULTS_FOLDER": folder}
