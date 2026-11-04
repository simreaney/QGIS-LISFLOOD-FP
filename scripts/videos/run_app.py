"""Run a script inside the real QGIS 4 application, offscreen at 4x, with a fresh profile.

    python3 run_app.py <script.py> <output folder> [seconds]

The profile is thrown away each time, so nothing touches the user's own: it has
this checkout installed as the plugin (a link), the QGIS 3 settings migration and
the macOS Keychain turned off (both wait forever offscreen), and map symbols at
the usual 96 dpi.

LISFLOOD_ICON_WORKAROUND=1 is for QGIS 4.2.3 on macOS 27.2, which dies at start-up
making its Dock icon: CoreGraphics refuses the colour space Qt builds from the
icon's sRGB tag. QGIS_PREFIX_PATH then points at a tree of links to the app's own
folders in which only that icon is replaced, by an untagged copy of the same
pixels. The default app, a QGIS master build (4.3), starts without it.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
APP = os.environ.get("LISFLOOD_QGIS_APP", "/Applications/QGIS-master-6ece892.app")
BUILD = os.path.join(HERE, "build")
PROFILES = os.path.join(BUILD, "qgis-profiles")
PREFIX = os.path.join(BUILD, "qgis-prefix", os.path.basename(APP))  # one per app: they are links into it
ICON = os.path.join("Contents", "Resources", "qgis", "images", "icons", "qgis-icon-macos.png")


def shadow_prefix():
    """Links to the app's folders, real folders only down the path to the icon."""
    if os.path.exists(os.path.join(PREFIX, ICON)):
        return PREFIX
    shutil.rmtree(PREFIX, ignore_errors=True)
    parts = ICON.split(os.sep)
    real, fake = APP, PREFIX
    for depth, part in enumerate(parts):
        os.makedirs(fake, exist_ok=True)
        for entry in os.listdir(real):
            if entry != part:
                os.symlink(os.path.join(real, entry), os.path.join(fake, entry))
        real, fake = os.path.join(real, part), os.path.join(fake, part)
    from PIL import Image  # same pixels, no colour-space chunks
    with Image.open(real) as icon:
        icon.load()
        Image.frombytes(icon.mode, icon.size, icon.tobytes()).save(fake)
    return PREFIX


def fresh_profile():
    shutil.rmtree(PROFILES, ignore_errors=True)
    profile = os.path.join(PROFILES, "profiles", "film")
    os.makedirs(os.path.join(profile, "qgis.org"))  # QGIS 4: not QGIS/
    os.makedirs(os.path.join(profile, "python", "plugins"))
    os.symlink(REPO, os.path.join(profile, "python", "plugins", "lisflood_fp"))
    with open(os.path.join(profile, "qgis.org", "QGIS4.ini"), "w") as handle:
        handle.write("[migration]\nmigrated_from_3=true\n\n"
                     "[auth]\nuse_password_helper=false\n\n"
                     "[authentication]\ngenerate-random-password-for-keychain=false\nuse-password-helper=false\n\n"
                     "[PythonPlugins]\nlisflood_fp=true\n\n"
                     # Symbols at 96 dpi, as on a desktop: offscreen, the "physical" DPI is
                     # made up (25 at 4x), which shrinks every symbol and label on the map.
                     "[gui]\nqgis\\respect_screen_dpi=false\n")
    password = os.path.join(PROFILES, "auth-password.txt")
    with open(password, "w") as handle:
        handle.write("film-profile-only\n")
    return password


if __name__ == "__main__":
    script, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 600
    os.makedirs(out, exist_ok=True)
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "LANG", "TMPDIR") if k in os.environ}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=os.environ.get("FILM_SCALE", "4"),
               FILM_OUT=out, FILM_SCRIPTS=HERE, QGIS_AUTH_PASSWORD_FILE=fresh_profile())
    if os.environ.get("LISFLOOD_ICON_WORKAROUND") == "1":
        env["QGIS_PREFIX_PATH"] = shadow_prefix()
    binary = os.path.join(APP, "Contents", "MacOS", os.path.basename(APP).replace(".app", ""))
    try:
        result = subprocess.run([binary, "--profiles-path", PROFILES, "--profile", "film", "--nologo",
                                 "--noversioncheck", "--code", script], env=env, timeout=timeout,
                                capture_output=True, text=True)
        print(result.stdout[-4000:], result.stderr[-2000:], "exit", result.returncode)
    except subprocess.TimeoutExpired as exc:
        print("timed out\nSTDOUT", (exc.stdout or b"")[-3000:], "\nSTDERR", (exc.stderr or b"")[-3000:])
