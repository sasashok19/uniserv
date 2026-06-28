# event-contracts

Shared event schemas (JSON Schema) for the Valkey event bus.

Event naming convention (ORCHESTRATOR): `{domain}.{entity}.{verb}` past tense,
e.g. `channel.message.received`, `complaint.ready`, `identity.resolved`.

## Phase 1
Schemas are defined in **02f_ADAPTER_CONTRACT** (the next feature after the
event bus). This package is intentionally empty at scaffold stage — only the
folder exists so services can depend on a stable location.

```
event-contracts/
└── schemas/        # *.schema.json — added in 02f_ADAPTER_CONTRACT
```
