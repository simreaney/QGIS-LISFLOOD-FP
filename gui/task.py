"""Background model run as a QgsTask, so the GUI stays usable during long runs."""

from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from ..gis.runner import run_model


class _Feedback(object):
    """Adapts a QgsTask to the small feedback protocol core/gis.runner expects."""

    def __init__(self, task):
        self.task = task

    def isCanceled(self):
        return self.task.isCanceled()

    def setProgress(self, pct):
        self.task.setProgress(pct)

    def pushInfo(self, text):
        self.task.logged.emit(text, 0)

    def pushWarning(self, text):
        self.task.logged.emit(text, 1)

    def reportError(self, text, fatal=False):
        self.task.logged.emit(text, 2)


class RunTask(QgsTask):
    """Runs a deck. Signals are emitted on the worker thread; connect queued."""

    logged = pyqtSignal(str, int)              # message, level (0 info/1 warn/2 error)
    stats = pyqtSignal(float, object)          # fraction, MassProgress

    def __init__(self, binary, par_path, sim_time, resroot, results_dir, threads):
        super(RunTask, self).__init__("LISFLOOD-FP: %s" % resroot, QgsTask.CanCancel)
        self.binary = binary
        self.par_path = par_path
        self.sim_time = sim_time
        self.resroot = resroot
        self.results_dir = results_dir
        self.threads = threads
        self.result = None

    def run(self):
        try:
            self.result = run_model(
                self.binary, self.par_path, self.sim_time,
                resroot=self.resroot, results_dir=self.results_dir,
                threads=self.threads, feedback=_Feedback(self),
                on_progress=lambda frac, tracker: self.stats.emit(frac, tracker))
        except Exception as exc:                # surfaced in finished()
            self.logged.emit(str(exc), 2)
            return False
        return True
