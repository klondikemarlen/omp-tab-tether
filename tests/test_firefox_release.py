import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "firefox_release.py"

# This executable records the commands and staged inputs at the web-ext boundary.
# It never talks to AMO, even when called with `sign`.
RECORDING_WEB_EXT = """
import os
import sys
from pathlib import Path

command, *options = sys.argv[1:]
assert not any(name.startswith('AMO_API_') for name in os.environ)
expected_web_ext_variables = set()
if command == 'sign':
    expected_web_ext_variables = {'WEB_EXT_API_KEY', 'WEB_EXT_API_SECRET'}
    assert os.environ['WEB_EXT_API_KEY'] == 'test-issuer'
    assert os.environ['WEB_EXT_API_SECRET'] == 'test-secret'
assert {name for name in os.environ if name.startswith('WEB_EXT_')} == expected_web_ext_variables

with Path(os.environ['SIGNING_CALL_LOG']).open('a') as record:
    record.write(command + '\\n')

if command == '--version':
    print(os.environ['TOOL_VERSION'])
else:
    assert '--no-config-discovery' in options
    source_option = next(option for option in options if option.startswith('--source-dir='))
    source = Path(source_option.split('=', 1)[1])
    assert sorted(file.name for file in source.iterdir()) == ['background.js', 'manifest.json']
    assert (source / 'background.js').read_text() == '/* committed JavaScript */\\n'

if command == 'sign':
    assert '--channel=listed' in options
    assert '--amo-base-url=https://addons.mozilla.org/api/v5/' in options
    assert '--approval-timeout=0' in options
    assert not any('test-issuer' in option or 'test-secret' in option for option in options)
"""


class FirefoxReleaseTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.workspace = Path(workspace.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.extension = self.repo / "extension"
        self.extension.mkdir()
        self.manifest = self.extension / "manifest.json"
        self.background = self.extension / "background.js"
        self.background.write_text("/* committed JavaScript */\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored-local.js\n", encoding="utf-8")
        (self.repo / "host.py").write_text("# not a Firefox package file\n", encoding="utf-8")
        (self.repo / "scripts").mkdir()
        self.script = self.repo / "scripts" / RELEASE_SCRIPT.name
        shutil.copyfile(RELEASE_SCRIPT, self.script)
        self.git("init", "-q")
        self.set_manifest_version("0.1.0")

        web_ext = self.workspace / "web-ext"
        web_ext.write_text(f"#!{sys.executable}\n{RECORDING_WEB_EXT}", encoding="utf-8")
        web_ext.chmod(0o755)
        self.call_log = self.workspace / "web-ext.log"
        self.environment = {
            **os.environ,
            "PATH": f"{self.workspace}{os.pathsep}{os.environ['PATH']}",
            "AMO_API_ISSUER": "test-issuer",
            "AMO_API_SECRET": "test-secret",
            "WEB_EXT_CONFIG": "must-not-be-loaded.js",
            "WEB_EXT_AMO_BASE_URL": "https://example.invalid/api/",
            "SIGNING_CALL_LOG": str(self.call_log),
            "TOOL_VERSION": "10.5.0",
        }

    def git(self, *arguments):
        subprocess.run(
            ["git", "-c", "user.name=QA", "-c", "user.email=qa@example.invalid", *arguments],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def set_manifest_version(self, version, *, addon_id="tab-tether@klondikemarlen.github.io"):
        self.manifest.write_text(json.dumps({
            "version": version,
            "browser_specific_settings": {
                "gecko": {
                    "id": addon_id,
                },
            },
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", f"Fixture {version}")

    def run_release(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.workspace,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def test_preflight_only_lints_and_builds_the_committed_extension(self):
        (self.extension / "ignored-local.js").touch()
        (self.extension / "untracked-local.js").touch()

        result = self.run_release("preflight")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing uploaded", result.stdout)
        self.assertIn("Submission is blocked", result.stdout)
        self.assertEqual(self.call_log.read_text().splitlines(), ["--version", "lint", "build"])

    def test_submit_blocks_initial_and_mismatched_versions_before_calling_web_ext(self):
        initial = self.run_release("submit", "0.1.0")
        self.assertEqual(initial.returncode, 1)
        self.assertIn("0.1.0 was already submitted", initial.stderr)

        self.set_manifest_version("0.1.1")
        mismatch = self.run_release("submit", "0.1.2")
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("HEAD contains 0.1.1", mismatch.stderr)
        self.assertFalse(self.call_log.exists())

    def test_submit_uses_listed_channel_with_credentials_only_at_signing_boundary(self):
        self.set_manifest_version("0.1.1")

        result = self.run_release("submit", "0.1.1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/developers/addon/omp-tab-tether/versions", result.stdout)
        self.assertEqual(self.call_log.read_text().splitlines(), ["--version", "lint", "sign"])

    def test_preflight_rejects_staged_and_unstaged_changes(self):
        self.background.write_text("/* modified JavaScript */\n", encoding="utf-8")
        unstaged = self.run_release("preflight")
        self.assertEqual(unstaged.returncode, 1)
        self.assertIn("staged and unstaged tracked changes", unstaged.stderr)

        self.git("add", "extension/background.js")
        staged = self.run_release("preflight")
        self.assertEqual(staged.returncode, 1)
        self.assertIn("staged and unstaged tracked changes", staged.stderr)
        self.assertFalse(self.call_log.exists())

    def test_preflight_rejects_a_different_firefox_id(self):
        self.set_manifest_version("0.1.1", addon_id="wrong-id@example.invalid")

        result = self.run_release("preflight")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Use the existing Firefox ID", result.stderr)
        self.assertFalse(self.call_log.exists())

    def test_preflight_rejects_a_different_web_ext_version(self):
        self.environment["TOOL_VERSION"] = "10.5.1"

        result = self.run_release("preflight")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Expected web-ext 10.5.0", result.stderr)
        self.assertEqual(self.call_log.read_text().splitlines(), ["--version"])

    def test_submit_does_not_sign_without_both_amo_credentials(self):
        self.set_manifest_version("0.1.1")
        del self.environment["AMO_API_SECRET"]

        result = self.run_release("submit", "0.1.1")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Set AMO_API_ISSUER and AMO_API_SECRET", result.stderr)
        self.assertEqual(self.call_log.read_text().splitlines(), ["--version", "lint"])
