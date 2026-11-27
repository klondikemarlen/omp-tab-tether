"""Build the unsigned add-on without carrying over checkout timestamps or modes."""

import sys
from pathlib import Path
from zipfile import ZipFile, ZipInfo


with ZipFile(sys.argv[1], "w") as archive:
    for filename in ("manifest.json", "background.js"):
        entry = ZipInfo(filename)  # Fixed ZIP epoch (1980-01-01).
        entry.create_system = 3  # Unix file permissions.
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, (Path("extension") / filename).read_bytes())
