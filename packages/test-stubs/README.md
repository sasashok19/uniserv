# test-stubs

`.http` request files and mock seed scripts used during development.

## Files
- `health.http` — hits the health endpoint of every service (use now to
  confirm the scaffold is up).

## Phase 1
Per-feature `.http` stubs and the mock-data seed scripts are added alongside
each feature. Seeding runs automatically when `APP_ENV=development`.

```
test-stubs/
├── health.http       # health checks for all services
└── seed/             # mock data seed scripts (added per feature)
```
