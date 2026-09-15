"""Shared behaviour for the LISFLOOD-FP Processing algorithms."""

from qgis.core import QgsProcessingAlgorithm, QgsProcessingException
from qgis.PyQt.QtCore import QCoreApplication

from ..core.runner import RunnerError, probe
from ..gis import settings


class LisfloodAlgorithm(QgsProcessingAlgorithm):
    def tr(self, text):
        return QCoreApplication.translate("LisfloodAlgorithm", text)

    def group(self):
        return self.tr(self.GROUP)

    def groupId(self):
        return self.GROUP_ID

    def createInstance(self):
        return type(self)()

    # -- helpers ---------------------------------------------------------
    def resolve_binary(self, feedback=None):
        """Find and validate the executable, or explain how to get one."""
        path = settings.binary_path()
        if not path:
            raise QgsProcessingException(self.tr(
                "No LISFLOOD-FP executable is configured.\n\n"
                "Run the 'Build or locate LISFLOOD-FP executable' algorithm in this "
                "provider, or set the path in Settings > Options > LISFLOOD-FP.\n\n"
                "Note that building the deck does not need an executable -- only "
                "running the model does."))
        try:
            caps = probe(path)
        except RunnerError as exc:
            raise QgsProcessingException(self.tr(
                "The configured LISFLOOD-FP executable could not be used:\n\n%s"
                % exc))
        if feedback is not None:
            feedback.pushInfo("Using %s" % caps.describe())
        return path, caps

    def report_outcome(self, outcome, feedback):
        """Turn a RunOutcome into feedback, and fail loudly when it did not work."""
        for warning in outcome.warnings:
            feedback.pushWarning(warning) if hasattr(feedback, "pushWarning") \
                else feedback.pushInfo("WARNING: " + warning)
        if outcome.ok:
            feedback.pushInfo(outcome.message)
            return
        message = outcome.message
        if outcome.detail:
            message += "\n\n" + outcome.detail
        raise QgsProcessingException(message)
