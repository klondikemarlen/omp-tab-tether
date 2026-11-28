#!/usr/bin/python3
"""Install the native host and prepare a temporary Firefox add-on for this user."""

import argparse
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
HOST = "org.omp.tab_tether"
EXTENSION_ID = "tab-tether@klondikemarlen.github.io"

# Keep this allowlist in sync with debian/build-xpi.py.
EXTENSION_FILES = (
    "manifest.json",
    "background.js",
    "icons/tether.svg",
)

@contextmanager
def installation_file(destination, mode):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        yield staged
        staged.chmod(mode)
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)

def install(sandboxed):
    if os.geteuid() == 0:
        raise SystemExit("Run as your desktop user, not with sudo.")

    if sandboxed and not Path("/usr/share/dbus-1/services/org.freedesktop.NativeMessagingProxy.service").is_file():
        raise SystemExit("Install xdg-native-messaging-proxy before registering a sandboxed Firefox host.")

    try:
        import gi
        gi.require_version("Atspi", "2.0")
    except (ImportError, ValueError) as error:
        raise SystemExit("System Python needs PyGObject and the Atspi 2.0 typelib.") from error

    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    destination = data_home.resolve() / "omp-tab-tether"
    executable = destination / "tab_tether.py"
    addon = destination / "tab-tether.xpi"
    manifest = Path.home() / ".mozilla/native-messaging-hosts" / f"{HOST}.json"
    registration = {
        "name": HOST,
        "description": "Observe explicitly paired Ptyxis terminals",
        "path": str(executable),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }
    with installation_file(addon, 0o600) as staged:
        with ZipFile(staged, "w", ZIP_DEFLATED) as archive:
            for filename in EXTENSION_FILES:
                archive.write(ROOT / "extension" / filename, filename)

    with installation_file(executable, 0o700) as staged:
        shutil.copyfile(ROOT / "host/tab_tether.py", staged)

    with installation_file(manifest, 0o600) as staged:
        staged.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")

    print(f"Registered native host: {manifest}")
    print(f"In Firefox, open about:debugging#/runtime/this-firefox, choose Load Temporary Add-on, then select:\n{addon}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandboxed", action="store_true", help="require the native messaging proxy for Snap/Flatpak Firefox")
    install(parser.parse_args().sandboxed)
