# Firefox signing and listed releases

OMP Tab Tether uses the existing Mozilla Add-ons (AMO) listing, `omp-tab-tether`, with the permanent Firefox ID `tab-tether@klondikemarlen.github.io`. Version `0.1.0` has already been submitted. Do not resubmit it or make a new listing; use the [AMO version dashboard](https://addons.mozilla.org/developers/addon/omp-tab-tether/versions) for review status.

This workflow submits the browser extension only. The Linux native-messaging host is installed separately; AMO does not install it.

## Set up `web-ext`

Use Git, Python 3.10+, a supported Node.js release (for example, current Node.js 22 LTS), and exactly `web-ext` **10.5.0**. Install the tool outside this checkout and explicitly put the executable's directory on `PATH`:

```sh
npm install --prefix "$HOME/.local/share/omp-tab-tether/web-ext" web-ext@10.5.0
export PATH="$HOME/.local/share/omp-tab-tether/web-ext/node_modules/.bin:$PATH"
command -v web-ext
web-ext --version
```

The release command checks the version and does not install anything. It ignores inherited `WEB_EXT_*` settings and web-ext config files so local options cannot redirect the submission or change which files are packaged.

## Preflight without submitting

From the project root, use the intended release commit with no staged or unstaged tracked changes. For a future release, bump `extension/manifest.json` to a new `MAJOR.MINOR.PATCH` version and commit the change before preflight. Do not change the Firefox ID.

```sh
python3 scripts/firefox_release.py preflight
```

Preflight checks the committed manifest, lints the extension, and builds an unsigned test package in a temporary directory. It never contacts AMO or requires credentials. It prints the exact commit and version and removes the temporary package. Preflight still works for `0.1.0`, but reports that submission is blocked.

Both commands use the tracked `extension/` file contents from `HEAD`, not the working directory. Local, ignored, and untracked files are not copied. The native host, Debian packaging, and repository-level files are not part of the upload.

## Submit a future listed version

1. Check the AMO dashboard before submitting. Use a version that has not already been uploaded. After preflight, keep the same release commit checked out.
2. Load `AMO_API_ISSUER` (JWT issuer) and `AMO_API_SECRET` (JWT secret) into the process environment from a trusted local credential store. Use [AMO API credentials](https://addons.mozilla.org/developers/addon/api/key/) for an account authorized to update this listing. Never commit credentials or include their values in shell history, logs, or command arguments.
3. Run the submission explicitly, substituting the exact version printed by preflight (here `0.1.1`):

   ```sh
   python3 scripts/firefox_release.py submit 0.1.1
   ```

   If a sibling `omp-send-context` checkout already has an authorized local `direnv` setup that exports those variables, you can reuse it without copying credentials. With that checkout's pinned dependencies installed, explicitly put its `web-ext` executable on the child command's `PATH`:

   ```sh
   direnv exec ../omp-send-context env PATH="$PWD/../omp-send-context/node_modules/.bin:$PATH" \
     python3 scripts/firefox_release.py submit 0.1.1
   ```

The command refuses `0.1.0` and earlier versions, or any requested version that does not match `HEAD`. A successful command submits a listed version for AMO review; it does not wait for approval, download an XPI, or prove publication. If the command fails after an upload begins, inspect the AMO dashboard before retrying. Once approved, install the exact signed version from AMO, verify its version in Firefox, and exercise pairing with the separately installed Linux host.
