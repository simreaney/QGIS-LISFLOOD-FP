"""
Launching LISFLOOD-FP: command assembly, environment scrubbing, capability probing.

Three rules the model imposes on its command line:
  * the .par path must be the **last** argument and must not start with `-`
    (pars.cpp:37-42);
  * any .par keyword also works as `-keyword value`, parsed after the file, so the
    command line overrides the deck;
  * `-v` is read before everything else -- and several of the model's own sanity
    aborts in CheckParams are gated on `verbose == ON`, so a non-verbose run will
    silently continue past errors it would otherwise refuse. The plugin always passes
    `-v`.

The environment must be scrubbed. QGIS ships its own GDAL/PROJ, and this machine also
carries a conda GDAL on GDAL_DRIVER_PATH; inheriting those into the child produces
dlopen failures that look like model bugs. The DYLD_*/LD_* variables are worse, since
QGIS 3.x on Apple Silicon runs under Rosetta while the model binary is native arm64.
"""

import os
import re
import subprocess

#: Variables removed from the child environment before launching the model.
SCRUB = (
    "GDAL_DATA", "GDAL_DRIVER_PATH", "GDAL_PAM_PROXY_DIR",
    "PROJ_DATA", "PROJ_LIB", "PROJ_NETWORK",
    "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "DYLD_INSERT_LIBRARIES",
    "LD_LIBRARY_PATH", "LD_PRELOAD",
    "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
)

_BANNER = re.compile(r"LISFLOOD-FP version\s+(\d+)\.(\d+)\.(\d+)\s*\((\w+)\)")


class RunnerError(Exception):
    pass


