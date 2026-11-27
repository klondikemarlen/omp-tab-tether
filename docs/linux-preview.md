# Linux preview: pair a terminal with a pull request

Show the matching GitHub pull request in Firefox when you switch to a paired Ptyxis terminal. Tether selects the **existing browser tab**: it does not navigate, reload the diff, focus the Firefox window, or move keyboard input. Selecting a PR does not switch terminals.

## Install the preview

Use Firefox, distro-installed `/usr/bin/ptyxis`, and a desktop exposing Ptyxis through AT-SPI (GNOME Wayland is the initial target). The native host uses `/usr/bin/python3`, PyGObject and the Atspi 2.0 typelib; on Ubuntu the latter packages are `python3-gi` and `gir1.2-atspi-2.0`. No OMP plugin, browser login or terminal configuration is required.

**Ubuntu 26.04 (Resolute).** Once `omp-tab-tether` is published in the [dedicated PPA](https://launchpad.net/~klondikemarlen/+archive/ubuntu/omp-tab-tether), install it with:

```sh
sudo add-apt-repository ppa:klondikemarlen/omp-tab-tether
sudo apt install omp-tab-tether
```

The package owns the native host, Firefox system manifest, and `/usr/share/omp-tab-tether/tab-tether.xpi`. It does not change Firefox profiles or load the extension. Snap and Flatpak Firefox require a [native messaging proxy](https://github.com/flatpak/xdg-native-messaging-proxy); review its security notes before installing `xdg-native-messaging-proxy`. A portal permission prompt is separate from package installation.

**From source instead.** Run `./install.py` as your desktop user, or `./install.py --sandboxed` for sandboxed Firefox. Use the XPI path printed by the installer. If migrating from this installation to apt, remove the per-user preview first (see below): a user manifest can shadow the packaged system manifest.

## Pair tabs in Firefox

1. Open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on**, and select `tab-tether.xpi`. If sandboxed Firefox cannot see the packaged path, copy the XPI to a new directory it can read:

   ```sh
   preview=$(mktemp -d "$HOME/tab-tether-preview.XXXXXXXX")
   cp /usr/share/omp-tab-tether/tab-tether.xpi "$preview/"
   printf '%s\n' "$preview/tab-tether.xpi"
   ```

2. Pin Tab Tether from Firefox's Extensions menu for easy access. This extension is unsigned: Firefox removes a temporary add-on on restart.
3. Open a GitHub PR in Firefox. Click the Tab Tether toolbar button on that tab, then focus the intended Ptyxis terminal within 30 seconds. If Firefox asks whether to allow the native host, review the request first; retry pairing if it expires.
4. Repeat for a second PR and terminal. Switch between those terminals. Each paired PR becomes the selected tab in its own Firefox window. Clicking the toolbar button on a paired PR removes its pair.

Pairs live in memory. Closing or leaving the paired PR, restarting the host, or reloading the add-on can require pairing again. An unpaired or ambiguous terminal does nothing. If two browser windows overlap, bring the relevant Firefox window into view yourself: Tether deliberately does not raise windows.

The toolbar badge shows `?` while waiting, `ON` when paired, or `!` after an error. Hover over the button for the reason. Click again on a waiting tab to cancel; after an error, click to retry. Only one tab can wait for a terminal at a time.

## What crosses the boundary

The Firefox extension recognizes GitHub PR URLs and keeps their tab IDs in the browser. The host observes window/terminal identity and focus through accessibility metadata. Native messages carry pairing IDs, not URLs, page content, terminal output, or keystrokes. No server, credentials, browsing history, or persistent pair database is required.

## Update or remove

Remove the temporary add-on in `about:debugging` before uninstalling either version. If you copied the XPI for sandbox access, remove that copy and its now-empty directory. Firefox manages any portal permission separately; apt does not grant or revoke it.

- **Apt installation:** `sudo apt purge omp-tab-tether` removes the package and its host registration. To also stop receiving updates from the archive, run `sudo add-apt-repository --remove ppa:klondikemarlen/omp-tab-tether`. Removing the archive alone does not uninstall the package. After an apt upgrade, refresh any sandbox copy and reload the temporary add-on.
- **Source installation:** remove `~/.mozilla/native-messaging-hosts/org.omp.tab_tether.json` and the two files `tab_tether.py` and `tab-tether.xpi` under `${XDG_DATA_HOME:-$HOME/.local/share}/omp-tab-tether/`. Leave other hosts and their registrations alone. To update instead, rerun the installer and reload the temporary add-on.
