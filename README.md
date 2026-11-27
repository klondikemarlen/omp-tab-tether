# OMP Tab Tether

Show the matching GitHub pull request in Firefox when you switch to a paired Ptyxis terminal. Tether selects the **existing browser tab**: it does not navigate, reload the diff, focus the Firefox window, or move keyboard input. Selecting a PR does not switch terminals.

## Try it on Linux

Use Firefox, distro-installed `/usr/bin/ptyxis`, and a desktop exposing Ptyxis through AT-SPI (GNOME Wayland is the initial target). The native host uses `/usr/bin/python3`, PyGObject and the Atspi 2.0 typelib; on Ubuntu the latter packages are `python3-gi` and `gir1.2-atspi-2.0`. No OMP plugin, browser login or terminal configuration is required.

1. From this checkout, run `./install.py` as your desktop user. For Snap or Flatpak Firefox, use `./install.py --sandboxed` with your distribution's [native messaging proxy](https://github.com/flatpak/xdg-native-messaging-proxy) already installed. Review that project's security notes before enabling the proxy.
2. Open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on**, and select the `tab-tether.xpi` printed by the installer. Pin Tab Tether from Firefox's Extensions menu for easy access. This is an unsigned preview: Firefox removes a temporary add-on on restart.
3. Open a GitHub PR in Firefox. Click the Tab Tether toolbar button on that tab, then focus the intended Ptyxis terminal within 30 seconds. If Firefox asks whether to allow the native host, review the request first; retry pairing if it expires.
4. Repeat for a second PR and terminal. Switch between those terminals. Each paired PR becomes the selected tab in its own Firefox window. Clicking the toolbar button on a paired PR removes its pair.

Pairs live in memory. Closing or leaving the paired PR, restarting the host, or reloading the add-on can require pairing again. An unpaired or ambiguous terminal does nothing. If two browser windows overlap, bring the relevant Firefox window into view yourself: Tether deliberately does not raise windows.

The toolbar badge shows `?` while waiting, `ON` when paired, or `!` after an error. Hover over the button for the reason. Click again on a waiting tab to cancel; after an error, click to retry. Only one tab can wait for a terminal at a time.

## What crosses the boundary

The Firefox extension recognizes GitHub PR URLs and keeps their tab IDs in the browser. The host observes window/terminal identity and focus through accessibility metadata. Native messages carry pairing IDs, not URLs, page content, terminal output, or keystrokes. No server, credentials, browsing history, or persistent pair database is required.

## Update or remove

To update, rerun the installer from the desired revision and reload the temporary add-on. To remove it, click **Remove** in `about:debugging`, delete `~/.mozilla/native-messaging-hosts/org.omp.tab_tether.json`, and remove the two installed files (`tab_tether.py` and `tab-tether.xpi`) under `${XDG_DATA_HOME:-$HOME/.local/share}/omp-tab-tether/`. This host has its own registration; other Firefox hosts need no changes.

## Development checks

Run `make test` with system Python and Node.js. `make lint` checks Python with Ruff and JavaScript with Biome; put `ruff` (0.14.6) and `biome` (2.3.8) on `PATH`. Neither tool is installed on a user's machine by `install.py`. See the [changelog](CHANGELOG.md) for the preview scope.
