# Vector 1A 1.6.0-alpha51

## Director browser bridge polish

Alpha 51 keeps the Alpha 50 Director API unchanged in capability and adds browser-safe local access for an optional SillyTavern companion extension.

### Changed
- Director API now supports CORS preflight from local SillyTavern at `http://127.0.0.1:8000` or `http://localhost:8000`.
- Adds `OPTIONS` support for browser POST requests.
- CORS remains restricted to the local SillyTavern origins above; the Director server remains loopback-only.
- No change to signal-generation mathematics, routing, ReStim output, or Director command authority.

Vector remains fully standalone. SillyTavern/Gwendolyn remains optional.
