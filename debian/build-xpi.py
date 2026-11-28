"""Build the unsigned add-on without carrying over checkout timestamps or modes."""

import sys
from pathlib import Path
from zipfile import ZipFile, ZipInfo

# Keep this allowlist in sync with install.py.
EXTENSION_FILES = (
    "manifest.json",
    "background.js",
    "icons/tether.svg",
)


with ZipFile(sys.argv[1], "w") as archive:
    for filename in EXTENSION_FILES:
        entry = ZipInfo(filename)  # Fixed ZIP epoch (1980-01-01).
        entry.create_system = 3  # Unix file permissions.
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, (Path("extension") / filename).read_bytes())
