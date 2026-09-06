# Vector 1A 1.6.0-alpha62

## Director resume

- Adds `POST /v1/resume` to the loopback Director API.
- Resume uses Vector's existing `resume()` path and returns the engine to Buffering; it does not invent or force output without incoming signal.
- `/v1/stop` remains a true zero-output stop and `/v1/neutral` remains separate.
- Intended to pair with Gwendolyn Direct Voice v0.14 for grounded stop -> restart conversations.
