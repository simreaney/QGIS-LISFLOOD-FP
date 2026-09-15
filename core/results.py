"""
Discovering, classifying and adjudicating model output.

Two things make this less trivial than globbing.

**Exit codes are not trustworthy.** The model uses exit(-1) for a missing .par or DEM,
exit(1) for option conflicts, and returns 0 after the `kill` wall-clock guard fires --
so a run cut short by the guard is indistinguishable from a complete one by exit code
alone. Success is therefore adjudicated on evidence: the expected files exist and the
mass file reached sim_time.

**A run can succeed and still be wrong.** Silently clamped boundary coordinates, a
.bci name with no matching .bdy block, and a point source on a nodata cell all give
exit code 0, a full set of outputs, and an entirely dry domain. Wetted area staying at
zero for the whole run catches all three, so it is checked explicitly.
"""

import glob
import os
import re

from .progress import scan_mass

#: extension -> (label, kind) where kind drives styling
RASTER_KINDS = {
    ".wd":      ("Water depth", "depth"),
    ".wdfp":    ("Floodplain depth", "depth"),
    ".max":     ("Maximum depth", "depth"),
    ".elev":    ("Water surface elevation", "elev"),
    ".mxe":     ("Maximum water elevation", "elev"),
    ".maxtm":   ("Time of maximum depth", "time"),
    ".inittm":  ("Time of first inundation", "time"),
    ".totaltm": ("Total time inundated", "time"),
    ".Qx":      ("Discharge, x faces", "flux"),
    ".Qy":      ("Discharge, y faces", "flux"),
    ".Qcx":     ("Channel discharge, x faces", "flux"),
    ".Qcy":     ("Channel discharge, y faces", "flux"),
    ".Vx":      ("Velocity, x faces", "velocity"),
    ".Vy":      ("Velocity, y faces", "velocity"),
    ".maxVc":   ("Maximum velocity", "velocity"),
    ".maxHaz":  ("Maximum hazard", "hazard"),
    ".op":      ("Overpass depth", "depth"),
    ".opelev":  ("Overpass elevation", "elev"),
}

#: grids whose values are hours, not seconds
TIME_IN_HOURS = (".maxtm", ".inittm", ".totaltm")

_SERIES = re.compile(r"^(?P<root>.+)-(?P<num>\d{4,})(?P<ext>\.[A-Za-z]+)$")

COMPLETED, TRUNCATED, KILLED, CRASHED, FAILED, NO_OUTPUT = (
    "completed", "truncated", "killed", "crashed", "failed", "no_output")


class Outcome(object):
    def __init__(self, status, message, detail=None, warnings=None):
        self.status = status
        self.message = message
        self.detail = detail or ""
        self.warnings = warnings or []

    @property
    def ok(self):
        return self.status in (COMPLETED, KILLED)

    def __repr__(self):
        return "<Outcome %s: %s>" % (self.status, self.message)


def discover(results_dir, resroot="res"):
    """Return {'series': {ext: [paths in save order]}, 'single': {ext: path}, ...}."""
    out = {"series": {}, "single": {}, "tables": {}, "resroot": resroot}
    if not os.path.isdir(results_dir):
        return out
    for path in sorted(glob.glob(os.path.join(results_dir, resroot + "*"))):
        base = os.path.basename(path)
        ext = os.path.splitext(base)[1]
        m = _SERIES.match(base)
        if m and m.group("ext") in RASTER_KINDS:
            out["series"].setdefault(m.group("ext"), []).append(path)
        elif ext in RASTER_KINDS:
            out["single"][ext] = path
        elif ext in (".mass", ".stage", ".discharge", ".velocity"):
            out["tables"][ext] = path
    for ext, paths in out["series"].items():
        paths.sort(key=lambda p: int(_SERIES.match(os.path.basename(p)).group("num")))
    return out


def label_for(ext):
    return RASTER_KINDS.get(ext, (ext.lstrip("."), "other"))[0]


def kind_for(ext):
    return RASTER_KINDS.get(ext, (ext.lstrip("."), "other"))[1]


def died_on_signal(exit_code):
    """Did the process die on a signal? subprocess reports -N; shells report 128+N."""
    if exit_code is None:
        return False
    return exit_code < 0 or exit_code in range(129, 160)


