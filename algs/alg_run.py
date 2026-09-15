"""Run an existing LISFLOOD-FP deck and load its results."""

import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsProcessingException,
                       QgsProcessingParameterBoolean, QgsProcessingParameterCrs,
                       QgsProcessingParameterFile, QgsProcessingParameterNumber,
                       QgsProcessingParameterString)

from ..core.par import ParFile
from ..core.runner import check_deck_paths
from ..gis import settings
from ..gis.loader import load_results
from ..gis.runner import run_model
from ..qt_compat import advanced_flag
from .base import LisfloodAlgorithm


class RunModelAlgorithm(LisfloodAlgorithm):
    GROUP = "Run"
    GROUP_ID = "run"

    PAR_FILE = "PAR_FILE"
    THREADS = "THREADS"
    EXTRA_ARGS = "EXTRA_ARGS"
    LOAD_RESULTS = "LOAD_RESULTS"
    MIN_DEPTH = "MIN_DEPTH"
    CRS = "CRS"

    def name(self):
        return "runmodel"

    def displayName(self):
        return self.tr("Run a model deck")

    def shortHelpString(self):
        return self.tr(
            "Runs an existing LISFLOOD-FP parameter (.par) file and loads the results "
            "as styled layers.\n\n"
            "Progress is read from the model's mass balance file, so it updates every "
            "mass interval rather than every save interval.\n\n"
            "The run is judged on evidence rather than on the exit code, which is not "
            "reliable: the model returns 0 both for a completed run and for one cut "
            "short by its wall-clock guard. A run that finishes but never wets a cell "
            "is reported as a problem, since that is what a mis-specified boundary "
            "looks like.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PAR_FILE, self.tr("Parameter file (.par)"),
            extension="par"))
        self.addParameter(QgsProcessingParameterCrs(
            self.CRS, self.tr("CRS of the model grid"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.LOAD_RESULTS, self.tr("Load results when finished"), defaultValue=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_DEPTH, self.tr("Hide depths below (m)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.01, minValue=0.0))

        threads = QgsProcessingParameterNumber(
            self.THREADS, self.tr("Threads (0 = automatic)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=0, minValue=0)
        threads.setFlags(threads.flags() | advanced_flag())
        self.addParameter(threads)

        extra = QgsProcessingParameterString(
            self.EXTRA_ARGS,
            self.tr("Command line overrides, e.g. -sim_time 7200"),
            defaultValue="", optional=True)
        extra.setFlags(extra.flags() | advanced_flag())
        self.addParameter(extra)

    def processAlgorithm(self, parameters, context, feedback):
        par_path = self.parameterAsFile(parameters, self.PAR_FILE, context)
        if not par_path or not os.path.exists(par_path):
            raise QgsProcessingException(self.tr("No parameter file given."))
        par_path = os.path.abspath(par_path)
        deck_dir = os.path.dirname(par_path)

        binary, caps = self.resolve_binary(feedback)

        par = ParFile.parse(par_path)
        issues = par.validate(deck_dir=deck_dir, caps=caps)
        blocking = [i for i in issues if i.blocking]
        for issue in issues:
            text = "%s: %s" % (issue.key, issue.message)
            if issue.blocking:
                feedback.reportError(text)
            else:
                feedback.pushInfo(text)
        if blocking:
            raise QgsProcessingException(self.tr(
                "The parameter file has %d problem(s) that would produce a wrong or "
                "failed run; see the log above." % len(blocking)))

        for problem in check_deck_paths(deck_dir):
            feedback.reportError(problem)

        resroot = par.get("resroot") or "res"
        dirroot = par.get("dirroot") or ""
        results_dir = os.path.join(deck_dir, dirroot) if dirroot else deck_dir
        sim_time = float(par.get("sim_time") or 3600.0)
        saveint = float(par.get("saveint") or 1000.0)

        threads = self.parameterAsInt(parameters, self.THREADS, context) or settings.threads()
        raw_extra = (self.parameterAsString(parameters, self.EXTRA_ARGS, context) or "").split()

        feedback.pushInfo("Running %s in %s with %d thread(s)"
                          % (os.path.basename(par_path), deck_dir, threads))
        result = run_model(binary, par_path, sim_time, resroot=resroot,
                           results_dir=results_dir, threads=threads,
                           extra_args=raw_extra, feedback=feedback)

        for line in result.log[-40:]:
            feedback.pushInfo(line)
        self.report_outcome(result.outcome, feedback)

        out = {"RESULTS_FOLDER": results_dir,
               "EXIT_CODE": result.exit_code,
               "STATUS": result.outcome.status}

        if self.parameterAsBool(parameters, self.LOAD_RESULTS, context):
            crs = self.parameterAsCrs(parameters, self.CRS, context)
            if crs is None or not crs.isValid():
                crs = self._crs_from_deck(par, deck_dir)
            min_depth = self.parameterAsDouble(parameters, self.MIN_DEPTH, context)
            layers = load_results(results_dir, resroot, crs, saveint=saveint,
                                  min_depth=min_depth, project=context.project(),
                                  group_name="LISFLOOD-FP: %s" % resroot)
            feedback.pushInfo("Loaded %d layer(s)." % len(layers))
            out["LAYER_COUNT"] = len(layers)
        return out

    @staticmethod
    def _crs_from_deck(par, deck_dir):
        """Recover the CRS from the DEM's .prj sidecar, if there is one."""
        dem = par.get("DEMfile")
        if not dem:
            return QgsCoordinateReferenceSystem()
        prj = os.path.splitext(os.path.join(deck_dir, dem))[0] + ".prj"
        if os.path.exists(prj):
            try:
                with open(prj) as fh:
                    return QgsCoordinateReferenceSystem.fromWkt(fh.read())
            except OSError:
                pass
        return QgsCoordinateReferenceSystem()
