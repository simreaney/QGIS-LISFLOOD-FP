"""Build a deck from layers and run it in one step."""

from qgis.core import QgsProcessingMultiStepFeedback

from .alg_build_model import BuildModelAlgorithm


class SimulateAlgorithm(BuildModelAlgorithm):
    """Everything BuildModelAlgorithm takes, plus the run."""

    GROUP = "Run"
    GROUP_ID = "run"

    def name(self):
        return "simulate"

    def displayName(self):
        return self.tr("Build and run flood simulation")

    def shortHelpString(self):
        return self.tr(
            "Builds a LISFLOOD-FP deck from QGIS layers, runs it, and loads the "
            "results -- the whole workflow in one step.\n\n"
            "Inflows are given in m3/s and converted to the model's per-metre "
            "convention automatically. Requires a configured executable; use "
            "'Build or locate LISFLOOD-FP executable' first if you have none.")

    def processAlgorithm(self, parameters, context, feedback):
        import processing          # only available inside a running QGIS

        steps = QgsProcessingMultiStepFeedback(2, feedback)

        steps.setCurrentStep(0)
        built = super(SimulateAlgorithm, self).processAlgorithm(parameters, context, steps)
        if steps.isCanceled():
            return built

        steps.setCurrentStep(1)
        run = processing.run(
            "lisfloodfp:runmodel",
            {"PAR_FILE": built["PAR_FILE"],
             "CRS": parameters.get(self.CRS, ""),
             "LOAD_RESULTS": True,
             "MIN_DEPTH": 0.01,
             "THREADS": 0,
             "EXTRA_ARGS": ""},
            context=context, feedback=steps, is_child_algorithm=True)

        built.update(run)
        return built
