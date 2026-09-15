"""
The .par control file: writing, parsing and -- most importantly -- validating.

LISFLOOD-FP ignores keywords it does not recognise (pars.cpp:1030) and only says so
when run verbosely. `sim_tme 3600` is not an error: the model uses the default 3600 s
and runs happily. Validation against `keywords.py` is what turns that into a real error.

Path rules the model imposes, all of which this module enforces:
  * filenames are read with `sscanf("%255s")`, so a path truncates at the first space
    and hard-fails at exactly 255 characters;
  * `#` starts a comment only in column 0;
  * keywords are case-insensitive, one per line, value separated by any whitespace.

Decks are written with *relative* filenames and run with the process CWD set to the
deck directory. That is what makes a deck inside `~/Documents/My Project/` work despite
the no-spaces rule: the model only ever sees `dem.asc`.
"""

import os
from collections import OrderedDict

from . import keywords as kw

MAX_PATH = 254
LEVEL_ERROR, LEVEL_WARN, LEVEL_INFO = "ERROR", "WARN", "INFO"


class Issue(object):
    __slots__ = ("level", "key", "message")

    def __init__(self, level, key, message):
        self.level, self.key, self.message = level, key, message

    def __repr__(self):
        return "%s %s: %s" % (self.level, self.key, self.message)

    @property
    def blocking(self):
        return self.level == LEVEL_ERROR


