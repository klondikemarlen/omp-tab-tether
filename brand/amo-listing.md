# OMP Tab Tether — Firefox Add-ons listing

## Summary

Switch to a paired Ptyxis terminal and Firefox selects its open GitHub pull request tab.

## Description

Keep the right pull request selected in Firefox as you switch between Ptyxis terminals on Linux. Pair each terminal with an open GitHub pull request tab, then switch terminals as usual.

1. Open a GitHub pull request in Firefox and click the OMP Tab Tether toolbar button.
2. Switch to the corresponding Ptyxis terminal within 30 seconds to make the pair.
3. Repeat for another terminal and pull request. Selecting either paired terminal selects its existing pull request tab in Firefox.

Tab Tether does not open, navigate, or reload tabs. It does not raise Firefox or move keyboard focus. Selecting a Firefox tab does not switch terminals. Pairs are session-only; click the toolbar button on a paired tab again to remove its pair.

**Required:** Firefox 140 or later on Linux, desktop-installed Ptyxis, a desktop that exposes it through AT-SPI (GNOME Wayland is the initial target), and the separately installed Tab Tether native host. Snap and Flatpak Firefox also need a native messaging proxy. See the [project’s Linux setup instructions](https://github.com/klondikemarlen/omp-tab-tether) before pairing.

**Privacy:** Pairing is local. The add-on recognizes GitHub pull request URLs inside Firefox; the native host uses desktop accessibility metadata to identify Ptyxis terminals and detect selection. The two exchange pairing IDs, not URLs, page contents, terminal output, or keystrokes. Tab Tether does not send data to a server.

## Listing assets

- **[Icon](amo-icon-128.png)** — 128 × 128 transparent PNG. Alt text: “OMP Tab Tether logo: an aqua terminal chevron connected to an orange tab on a dark tile.”
- **[Editorial artwork](listing-art.png)** — 1280 × 800 PNG. Caption: “Workflow diagram: switching Ptyxis terminals selects the corresponding GitHub pull request tab in Firefox.” Alt text: “Two examples: selecting terminal A selects the existing GitHub PR #42 tab; selecting terminal B selects the existing PR #57 tab. Firefox is not brought to the foreground, and keyboard focus does not move.” This is an illustration, not a screenshot of Firefox, GitHub, or Ptyxis.

## Re-export the assets

From the repository root, with Inkscape and the Noto Serif Display, Noto Sans, and Noto Mono fonts installed:

```sh
inkscape "$PWD/extension/icons/tether.svg" --export-width=128 --export-filename="$PWD/brand/amo-icon-128.png"
inkscape "$PWD/brand/listing-art.svg" --export-filename="$PWD/brand/listing-art.png"
```
