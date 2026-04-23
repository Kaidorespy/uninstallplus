# Uninstall+

![Status](https://img.shields.io/badge/status-100%25-brightgreen)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**The uninstaller Windows should have shipped with.**

Uninstall programs AND hunt down the leftover files, folders, and registry entries they leave behind.

## Features

- **Clean Uninstall** — Runs native uninstaller, then scans for leftovers
- **Leftover Scanner** — Finds residual files in AppData, ProgramData, Program Files, and Registry
- **Manual Scan** — Search for leftovers from programs already uninstalled (retroactive cleaning)
- **Broken Uninstaller Detection** — Greys out missing uninstallers, guides you to scan instead
- **Steam Game Labels** — Clearly marks Steam games so you don't accidentally launch Steam
- **Recent History** — Track what you've uninstalled with re-scan capability
- **Smart Filtering** — Ignores generic words to avoid false positives
- **Admin Auto-Elevation** — Requests admin on launch for full cleanup power

## Usage

1. Run `main.py` (will request admin)
2. Select a program from the list
3. Click **Uninstall** to run native uninstaller
4. Review and clean leftovers
5. Use **Manual Scan** for programs already uninstalled

## Requirements

- Windows 10/11
- Python 3.10+
- customtkinter

```
pip install customtkinter
```

## Why?

Because CCleaner got bloated, Revo wants money, and Windows Add/Remove Programs leaves crumbs everywhere.

No nags. No subscriptions. No bullshit.