class ParFile(object):
    """An ordered set of .par entries. A value of None means a bare flag."""

    #: written in this order, so a deck reads the way a modeller thinks
    GROUP_ORDER = ("files", "run", "solver", "physics", "subgrid", "output", "other", "gpu")

    def __init__(self):
        self._entries = OrderedDict()
        self.header_comments = []
        self.extra_text = ""

    # -- construction ----------------------------------------------------
    def set(self, key, value=None):
        canon = kw.canonical(key)
        if canon is None:
            raise KeyError("%r is not a LISFLOOD-FP keyword" % key)
        self._entries[canon] = value
        return self

    def unset(self, key):
        self._entries.pop(kw.canonical(key) or key, None)
        return self

    def get(self, key, default=None):
        return self._entries.get(kw.canonical(key) or key, default)

    def has(self, key):
        return (kw.canonical(key) or key) in self._entries

    def items(self):
        return list(self._entries.items())

    # -- parsing ---------------------------------------------------------
    @classmethod
    def parse(cls, path):
        par = cls()
        par._raw = []
        with open(path, "r") as fh:
            for line in fh:
                raw = line.rstrip("\n").rstrip("\r")
                if not raw.strip() or raw[0] == "#":
                    continue
                parts = raw.split(None, 1)
                name = parts[0]
                value = parts[1].split()[0] if len(parts) > 1 and parts[1].split() else None
                par._raw.append((name, value))
                canon = kw.canonical(name)
                par._entries[canon or name] = value
        return par

    # -- validation ------------------------------------------------------
    def validate(self, deck_dir=None, caps=None):
        """Return a list of Issue. Any ERROR means the deck should not be run."""
        issues = []
        for name, value in self._entries.items():
            spec = kw.lookup(name)
            if spec is None:
                hint = kw.suggest(name)
                msg = "%r is not a LISFLOOD-FP keyword." % name
                if hint:
                    msg += " Did you mean %s?" % " or ".join(repr(h) for h in hint)
                msg += (" Unrecognised keywords are ignored silently, so the run would "
                        "use the default value instead.")
                issues.append(Issue(LEVEL_ERROR, name, msg))
                continue
            if name in kw.DENIED:
                issues.append(Issue(LEVEL_ERROR, name, kw.DENIED[name]))
            if spec.kind == "flag":
                if value is not None:
                    issues.append(Issue(LEVEL_WARN, name,
                                        "%r is a flag; the value %r is ignored." % (name, value)))
            elif value is None:
                if name != "checkpoint":   # checkpoint legitimately defaults to 1.0 h
                    issues.append(Issue(LEVEL_ERROR, name, "%r needs a value." % name))
            elif spec.kind in ("float", "int"):
                try:
                    float(value) if spec.kind == "float" else int(float(value))
                except ValueError:
                    issues.append(Issue(LEVEL_ERROR, name,
                                        "%r expects a number, got %r." % (name, value)))
            elif spec.kind == "str":
                issues.extend(self._check_path(name, value, deck_dir))
            if caps is not None and name in kw.GPU_ONLY and not caps.get("cuda"):
                issues.append(Issue(LEVEL_ERROR, name,
                                    "%r needs a CUDA build; this executable has no GPU support."
                                    % name))
        issues.extend(self._check_semantics())
        return issues

    def _check_path(self, name, value, deck_dir):
        out = []
        if name in ("resroot", "dirroot"):
            if " " in value:
                out.append(Issue(LEVEL_ERROR, name,
                                 "%r contains a space. LISFLOOD-FP reads names with "
                                 "sscanf(\"%%255s\"), which stops at the first space." % value))
            return out
        if " " in value:
            out.append(Issue(LEVEL_ERROR, name,
                             "Path %r contains a space. LISFLOOD-FP truncates filenames at "
                             "the first space, so it would try to open %r."
                             % (value, value.split(" ")[0])))
        if len(value) > MAX_PATH:
            out.append(Issue(LEVEL_ERROR, name,
                             "Path is %d characters; LISFLOOD-FP aborts at %d."
                             % (len(value), MAX_PATH + 1)))
        try:
            value.encode("ascii")
        except UnicodeEncodeError:
            out.append(Issue(LEVEL_ERROR, name, "Path %r contains non-ASCII characters." % value))
        if deck_dir is not None:
            full = value if os.path.isabs(value) else os.path.join(deck_dir, value)
            if not os.path.exists(full):
                out.append(Issue(LEVEL_ERROR, name,
                                 "%r refers to %r, which does not exist." % (name, value)))
        return out

    def _check_semantics(self):
        out = []
        if not self.has("DEMfile"):
            out.append(Issue(LEVEL_ERROR, "DEMfile", "No DEMfile: the model has no domain."))
        if not self.has("sim_time"):
            out.append(Issue(LEVEL_WARN, "sim_time",
                             "No sim_time; LISFLOOD-FP will default to 3600 s."))
        if self.has("routing") and not (self.has("acceleration") or self._sgc_on()):
            out.append(Issue(LEVEL_ERROR, "routing",
                             "`routing` needs the acceleration solver or the subgrid model. "
                             "LISFLOOD-FP disables it silently otherwise."))
        if self.has("latlong") and not self._sgc_on():
            out.append(Issue(LEVEL_ERROR, "latlong",
                             "`latlong` is only supported with the subgrid model."))
        if self.has("acceleration") and self.has("adaptoff"):
            out.append(Issue(LEVEL_ERROR, "acceleration",
                             "`acceleration` and `adaptoff` are mutually exclusive."))
        try:
            sim = float(self.get("sim_time") or 3600.0)
            save = float(self.get("saveint") or 1000.0)
            if save > sim:
                out.append(Issue(LEVEL_WARN, "saveint",
                                 "saveint (%g s) exceeds sim_time (%g s); no depth grids "
                                 "will be written." % (save, sim)))
            elif sim / save > 9999:
                out.append(Issue(LEVEL_WARN, "saveint",
                                 "This writes %d snapshots. Past 9999 the model switches "
                                 "from res-0001.wd to res-10000.wd, which breaks "
                                 "alphabetical ordering." % int(sim / save)))
        except (TypeError, ValueError):
            pass
        for varying, needs in (("bcifile", "bdyfile"),):
            if self.has(varying) and not self.has(needs):
                out.append(Issue(LEVEL_INFO, needs,
                                 "No %s: any QVAR/HVAR boundary would be disabled." % needs))
        return out

    def _sgc_on(self):
        return any(self.has(k) for k in
                   ("SGCwidth", "SGC_enable", "SGCp", "SGCr", "SGCn", "SGCbed", "SGCbank"))

    # -- writing ---------------------------------------------------------
    def merge_text(self, text):
        """Accept free-form `keyword value` lines (the advanced escape hatch).

        Written last, because the parser lets the final occurrence win.
        """
        self.extra_text = text or ""
        return self

    def render(self):
        lines = ["# %s" % c for c in self.header_comments]
        if lines:
            lines.append("#")
        by_group = OrderedDict((g, []) for g in self.GROUP_ORDER)
        for name, value in self._entries.items():
            spec = kw.lookup(name)
            group = spec.group if spec else "other"
            by_group.setdefault(group, []).append((name, value))
        for group in self.GROUP_ORDER:
            rows = by_group.get(group) or []
            if not rows:
                continue
            lines.append("")
            for name, value in rows:
                lines.append(name if value is None else "%-24s %s" % (name, value))
        if self.extra_text.strip():
            lines += ["", "# --- additional keywords ---"]
            lines += [l for l in self.extra_text.splitlines() if l.strip()]
        return "\n".join(lines) + "\n"

    def write(self, path):
        with open(path, "w", newline="\n") as fh:
            fh.write(self.render())
        return path