def host_arch():
    """The machine's real CPU architecture.

    `platform.machine()` reports the *calling process's* architecture, which on Apple
    Silicon is "x86_64" whenever the caller is translated -- QGIS 3.42 is an x86_64
    build, so anything it launches sees x86_64 and would happily configure a build for
    the wrong architecture. `hw.optional.arm64` reports the hardware regardless.
    """
    import platform
    if platform.system() != "Darwin":
        return platform.machine()
    try:
        out = subprocess.run(["sysctl", "-n", "hw.optional.arm64"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip() == "1":
            return "arm64"
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.machine()


def executable_name():
    """`lisflood.exe` on Windows, `lisflood` elsewhere."""
    import platform
    return "lisflood.exe" if platform.system() == "Windows" else "lisflood"


def find_built_binary(build_dir):
    """Locate the executable a CMake build produced.

    Single-config generators (Make, Ninja) write it straight into the build directory;
    multi-config generators -- Visual Studio, notably -- put it in a per-configuration
    subdirectory instead.
    """
    name = executable_name()
    candidates = [os.path.join(build_dir, name)]
    for config in ("Release", "RelWithDebInfo", "Debug"):
        candidates.append(os.path.join(build_dir, config, name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def build_env(base=None, threads=None, binary=None):
    """Return a scrubbed copy of the environment for a model run."""
    env = dict(os.environ if base is None else base)
    for key in SCRUB:
        env.pop(key, None)
    if threads:
        env["OMP_NUM_THREADS"] = str(int(threads))
    if binary:
        # CMake copies the bundled NetCDF DLLs into the build root on Windows, which is
        # the parent directory when a multi-config generator puts the exe in Release/.
        bindir = os.path.dirname(os.path.abspath(binary))
        extra = [bindir, os.path.dirname(bindir)]
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def build_command(binary, par_path, extra_args=(), verbose=True):
    """Assemble argv. The .par always goes last."""
    par_name = os.path.basename(par_path)
    if par_name.startswith("-"):
        raise RunnerError(
            "The parameter file name %r starts with '-', which LISFLOOD-FP would "
            "read as an option rather than the deck." % par_name)
    argv = [binary]
    if verbose:
        argv.append("-v")
    argv.extend(str(a) for a in extra_args)
    argv.append(par_name)
    return argv


def default_threads():
    """Performance cores on Apple Silicon; a conservative share elsewhere.

    The model's inner loop has an OpenMP barrier every timestep, so scheduling work
    onto efficiency cores makes every performance core wait for the slowest.
    """
    try:
        out = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return max(1, int(out.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return max(1, (os.cpu_count() or 2) - 2)


class Capabilities(dict):
    """What a particular executable can do, parsed from its version banner."""

    @property
    def version(self):
        return self.get("version")

    @property
    def precision(self):
        return self.get("precision")

    @property
    def bytes_per_cell(self):
        return 420 if self.get("precision") == "double" else 210

    def describe(self):
        bits = ["LISFLOOD-FP %s (%s)" % (self.get("version", "?"), self.get("precision", "?"))]
        if self.get("cuda"):
            bits.append("CUDA")
        if self.get("only_rect"):
            bits.append("rectangular channels only")
        if self.get("arch"):
            bits.append(self["arch"])
        return ", ".join(bits)


def probe(binary, timeout=20):
    """Run `<binary> -v -version` and parse the capability banner.

    Raises RunnerError if the binary does not identify itself as LISFLOOD-FP, so a
    wrong path can never be silently accepted.
    """
    if not binary or not os.path.exists(binary):
        raise RunnerError("No LISFLOOD-FP executable at %r." % binary)
    if not os.access(binary, os.X_OK):
        raise RunnerError(
            "%r is not executable. Run: chmod +x %s" % (binary, binary))
    try:
        proc = subprocess.run([binary, "-v", "-version"],
                              capture_output=True, text=True, timeout=timeout,
                              env=build_env(binary=binary))
    except subprocess.TimeoutExpired:
        raise RunnerError("%r did not respond to -version within %ds." % (binary, timeout))
    except OSError as exc:
        msg = str(exc)
        if "Bad CPU type" in msg or "Exec format" in msg:
            raise RunnerError(
                "%r was built for a different processor architecture." % binary)
        raise RunnerError("Could not run %r: %s" % (binary, exc))

    text = (proc.stdout or "") + (proc.stderr or "")
    m = _BANNER.search(text)
    if not m:
        raise RunnerError(
            "%r did not identify itself as LISFLOOD-FP. Output was:\n%s"
            % (binary, text.strip()[:400] or "(nothing)"))

    caps = Capabilities({
        "path": os.path.abspath(binary),
        "version": "%s.%s.%s" % (m.group(1), m.group(2), m.group(3)),
        "version_tuple": (int(m.group(1)), int(m.group(2)), int(m.group(3))),
        "precision": m.group(4),
        "cuda": "CUDA supported" in text,
        "only_rect": "Rectangular channels only." in text,
        "disable_wet_dry": "_DISABLE_WET_DRY" in text,
        "banner": text.strip(),
        "arch": _arch(binary),
        # the banner does not report NetCDF; only a plugin-driven build knows
        "netcdf": None,
    })
    mq = re.search(r"_CALCULATE_Q_MODE\s+(\d+)", text)
    caps["calculate_q_mode"] = int(mq.group(1)) if mq else None
    return caps


def _arch(binary):
    """Real architecture of a Mach-O/ELF binary.

    Deliberately not platform.machine(): under Rosetta that reports the *host
    process* architecture, which would wrongly reject a correct native binary.
    """
    try:
        with open(binary, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return ""
    if len(head) < 8:
        return ""
    magic = int.from_bytes(head[:4], "little")
    if magic in (0xFEEDFACF, 0xFEEDFACE):
        cputype = int.from_bytes(head[4:8], "little")
        return {0x0100000C: "arm64", 0x01000007: "x86_64",
                0x0000000C: "arm", 0x00000007: "i386"}.get(cputype, "mach-o")
    if head[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        return "universal"
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:2] == b"MZ":
        return "pe"
    return ""


def check_deck_paths(deck_dir):
    """Confirm a deck directory is safe for the model's `%255s` filename scanner."""
    problems = []
    for name in sorted(os.listdir(deck_dir)):
        if " " in name:
            problems.append(
                "%r contains a space. LISFLOOD-FP truncates filenames at the first "
                "space, so this file can never be opened from a .par." % name)
        try:
            name.encode("ascii")
        except UnicodeEncodeError:
            problems.append("%r contains non-ASCII characters." % name)
        if len(name) > 254:
            problems.append("%r exceeds the model's 254-character filename limit." % name)
    return problems
