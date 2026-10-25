# Vector 1A 1.6.0-alpha81

Alpha81 adds a portable Windows app and fixes a socket-status callback deadlock while retaining alpha80's connection recovery.

## Downloads
- **Vector1A-1.6.0-alpha81-windows-exe.zip**: no Python installation required. Extract the whole ZIP and run **Vector1A-1.6.0-alpha81.exe** inside its folder. Keep the accompanying **_internal** folder beside the executable.
- **Vector1A-1.6.0-alpha81-windows.zip**: Python source edition. Run **start-vector1a.bat** with Python 3.11 or newer.
- Both downloads have SHA-256 checksum files.

## Connection reliability
ReStim connection status callbacks now execute after the socket lock is released. This prevents lock inversion when a callback reads connection health or marshals work to the interface. New regressions cover reconnect failures, failed sends, and recovery notifications. The recovery neutral is still sent before live output.

Retains alpha80's overlapping MFP connection replacement, WebSocket ping/pong and close handling, handshake cleanup, independent output lanes, and ongoing reconnection. No five-attempt reconnect limit is introduced.

## Settings and logs
Both editions use **profile/Vector1A/settings.json** inside the extracted application folder. To upgrade, close the previous instance and copy that settings file to the matching location in the new folder. Extract to a writable folder.
The executable records console diagnostics at **profile/Vector1A/logs/vector-console.log**. The in-app connection log remains available.

## Credits
Thanks to **Senorgif33** and the [Senorgif33 Vector fork](https://github.com/Senorgif33/restim-vector-live) for identifying the status-callback/socket-lock issue and demonstrating Python-free Windows distribution. This release implements callback deferral within our alpha80 networking code and uses a separate portable executable build. Existing upstream and event-work credits are retained.

## Validation
Release publication is gated on the full regression suite on Windows with Python 3.11, 3.13 and 3.14. The source compiles, both archives are built, and the executable is extracted and smoke-tested for application imports, Tk, Bleak and bundled event definitions without opening MFP/ReStim connections. No physical stimulation hardware is used.

Alpha79 Howl/Civet features remain included. Media sidecars, LAN remote control and independent secondary scripts are not added in this release.
