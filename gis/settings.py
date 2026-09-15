"""Plugin settings: where the executable is, and what it can do."""

import json
import os

from qgis.core import QgsSettings

GROUP = "lisflood-fp/"
DEFAULT_BUILD_DIR = os.path.expanduser("~/.lisflood-fp/build")


def _s():
    return QgsSettings()


def get(key, default=None):
    return _s().value(GROUP + key, default)


def set_(key, value):
    _s().setValue(GROUP + key, value)


def binary_path():
    """Configured path, else the plugin's own build, else one on PATH."""
    configured = get("binaryPath")
    if configured and os.path.exists(configured):
        return configured
    from ..core.runner import executable_name, find_built_binary
    built = find_built_binary(get("buildDir", DEFAULT_BUILD_DIR) or DEFAULT_BUILD_DIR)
    if built:
        return built
    import shutil
    return shutil.which(executable_name()) or shutil.which("lisflood")


def set_binary_path(path):
    set_("binaryPath", path)


def capabilities():
    raw = get("capabilities")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def set_capabilities(caps):
    set_("capabilities", json.dumps(dict(caps)))


def threads():
    value = get("threads", 0)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value
    from ..core.runner import default_threads
    return default_threads()
