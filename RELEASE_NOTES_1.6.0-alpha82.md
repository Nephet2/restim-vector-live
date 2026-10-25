# Vector 1A 1.6.0-alpha82

Fixes stale MFP warnings and connection panels shifting as status messages change.

## Fixed
- The MFP banner now reflects current listener health. A historical stream error no longer prevents a recovered input from showing Receiving.
- Intentionally closing a replaced MFP stream no longer emits a misleading socket failure. Unexpected errors from the active stream remain in Connection log.
- TCP/UDP listener failures remain visible even when the other transport is receiving.
- Connection panels use equal stable columns. Status lines fill their existing space without requesting additional width, and section summaries clip rather than pushing adjacent controls. Detailed messages remain in Connection log.

## Downloads and upgrade
Download the Windows executable ZIP for use without Python, or the source ZIP for Python 3.11+. Extract the entire executable ZIP and keep _internal beside the executable. Both editions retain folder-local profile/Vector1A/settings.json. Copy your existing settings file into the new folder to preserve connection ports and preferences; the generic defaults do not know your local ReStim port.

Alpha81 socket callback deadlock fix and alpha80 connection hardening are retained. No motion, intensity, or output mapping changes.

## Validation
Windows regression checks cover recovery from stale warnings, intentional stream replacement versus real failures, and actual Tk panel/control geometry under alternating short/long status messages at 980, 1360 and 1920 pixel window widths. The full suite runs on Python 3.11, 3.13 and 3.14 before packaging. Both ZIPs are checked and the extracted executable smoke-tested. Physical stimulation hardware is not exercised.
