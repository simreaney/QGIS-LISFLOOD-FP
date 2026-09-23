"""Build the LISFLOOD-FP executable from source, or validate an existing one."""

import os
import subprocess  # nosec B404 - used only to launch LISFLOOD-FP and CMake

from qgis.core import (QgsProcessingException, QgsProcessingParameterBoolean,
                       QgsProcessingParameterFile, QgsProcessingParameterNumber)

from ..core.runner import RunnerError, find_built_binary, host_arch, probe
from ..gis import settings
from ..qt_compat import advanced_flag
from .base import LisfloodAlgorithm

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BuildBinaryAlgorithm(LisfloodAlgorithm):
    GROUP = "Setup"
    GROUP_ID = "setup"

    SOURCE_DIR = "SOURCE_DIR"
    BUILD_DIR = "BUILD_DIR"
    JOBS = "JOBS"
    ENABLE_NETCDF = "ENABLE_NETCDF"
    SET_DEFAULT = "SET_DEFAULT"

    def name(self):
        return "buildbinary"

    def displayName(self):
        return self.tr("Build or locate LISFLOOD-FP executable")

    def shortHelpString(self):
        return self.tr(
            "Compiles LISFLOOD-FP from a source checkout and registers the result.\n\n"
            "On macOS the stock CMake build fails because it requires libnuma, which is "
            "Linux-only. This algorithm supplies a replacement CMake find-module on the "
            "command line instead of editing your checkout, so the source tree is left "
            "byte-identical and survives a git pull. That is safe because the only NUMA "
            "code in the model is guarded by #ifdef __unix__, which Apple's compiler "
            "does not define.\n\n"
            "OpenMP is required and Apple's own compiler does not ship it, so a Homebrew "
            "LLVM toolchain is used when one is present.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.SOURCE_DIR, self.tr("LISFLOOD-FP source directory"),
            behavior=QgsProcessingParameterFile.Folder))
        build = QgsProcessingParameterFile(
            self.BUILD_DIR, self.tr("Build directory"),
            behavior=QgsProcessingParameterFile.Folder, optional=True)
        build.setFlags(build.flags() | advanced_flag())
        self.addParameter(build)
        self.addParameter(QgsProcessingParameterBoolean(
            self.SET_DEFAULT, self.tr("Use this build from now on"), defaultValue=True))
        netcdf = QgsProcessingParameterBoolean(
            self.ENABLE_NETCDF, self.tr("Enable NetCDF output"), defaultValue=False)
        netcdf.setFlags(netcdf.flags() | advanced_flag())
        self.addParameter(netcdf)
        jobs = QgsProcessingParameterNumber(
            self.JOBS, self.tr("Parallel compile jobs"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=0, minValue=0)
        jobs.setFlags(jobs.flags() | advanced_flag())
        self.addParameter(jobs)

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsFile(parameters, self.SOURCE_DIR, context)
        if not source or not os.path.exists(os.path.join(source, "CMakeLists.txt")):
            raise QgsProcessingException(self.tr(
                "%r does not look like a LISFLOOD-FP checkout (no CMakeLists.txt)."
                % source))
        build_dir = (self.parameterAsFile(parameters, self.BUILD_DIR, context)
                     or settings.DEFAULT_BUILD_DIR)
        jobs = self.parameterAsInt(parameters, self.JOBS, context) or 0
        netcdf = self.parameterAsBool(parameters, self.ENABLE_NETCDF, context)

        config = self._write_config(build_dir, netcdf)
        cmake = self._which("cmake")
        if not cmake:
            raise QgsProcessingException(self.tr(
                "CMake was not found. Install it with:  brew install cmake"))

        args = [cmake, "-S", source, "-B", build_dir,
                "-DCMAKE_BUILD_TYPE=Release",
                "-D_CONFIG=%s" % config]
        args += self._toolchain_args(feedback)

        self._run(args, feedback, "Configuring")

        # --config matters for multi-config generators (Visual Studio); it is ignored
        # by single-config ones, so it is safe to pass everywhere.
        build_args = [cmake, "--build", build_dir, "--target", "lisflood",
                      "--config", "Release"]
        build_args += ["-j", str(jobs)] if jobs else ["-j"]
        self._run(build_args, feedback, "Compiling")

        binary = find_built_binary(build_dir)
        if not binary:
            raise QgsProcessingException(self.tr(
                "The build reported success but no executable was found under %s."
                % build_dir))
        try:
            caps = probe(binary)
        except RunnerError as exc:
            raise QgsProcessingException(str(exc))
        caps["netcdf"] = bool(netcdf)
        feedback.pushInfo("Built %s" % caps.describe())

        if self.parameterAsBool(parameters, self.SET_DEFAULT, context):
            settings.set_binary_path(binary)
            settings.set_capabilities(caps)
            feedback.pushInfo("Registered as the default executable.")
        return {"BINARY": binary, "VERSION": caps.get("version"),
                "CAPABILITIES": caps.describe()}

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _which(name):
        import shutil
        return shutil.which(name) or (
            "/opt/homebrew/bin/%s" % name
            if os.path.exists("/opt/homebrew/bin/%s" % name) else None)

    def _toolchain_args(self, feedback):
        """Platform-specific configure flags.

        Only macOS needs help. Linux has real libnuma and native OpenMP, and Windows
        skips the NUMA block entirely, so the NUMA shim is deliberately *not* applied
        off macOS -- doing so would disable genuine NUMA support on Linux.
        """
        import platform
        system = platform.system()
        if system == "Linux":
            return []
        if system == "Windows":
            return []
        if system != "Darwin":
            return []
        args = ["-DCMAKE_MODULE_PATH=%s" % os.path.join(PLUGIN_DIR, "cmake_shims")]
        # host_arch(), not platform.machine(): QGIS 3.x is an x86_64 build, so a
        # translated process would otherwise configure an x86_64 build against an
        # arm64-only Homebrew libomp and fail at the OpenMP check.
        args.append("-DCMAKE_OSX_ARCHITECTURES=%s" % host_arch())
        for prefix in ("/opt/homebrew/opt", "/usr/local/opt"):
            clangxx = os.path.join(prefix, "llvm/bin/clang++")
            libomp = os.path.join(prefix, "libomp")
            if os.path.exists(clangxx):
                args += ["-DCMAKE_CXX_COMPILER=%s" % clangxx,
                         "-DCMAKE_C_COMPILER=%s" % clangxx[:-2]]
                if os.path.exists(libomp):
                    args.append("-DOpenMP_ROOT=%s" % libomp)
                return args
        feedback.pushWarning(
            "Homebrew LLVM was not found. Apple's own compiler does not provide "
            "OpenMP, which LISFLOOD-FP requires. If the build fails, run: "
            "brew install llvm libomp")
        return args

    @staticmethod
    def _write_config(build_dir, netcdf):
        if not os.path.isdir(build_dir):
            os.makedirs(build_dir)
        path = os.path.join(build_dir, "qgis_config.cmake")
        with open(path, "w") as fh:
            fh.write("set(_NETCDF %d)\n" % (1 if netcdf else 0))
            for define in ("_NUMERIC_MODE=1", "_ONLY_RECT=1", "_PROFILE_MODE=0",
                           "_DISABLE_WET_DRY=0", "_CALCULATE_Q_MODE=1",
                           "_SGM_BY_BLOCKS=0", "_BALANCE_TYPE=0"):
                fh.write("add_compile_definitions(%s)\n" % define)
        return path

    @staticmethod
    def _run(args, feedback, what):
        feedback.pushInfo("%s: %s" % (what, " ".join(args)))
        if not os.path.isabs(args[0]):
            raise QgsProcessingException("%s: %r is not a full path." % (what, args[0]))
        # args[0] is the absolute path to CMake, and argv goes to the OS directly with
        # no shell
        proc = subprocess.Popen(args, stdout=subprocess.PIPE,  # nosec B603
                                stderr=subprocess.STDOUT, universal_newlines=True)
        for line in proc.stdout:
            if feedback.isCanceled():
                proc.kill()
                raise QgsProcessingException("Cancelled.")
            feedback.pushInfo(line.rstrip())
        if proc.wait() != 0:
            raise QgsProcessingException("%s failed with exit code %d." % (what, proc.returncode))
