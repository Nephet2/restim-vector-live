# Vector 1A 1.6.0-alpha80 — connection reliability

Ports the connection fixes used in Steve's local Vector installation onto the published alpha79 source.

## Fixed
- MFP can reconnect when a script/character change leaves the previous TCP or WebSocket stream open. The newest stream replaces the old one; stale stream messages are ignored.
- ReStim WebSocket ping frames receive a masked pong reply. Close frames trigger reconnection; incoming frames are drained and buffered across partial reads.
- ReStim handshake failures close their socket and have a bounded handshake deadline.
- Plain TCP ReStim output no longer references undefined pressure-control variables and now updates transmission health counters.

Alpha79 already included supervised listeners, background reconnection and independent latest-frame output lanes. Those remain in place. Stop/manual disconnect behavior is retained. These fixes address Vector's network layer; they cannot guarantee recovery from a separate ReStim-to-FOCstim hardware or driver fault.

## Upgrade
Extract the Windows ZIP to a new folder and run start-vector1a.bat with Python 3.11 or newer. Copy your previous profile/Vector1A/settings.json if you want to retain your settings. No personal profiles or Bluetooth addresses are included.

This release retains alpha79's Howl and Civet features. Unrelated local pulse-effect and script-analysis experiments are excluded.

## Validation
The release workflow runs the full unittest suite on Windows, including new regressions for overlapping MFP connections, fragmented WebSocket ping/close frames and TCP send health. Publication occurs only after the suite and package build succeed. Physical stimulation hardware is not exercised.
