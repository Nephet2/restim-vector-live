# Vector 1A 1.6.0-alpha60

## Vector-backed controller state for Gwendolyn PTT

- Adds a read-only loopback `GET /v1/controller` Director endpoint.
- The endpoint reports Windows XInput connection state, LB state, D-pad state, `ptt_candidate`, and `lb_dpad_active`.
- LB alone is exposed as a push-to-talk candidate. LB+D-pad remains an existing Vector control gesture and is explicitly not a PTT candidate.
- Controller release transitions are exposed, not only press edges.
- `/v1/state` also includes the same compact controller snapshot.
- No signal-generation, routing, synchronization, safety-limit, or existing controller-command behaviour is changed.
