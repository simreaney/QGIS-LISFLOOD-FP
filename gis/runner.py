"""
Running the model from QGIS, with live progress, a live log, and working cancellation.

`QgsBlockingProcess` is deliberately not used: its Python API exposes neither a working
directory nor an environment, and this backend needs both -- the working directory
because decks use relative filenames, and the environment because QGIS's own
GDAL/PROJ variables (plus a conda GDAL on this machine) break a native child process.

Progress is polled from the mass file rather than parsed from stdout, because the
model's progress line is not flushed and arrives in lumps through a pipe, whereas the
mass file is explicitly flushed after every write.

The model installs no signal handlers, so cancellation escalates SIGTERM -> SIGKILL
and always loses everything since the last save interval. Enabling `checkpoint` is
what makes that recoverable.
"""

import os
import signal
import subprocess
import threading
import time

from ..core import progress as P
from ..core import results as R
from ..core.runner import build_command, build_env


class RunResult(object):
    def __init__(self, outcome, exit_code, log):
        self.outcome = outcome
        self.exit_code = exit_code
        self.log = log


def run_model(binary, par_path, sim_time, resroot="res", results_dir=None,
              threads=None, extra_args=(), feedback=None, poll=0.5,
              on_log=None, on_progress=None):
    """Run a deck to completion, streaming progress and log lines.

    `feedback` is anything with `isCanceled()`, `setProgress()`, `pushInfo()`,
    `pushWarning()` and `reportError()` -- QgsProcessingFeedback satisfies this, and
    so does a small adapter over QgsTask.
    """
    deck_dir = os.path.dirname(os.path.abspath(par_path))
    results_dir = results_dir or deck_dir
    # pre-create the output directory: the model otherwise shells out to an unquoted
    # `system("mkdir ...")`, which breaks on any path containing a space
    if not os.path.isdir(results_dir):
        os.makedirs(results_dir)

    argv = build_command(binary, par_path, extra_args=extra_args, verbose=True)
    env = build_env(threads=threads, binary=binary)

    proc = subprocess.Popen(
        argv, cwd=deck_dir, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)

    log = []
    lock = threading.Lock()

    def pump():
        try:
            for line in proc.stdout:
                line = line.rstrip("\n").rstrip("\r")
                with lock:
                    log.append(line)
                kind, payload = P.classify(line)
                if on_log:
                    on_log(kind, payload, line)
                if feedback is not None:
                    if kind == "error":
                        feedback.reportError(line)
                    elif kind == "warn":
                        feedback.pushWarning(line) if hasattr(feedback, "pushWarning") \
                            else feedback.pushInfo(line)
                    elif kind == "progress" and hasattr(feedback, "pushInfo"):
                        feedback.pushInfo(
                            "model %.1f min, elapsed %.1f min, ~%.1f min remaining"
                            % (payload["model"], payload["comp"], payload["efin"]))
        except (ValueError, OSError):
            pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    tracker = P.MassProgress(os.path.join(results_dir, resroot + ".mass"), sim_time)
    cancelled = False

    while proc.poll() is None:
        time.sleep(poll)
        frac = tracker.poll()
        if frac is not None:
            if feedback is not None:
                feedback.setProgress(100.0 * frac)
            if on_progress:
                on_progress(frac, tracker)
        if feedback is not None and feedback.isCanceled():
            cancelled = True
            _terminate(proc)
            break

    reader.join(timeout=5)
    exit_code = proc.poll()

    with lock:
        lines = list(log)

    if cancelled:
        outcome = R.Outcome(
            "cancelled",
            "Run cancelled at model time %s."
            % ("%.0f s" % tracker.last_time if tracker.last_time else "unknown"),
            "LISFLOOD-FP installs no signal handlers, so everything since the last "
            "save interval is lost. Snapshots already written are still valid.",
            [])
    else:
        outcome = R.adjudicate(results_dir, resroot, sim_time, exit_code,
                               crashed=False, log_lines=lines)
    return RunResult(outcome, exit_code, lines)


def _terminate(proc, grace=5.0):
    """SIGTERM, then SIGKILL. The model handles neither, so this is always abrupt."""
    try:
        proc.terminate()
    except OSError:
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        proc.kill()
    except OSError:
        pass
