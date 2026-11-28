"""Preflight or submit a listed Firefox release from the committed extension."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
GECKO_ID = "tab-tether@klondikemarlen.github.io"
FIRST_SUBMITTED_VERSION = (0, 1, 0)
WEB_EXT_VERSION = "10.5.0"
AMO_API_URL = "https://addons.mozilla.org/api/v5/"
AMO_VERSIONS_URL = "https://addons.mozilla.org/developers/addon/omp-tab-tether/versions"


class ReleaseError(Exception):
    """An unmet release prerequisite."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="Lint and build locally without uploading")
    submit = commands.add_parser("submit", help="Upload a new version to the existing AMO listing")
    submit.add_argument("version", help="Exact extension version to submit from HEAD")
    args = parser.parse_args()

    try:
        release(args)
    except (ReleaseError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Firefox release: {error}\n")


def release(args):
    commit = git("rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    if git("status", "--porcelain=v1", "--untracked-files=no", "--ignore-submodules=none"):
        raise ReleaseError("Commit or restore staged and unstaged tracked changes before releasing.")

    with tempfile.TemporaryDirectory(prefix="tab-tether-firefox-") as temp_dir:
        workspace = Path(temp_dir)
        source = workspace / "extension"
        artifacts = workspace / "artifacts"
        extract_extension(commit, source)
        version = release_version(source / "manifest.json")
        version_label = ".".join(map(str, version))

        if args.command == "submit":
            if version <= FIRST_SUBMITTED_VERSION:
                raise ReleaseError("0.1.0 was already submitted to AMO. Use a later manifest version.")
            if args.version != version_label:
                raise ReleaseError(f"Requested {args.version!r}, but HEAD contains {version_label}.")

        web_ext = shutil.which("web-ext")
        if web_ext is None:
            raise ReleaseError(f"Put the web-ext {WEB_EXT_VERSION} executable on PATH.")
        web_ext = str(Path(web_ext).absolute())

        # Neither local web-ext configuration nor inherited WEB_EXT_* options may
        # override the input, destination, or signing behavior.
        environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("WEB_EXT_") and name not in ("AMO_API_ISSUER", "AMO_API_SECRET")
        }
        environment["NO_UPDATE_NOTIFIER"] = "1"
        result = subprocess.run(
            [web_ext, "--version"],
            cwd=workspace,
            env=environment,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        installed_version = result.stdout.strip()
        if installed_version != WEB_EXT_VERSION:
            raise ReleaseError(f"Expected web-ext {WEB_EXT_VERSION}; found {installed_version!r}.")

        options = [
            "--no-config-discovery",
            "--no-input",
            f"--source-dir={source}",
            f"--artifacts-dir={artifacts}",
        ]
        subprocess.run([web_ext, "lint", *options], cwd=workspace, env=environment, check=True)

        if args.command == "preflight":
            subprocess.run([web_ext, "build", *options], cwd=workspace, env=environment, check=True)
            print(f"Preflight passed for {GECKO_ID} {version_label} at {commit}; nothing uploaded.")
            if version <= FIRST_SUBMITTED_VERSION:
                print("Submission is blocked: the manifest version must be greater than 0.1.0.")
            return

        issuer = os.environ.get("AMO_API_ISSUER", "")
        secret = os.environ.get("AMO_API_SECRET", "")
        if not issuer.strip() or not secret.strip():
            raise ReleaseError("Set AMO_API_ISSUER and AMO_API_SECRET before submitting.")

        environment["WEB_EXT_API_KEY"] = issuer
        environment["WEB_EXT_API_SECRET"] = secret
        print(f"Submitting {GECKO_ID} {version_label} at {commit} to the existing AMO listing.", flush=True)
        subprocess.run(
            [
                web_ext,
                "sign",
                *options,
                "--channel=listed",
                f"--amo-base-url={AMO_API_URL}",
                "--approval-timeout=0",
            ],
            cwd=workspace,
            env=environment,
            check=True,
        )
        print(f"Submission finished. Check review status and signed downloads at {AMO_VERSIONS_URL}.")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=REPOSITORY)


def extract_extension(commit, destination):
    # Read blobs by object ID rather than copying the worktree or applying
    # archive attributes (export-ignore / export-subst).
    entries = git("ls-tree", "-rz", f"{commit}:extension")
    for entry in entries.split(b"\0")[:-1]:
        metadata, raw_path = entry.split(b"\t", 1)
        mode, _, object_id = metadata.split()
        relative_path = os.fsdecode(raw_path)
        if mode not in (b"100644", b"100755"):
            raise ReleaseError(f"The release source must use regular tracked files: {relative_path}.")
        if relative_path in (".amo-upload-uuid", ".web-extension-id"):
            raise ReleaseError(f"Remove web-ext submission state from the tracked extension: {relative_path}.")

        path = destination / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git("cat-file", "blob", object_id.decode("ascii")))


def release_version(manifest_path):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        gecko_id = manifest["browser_specific_settings"]["gecko"]["id"]
        version = manifest["version"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReleaseError("Read the version and Firefox ID in the committed extension/manifest.json.") from error

    if gecko_id != GECKO_ID:
        raise ReleaseError(f"Use the existing Firefox ID: {GECKO_ID}.")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version):
        raise ReleaseError("Set the manifest version to a numeric MAJOR.MINOR.PATCH without leading zeroes.")

    return tuple(map(int, version.split(".")))


if __name__ == "__main__":
    main()
