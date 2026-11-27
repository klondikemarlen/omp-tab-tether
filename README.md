# OMP Tab Tether

Pair Firefox pull request tabs with their corresponding Ptyxis terminals.

- [Try the unsigned Linux preview](docs/linux-preview.md): prerequisites, pairing, privacy, and removal.
- [Changelog](CHANGELOG.md)

## Development checks

Run `make test` with system Python and Node.js. `make lint` checks Python with Ruff and JavaScript with Oxlint; put `ruff` (0.14.6) and `oxlint` (1.33.0) on `PATH`. Neither tool is installed by `install.py`.
