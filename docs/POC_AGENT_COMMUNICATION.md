# Direct Agent Communication POC

Branch: `POC`, based on `professional-ui`. **Experimental; do not merge into production without additional safeguards.**

## Goal

Demonstrate that Developer and Tester can exchange messages without an Executive-mediated
turn loop. An independent worker handles each recipient inbox. The room transcript is not
the dispatch mechanism. SQLite persists queued/processed messages, sender, recipient,
message ID, response linkage, and activity. The GET endpoint allows status requests while
other workers run.

## Run

Use the existing runtime development launcher, or start the FastAPI runtime as usual.
This branch includes the POC router in `runtime/app/main.py`.

POST `/api/poc-collaboration/start` with JSON
`{"task":"Build and test a login API"}`.

GET `/api/poc-collaboration/status` to inspect all POC messages, per-agent state,
and worker liveness. Expected message chain:

1. user -> developer: START DEMO
2. developer -> tester: implementation ready
3. tester -> developer: test failed
4. developer records receipt of feedback

POST `/api/poc-collaboration/messages` with
`{"sender":"user","recipient":"tester","content":"What is your status?"}`
to send a separate message while the worker service is running.

POST `/api/poc-collaboration/stop` to stop in-process workers.
Tests (from repo root, with runtime dependencies installed):
`cd runtime && python -m pytest tests/test_poc_collaboration.py -q`

## What is proven versus not proven

- Demonstrates persisted FIFO inbox, independent background consumers, direct worker-to-worker
  delivery, status snapshot, and restart recovery of queued messages.
- **Scripted agents**, no LLM, LangGraph, or actual coding/testing tools.
- This does **not** prove interruption of an in-flight LLM call or tool operation.
- Single-process workers, not durable distributed workers. Crash during a claim can leave
  a message `processing`; production requires lease/timeout reclaim and idempotency.
- Not production-safe: POC routes currently rely on the enclosing app's access boundary;
  do not deploy publicly without user authentication, per-project authorization,
  sender identity derived from authenticated context, rate limits, and isolation.
- The POC shares the main runtime's data directory but uses a separate database.
  It does not change existing meeting-room collaboration or permission policy.

## Next steps

Replace scripted handlers with LLM-facing agent adapters and the trusted tool executor;
integrate account/project/room identity, DB-enforced authorization, agent inboxes and
delivery acknowledgements, and UI live event subscriptions. Then add LangGraph for
workflow state, checkpointing and orchestration separately from messaging.