def adjudicate(results_dir, resroot, sim_time, exit_code, crashed=False, log_lines=()):
    """Decide whether a run really succeeded, on evidence rather than exit code."""
    warnings = []
    crashed = bool(crashed) or died_on_signal(exit_code)
    text = "\n".join(log_lines)

    typos = sorted(set(re.findall(r"Unknown parameter ignored:\s*(\S+?)\.", text)))
    for t in typos:
        warnings.append(
            "The parameter %r was ignored because LISFLOOD-FP does not recognise it. "
            "The run used the default value instead." % t)

    if crashed:
        return Outcome(CRASHED,
                       "LISFLOOD-FP crashed.",
                       "Two causes account for almost all of these, both verified: a "
                       "point source outside the DEM (the model indexes the cell with no "
                       "bounds check and writes straight into the depth array), and a "
                       "QVAR/HVAR boundary whose name has no matching block in the .bdy "
                       "file (names are case-sensitive). Re-run the pre-flight checks -- "
                       "both are caught before launch.", warnings)

    for pat, msg in (
        (r"ERROR:\s*(.*?)\.\s*Aborting", "LISFLOOD-FP could not read an input file."),
        (r"no parameter file specified", "The parameter file was not passed correctly."),
        (r"Time Series invalid time values",
         "A boundary time series has non-increasing times."),
        (r"Time Series 'count' is greater",
         "A boundary time series declares more values than it contains."),
        (r"has not been compiled with CUDA", "This build has no GPU support."),
    ):
        m = re.search(pat, text)
        if m:
            return Outcome(FAILED, msg, m.group(0), warnings)

    mass_path = os.path.join(results_dir, resroot + ".mass")
    rows = scan_mass(mass_path)
    if not rows:
        if os.path.exists(mass_path):
            return Outcome(NO_OUTPUT,
                           "The run stopped before completing a single timestep: the "
                           "mass balance file was created but never written to.",
                           "This usually means a boundary condition the model could not "
                           "resolve. Exit code %s." % exit_code, warnings)
        return Outcome(NO_OUTPUT,
                       "No mass balance file was written, so the run did not start "
                       "properly.",
                       "Exit code %s." % exit_code, warnings)

    last_t = rows[-1][0]
    areas = [r[4] for r in rows]
    if max(areas) <= 0:
        warnings.append(
            "No cell was ever wet: the flooded area stayed at 0 m2 for all %d mass "
            "balance records. Water is not entering the domain. Check that boundary "
            "coordinates lie on the domain edge (the model clamps out-of-range "
            "coordinates silently), that each .bci name has a matching .bdy block, and "
            "that point sources are not on nodata cells." % len(rows))

    verr = abs(rows[-1][10])
    if verr > 1e-2:
        warnings.append("Mass balance error is %.3g; depths may be unphysical." % verr)
    min_ts = min(r[2] for r in rows)
    if min_ts < 1e-4:
        warnings.append(
            "The timestep fell to %.3g s, which usually means one or two problem cells "
            "(a very steep face, or a Manning's n of zero)." % min_ts)

    if re.search(r"kill time reached|Simulation kill", text, re.I):
        return Outcome(KILLED,
                       "Run stopped at the wall-clock limit, at model time %g s of %g s "
                       "(%.0f%%)." % (last_t, sim_time, 100.0 * last_t / max(sim_time, 1)),
                       "All outputs up to that point were written.", warnings)

    if sim_time and last_t < 0.999 * sim_time:
        return Outcome(TRUNCATED,
                       "The run ended early, at model time %g s of %g s (%.0f%%)."
                       % (last_t, sim_time, 100.0 * last_t / max(sim_time, 1)),
                       "LISFLOOD-FP writes some errors only to standard output and is "
                       "often terse; see the full log.", warnings)

    if not os.path.exists(os.path.join(results_dir, resroot + ".max")):
        return Outcome(TRUNCATED,
                       "The mass file reached the end but no maximum-depth grid was "
                       "written, so the run did not complete its final output step.",
                       "", warnings)

    return Outcome(COMPLETED,
                   "Run completed: model time %g s." % last_t, "", warnings)
