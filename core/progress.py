"""
Run progress and log classification.

Progress comes from the **mass file**, not from stdout. The `comp_out` line at
iterateq.cpp:336 has no `fflush(stdout)` after it, so through a pipe it is
block-buffered and arrives in lumps. The mass file is explicitly flushed after every
write (iterateq.cpp:262) with the comment "user sometimes tracks progress through the
file" -- so that is the supported channel, and it updates every `massint` rather than
every `saveint`.

stdout is still worth reading: it carries the ETA, the "unknown parameter" warnings,
and the error text (which the model writes to stdout at least as often as stderr).
"""

import os
import re

#: T(mins): M: 500.0, C: 5.3, M/C: 94.94, ETot: 17.6, EFin: 12.3
COMP_OUT = re.compile(
    r"T\(mins\):\s*M:\s*(?P<model>[-\d.eE+]+),\s*C:\s*(?P<comp>[-\d.eE+]+),"
    r"\s*M/C:\s*(?P<ratio>[-\d.eE+]+),\s*ETot:\s*(?P<etot>[-\d.eE+]+),"
    r"\s*EFin:\s*(?P<efin>[-\d.eE+]+)")

UNKNOWN_PARAM = re.compile(r"Unknown parameter ignored:\s*(\S+?)\.")
FINISHED = re.compile(r"Total computation time:")

#: Terse model errors, all of which may appear on stdout rather than stderr.
ERROR_PATTERNS = (
    (re.compile(r"ERROR:.*?Aborting"), "input"),
    (re.compile(r"Unable to open"), "input"),
    (re.compile(r"no parameter file specified"), "deck"),
    (re.compile(r"Time Series invalid time values"), "timeseries"),
    (re.compile(r"Time Series 'count' is greater"), "timeseries"),
    (re.compile(r"has not been compiled with CUDA"), "build"),
    (re.compile(r"Aborting\.\.\."), "input"),
)
WARN_PATTERNS = (
    (re.compile(r"WARNING:"), "warning"),
    (UNKNOWN_PARAM, "typo"),
)


def classify(line):
    """Classify one stdout/stderr line as (kind, payload).

    kind is one of: progress, error, warn, finish, info.
    """
    m = COMP_OUT.search(line)
    if m:
        d = dict((k, float(v)) for k, v in m.groupdict().items())
        return "progress", d
    for pat, tag in ERROR_PATTERNS:
        if pat.search(line):
            return "error", {"tag": tag, "text": line.strip()}
    for pat, tag in WARN_PATTERNS:
        mm = pat.search(line)
        if mm:
            payload = {"tag": tag, "text": line.strip()}
            if tag == "typo":
                payload["keyword"] = mm.group(1)
            return "warn", payload
    if FINISHED.search(line):
        return "finish", {"text": line.strip()}
    return "info", {"text": line.rstrip()}


class MassProgress(object):
    """Tracks model time by tailing the mass file.

    The file is plain text, whitespace separated, 12 columns, column 0 being model
    seconds. On a checkpoint restart the model *appends*, writing a `####` banner and
    repeating the header, so both must be skipped.
    """

    def __init__(self, mass_path, sim_time):
        self.mass_path = mass_path
        self.sim_time = float(sim_time) if sim_time else 0.0
        self.last_time = None
        self.last_row = None

    def poll(self):
        """Return the fraction complete in [0, 1], or None if not readable yet."""
        row = self.tail_row()
        if row is None:
            return None
        self.last_row = row
        self.last_time = row[0]
        if self.sim_time <= 0:
            return None
        return max(0.0, min(1.0, row[0] / self.sim_time))

    def tail_row(self, window=8192):
        try:
            size = os.path.getsize(self.mass_path)
        except OSError:
            return None
        if not size:
            return None
        try:
            with open(self.mass_path, "rb") as fh:
                fh.seek(max(0, size - window))
                chunk = fh.read().decode("ascii", errors="replace")
        except OSError:
            return None
        for line in reversed(chunk.splitlines()):
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("Time"):
                continue
            parts = s.split()
            if len(parts) < 12:
                continue
            try:
                return [float(p) for p in parts[:12]]
            except ValueError:
                continue
        return None

    # -- the health signals that catch a "successful" but wrong run --------
    @property
    def wetted_area(self):
        return self.last_row[4] if self.last_row else None

    @property
    def volume(self):
        return self.last_row[5] if self.last_row else None

    @property
    def qin(self):
        return self.last_row[6] if self.last_row else None

    @property
    def qout(self):
        return self.last_row[8] if self.last_row else None

    @property
    def min_tstep(self):
        return self.last_row[2] if self.last_row else None


def scan_mass(mass_path):
    """Read a whole mass file into rows, skipping banners and repeated headers."""
    rows = []
    try:
        with open(mass_path, "r") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("Time"):
                    continue
                parts = s.split()
                if len(parts) < 12:
                    continue
                try:
                    rows.append([float(p) for p in parts[:12]])
                except ValueError:
                    continue
    except OSError:
        return []
    return rows
