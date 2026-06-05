# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

MaxBridge-Assistant patches the Quixel Bridge ↔ 3ds Max integration so it works on 3ds Max 2024/2025+ (the official plugin caps at 2023 and was not updated for the PySide2→PySide6 / MaxPlus-removal changes in Max 2025). The repo ships two things:

1. **A standalone Windows GUI tool** (`app/`) that downloads and installs patched MSLiveLink plugin files into a user's Megascans Library folder, then writes a `Quixel.ms` MAXScript bootstrap into each detected 3ds Max version's `scripts/startup`.
2. **The patched plugin files themselves** (`modified/`), provided alongside the unmodified Quixel sources (`original/`) so users can apply them by hand without running the app.

The README's "Manual Method" section is the source of truth for what the app automates — read it before changing install logic.

## Build & run

There is no test suite, no linter, and no package manager beyond `pip`. Three versioned variants of the app coexist in `app/`:

| File | UI toolkit | Requirements | Build script |
|---|---|---|---|
| `MaxBridge_Assistant.py` (v1) | PyQt5 | `requirements.txt` | (none — predates the batch files) |
| `MaxBridge_Assistant_v2.py` | PyQt6 | `requirements_v2.txt` | `nuitka-compilation.bat` |
| `MaxBridge_Assistant_v3.py` | PySide6 | `requirements_v3.txt` | `nuitka-compilation_v3.bat` |

**v3 is the current version.** When in doubt, edit `MaxBridge_Assistant_v3.py` and ignore v1/v2 (they are kept for users who can't use the newer build).

Run from source (from `app/`):
```powershell
pip install -r requirements_v3.txt
python MaxBridge_Assistant_v3.py
```

Build the distributable `.exe` (from `app/`):
```powershell
.\nuitka-compilation_v3.bat
```
This produces a Nuitka onefile in `app/dist/` with PySide6 bundled and the icon embedded. The v2 batch is identical except it uses the PyQt6 plugin.

`MaxBridge_Assistant_Hash_Generator.py` is a one-off helper for computing SHA-256 hashes of patched files when updating the remote manifest (see below). It has no CLI — uncomment the print at the bottom or import the function.

## Install-flow architecture

The app does **not** ship the patched plugin files inside the binary. At runtime it fetches a JSON manifest from this GitHub repo (`resources/download_urls_v2.json`, URL hard-coded in `MaxBridgeAssistant.__init__`) which lists:

- `plugin_version` — the Quixel plugin version string (e.g. `"5.6"`)
- `files[]` — each with `url`, `name`, `hash` (SHA-256), and `destination`

The flow in `MaxBridge_Assistant_v3.py`:

1. **Detect** installed Max versions by listing `%LOCALAPPDATA%\Autodesk\3dsMax\*` — checkbox grid is built from these.
2. **Fetch** the manifest (`fetch_plugin_version` + `download_files`), then download each file into a temp folder, hashing as it goes. Existing files with matching hashes are skipped. Downloads run on `QThreadPool` via `DownloadRunnable`; `handle_download_complete` waits until every thread finishes before proceeding.
3. **Prepare library** (`prepare_library`): wipes `<MegascansLibrary>/support/plugins/max/<plugin_version>/`, then for each downloaded file, substitutes `{plugin_version}` in its `destination` and either extracts (if `.zip`) or copies into `<MegascansLibrary>/<destination>`.
4. **Write `Quixel.ms`** (`create_quixel_files`) into every selected Max version's `<lang>/scripts/startup/` folder. This MAXScript single-liner `exec`s the patched `MS_API.py` from the library on Max startup — that's what wires Bridge into Max.
5. **Strip Windows file attributes** (`ensure_local_appdata_attributes`): Windows 11 24H2 silently adds the System attribute to `%LOCALAPPDATA%`, which breaks 3ds Max script access. The app recursively clears Hidden/System/Readonly on `%LOCALAPPDATA%`, the `Autodesk` folder, and the entire `3dsMax` subtree via `kernel32.SetFileAttributesW`. v1 did not do this; v2+ do — this is the documented reason to prefer v2+ unless the user explicitly doesn't want their AppData attributes touched.

Key consequence for changes: **when Quixel ships a new plugin version, no code change is needed — only the remote `download_urls_v2.json` and the patched files it points at.** The `{plugin_version}` placeholder in `destination` is what makes this work.

## The patched plugin files

`modified/max/5.5/MSLiveLink/MS_API.py` is the current hand-patched MS_API; compare against `original/max/5.5/...` and `original/max/5.6/...` to see what changed. `modified/56.zip` bundles the 5.6 plugin folder. `modified/plugin_versions_12.json` and `plugin_versions_13.json` are patched versions of Quixel Bridge's own plugin manifest (its `supportedversions` array originally caps Max at 2023; these extend it through 2027). The manual install in the README replaces this file in `<MegascansLibrary>/support/plugins/`.

`original/` is reference-only — those files are pulled from a real Bridge install for diffing. Don't edit them.

## Conventions to preserve

- The Megascans library path the user picks must match Bridge's library setting **exactly** — the app does not validate this; it just writes there.
- All install destinations are computed relative to the selected library; never hard-code absolute Megascans paths.
- File hashes in the manifest are SHA-256, hex-encoded lowercase (see `DownloadRunnable.calculate_file_hash`).
- When adding new files to the install set, update the remote manifest's `files[]` — don't add them as resources inside the Nuitka build.
