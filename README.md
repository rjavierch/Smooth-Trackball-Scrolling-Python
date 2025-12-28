# Smooth Trackball Scrolling (Python / evdev)

A small Linux daemon that turns trackball movement into smooth, continuous scrolling while a hotkey is held (or toggled), using `evdev` + `uinput`.
This is a Python port of **eynsai/Smooth-Trackball-Scrolling** (originally AutoHotKey).

## Overview

- Reads events from a physical mouse device under `/dev/input/event*` and (when active) converts REL X/Y movement into vertical/horizontal scroll events.
- Creates a virtual input device via `uinput` to inject scroll (and replay other) events back into the system.
- Supports multiple hotkey modes (toggle, momentary, on/off) and a configurable “panic button” to immediately exit.
- Includes smoothing, optional axis snapping, optional acceleration curve, and optional modifier emulation settings driven by `config.ini`.

## Requirements

- Linux with access to evdev input devices (`/dev/input/event*`) and `uinput`.
- Python 3 + the `python3-evdev` package.
- Root permissions are currently required because the daemon opens `/dev/input/event*`, grabs the mouse device, and creates a `uinput` virtual device.

## Running (current)

1. Install dependencies (Debian/Ubuntu/Pop!_OS):
```bash
sudo apt update
sudo apt install python3-evdev
```
`daemon.py` exits early if `python3-evdev` is missing.

2. Configure hotkeys and feel:
- Edit `config.ini` (see next section).

3. Run:
```bash
sudo python3 daemon.py
```
The script currently checks `os.geteuid()` and refuses to start unless it’s run with `sudo`.

Notes:
- The daemon attempts to locate a mouse (e.g., “Logitech Ergo M575”) and a keyboard device to listen for hotkeys.
- It grabs the mouse device so the cursor stops moving while scrolling is active, and replays events through the virtual device when appropriate.
- Logs are written to the console and also to `/tmp/smoothscroll.log`.

Security note (help wanted):
- Running with `sudo` is not ideal, and improvements are welcome (e.g., udev rules / group-based permissions, a proper systemd service, packaging).

## Configuration

The project loads configuration from `etc/smoothscroll/config.ini` if present; otherwise it falls back to `./config.ini`.

Key options in `config.ini`:

- **Hotkeys**
  - `hotkey1`: primary hotkey (can be a mouse button like `RButton` or a key like `F1`).
  - `hotkey2`: secondary hotkey used by some modes (e.g., ON/OFF).
  - `panicButton`: immediately exits when pressed.
  - `mode`: supports modes like `ONOFF`, `ONEKEYTOGGLE`, `ONEKEYMOMENTARY` (and some additional planned/mentioned mode names in the config comments).
  - `holdDuration`: threshold (ms) used to differentiate tap vs hold in the mouse-button logic path.

- **Texture (feel)**
  - `sensitivity`: scales output scroll amount (negative values invert direction).
  - `refreshInterval`: processing tick interval in milliseconds (the daemon converts it to seconds internally).
  - `smoothingWindowMaxSize`: moving-average window size used for smoothing.

- **Axis snapping / acceleration / modifiers**
  - Axis snapping parameters (`snapOnByDefault`, `snapRatio`, `snapThreshold`).
  - Acceleration parameters (`accelerationOn`, `accelerationBlend`, `accelerationScale`).
  - Optional modifier emulation flags (`addShift`, `addCtrl`, `addAlt`).

## Roadmap & contributions

Tested on **Pop!_OS 24** with scrolling speed set to **1** to approximate “high-resolution scroll” feel.

Planned / ideas:
- Add an install script + optional systemd unit (run on login / boot).  
- Improve safety: run without `sudo` (udev rules / input group / least-privilege approach).
- Restructure so the same framework can add other features (example: hotkeys for volume up/down).  
- Translate code comments to English (many comments are currently Spanish).

PRs and issues are welcome—especially around permissions/security and packaging, since the current “just run with sudo” approach is a workaround rather than a best practice.