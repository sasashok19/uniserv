# Running UniServe Locally (without Docker)

UniServe currently defaults to a **local-first** dev workflow: every service
runs as a bare process on your machine instead of in Docker. Docker Compose
remains fully supported and can be re-enabled at any time — see
["Switching between local and Docker"](#switching-between-local-and-docker)
below. The choice is controlled by a single flag, `RUN_MODE`.

---

## Prerequisites

- Java 21 (Temurin or GraalVM)
- Maven 3.9+ on your `PATH` (there is no committed Maven Wrapper in this repo
  yet, so `mvn` — not `./mvnw` — is what `scripts/dev-local.sh` runs)
- Python 3.11+
- Node.js 20+
- Valkey or Redis (the event bus) — [Memurai](https://www.memurai.com/get-memurai)
  on Windows, Homebrew on macOS/Linux; see below for details and alternatives

### Installing Valkey/Redis

`scripts/dev-local.sh` checks port `6379` first and skips this step entirely
if something is already listening there — so whichever option below you
pick, there is nothing else to configure; the script (and every service's
`redis://localhost:6379` URL) just finds it.

**Recommended (Windows): [Memurai](https://www.memurai.com/get-memurai)** —
a native Windows, Redis-protocol-compatible server that installs and runs as
a background Windows service (`sc query Memurai` shows `STATE: RUNNING`), so
it's simply always there — no WSL, no Docker, nothing to launch per session.
This is what this repo's own dev environment uses. **Verified working**,
including the exact commands the event bus depends on
(`XADD`/`XGROUP CREATE`/`XREADGROUP`/`XACK`/`XPENDING`, not just plain
`GET`/`SET`) — see the note on fake/mock Redis servers below for why that
distinction matters.

**macOS / Linux (Homebrew):**
```bash
brew install valkey   # or: brew install redis
```

**Alternative (Windows): WSL2** — install a WSL2 distro, then inside it:
`sudo apt update && sudo apt install -y redis-server`. WSL2 forwards
`localhost:6379` to Windows automatically, so `dev-local.sh` running in Git
Bash on the Windows side will find it. Real Redis, same guarantees as
Memurai; more setup if you don't already use WSL2 for anything else.

**Alternative: Docker, just for Valkey** — if you'd rather not install
either of the above and already have Docker available for this one piece:
`docker run -d --name valkey -p 6379:6379 valkey/valkey:8-alpine`. Uses
Docker only for the cache/event-bus, not the app services.

> **Don't use a pure-Python/JS "fake Redis" reimplementation** (e.g.
> `fakeredis`) as a shortcut here. We tried exactly that — it looked
> promising (a real TCP server, no install needed at all) but failed a real
> test: `XREADGROUP` — the call `BaseConsumer.consume()` makes on every
> poll — returns a malformed reply (`Protocol Error: b'%1'`, a RESP3 map
> leaking into a RESP2 connection) under both `server_type="redis"` and
> `server_type="valkey"`. Plain key/value commands (`GET`/`SET`/`PING`) work
> fine on these reimplementations, which is exactly what makes them a trap —
> everything looks fine until a consumer silently stops receiving events.
> Memurai and WSL2/Homebrew Redis are the real thing, not a reimplementation,
> so they don't have this class of gap.

---

## One-time setup

Each service reads a `.env.local` file (gitignored — never commit it).
Working copies with sensible dev defaults already exist in this repo; to
regenerate them from scratch (e.g. on a fresh clone) copy the `.example`:

```bash
cp services/api-gateway/.env.local.example services/api-gateway/.env.local
cp services/db-writer/.env.local.example     services/db-writer/.env.local
cp services/ai-core/.env.local.example       services/ai-core/.env.local
cp apps/dashboard/.env.local.example          apps/dashboard/.env.local
```

Then, for the AI conversation feature to use a real LLM instead of the
Phase-1 rule-based fallback, set `OPENAI_API_KEY` and `OPENAI_ASSISTANT_ID`
either in `services/ai-core/.env.local` or in `services/ai-core/.env` (both
are loaded, `.env` first, `.env.local` as an overlay — see
`services/ai-core/app/config.py`). Leaving them blank is fine; ai-core falls
back to rule-based classification (`/api/v1/internal/test-llm-health` reports
`llmAvailable: false`).

---

## Start everything

```bash
./scripts/dev.sh
```

This reads `RUN_MODE` (see below) and either starts every service locally or
falls back to Docker Compose. To run the local stack directly without the
dispatcher:

```bash
chmod +x scripts/dev-local.sh   # first time only
./scripts/dev-local.sh
```

It starts, in order: Valkey/Redis → DB Writer (waits for it to be ready,
since everything else calls it) → API Gateway → AI Core → Dashboard. Each
service's own output goes to `scripts/<service>.log`; watch those if
something doesn't come up.

## Stop everything

```bash
./scripts/dev-stop.sh
```

(Or just `Ctrl+C` the terminal running `dev-local.sh` — it cleans up after
itself via a trap.)

## Ports

Identical in both modes, so nothing else (dashboard config, `.http` test
stubs, docs) needs to change when you switch:

| Service | Port |
|---|---|
| api-gateway | 8080 |
| db-writer | 8090 |
| ai-core | 8001 |
| dashboard | 3000 |
| valkey/redis | 6379 |

> Note: a couple of the feature specs under `docs/` mention `8081` for
> db-writer — this project standardised on **8090** from the start (avoids a
> port clash with api-gateway on the host) and both local and Docker mode use
> it consistently. See `docs/04_DB_WRITER_SERVICE.md`'s Phase 1 notes.

---

## Switching between local and Docker

A single flag, `RUN_MODE`, controls it:

```bash
# one-off, for this run only
RUN_MODE=docker ./scripts/dev.sh

# persistent — copy .env.example to .env at the repo root and set:
RUN_MODE=docker
```

`RUN_MODE=docker` runs the pre-existing Docker Compose stack directly:

```bash
docker compose -f infrastructure/compose/docker-compose.dev.yml up --build
```

`RUN_MODE=local` (the default) runs `scripts/dev-local.sh`. Nothing about the
services themselves changes between modes — same ports, same environment
variable names, same health-check paths — only *how* they're launched.

---

## Verifying it's up

```bash
curl http://localhost:8080/api/v1/health     # api-gateway
curl http://localhost:8090/q/health/ready    # db-writer
curl http://localhost:8001/api/v1/health     # ai-core
open http://localhost:3000                   # dashboard (or just visit it)
```

`packages/test-stubs/health.http` hits every health endpoint (including
`/q/health/live` / `/q/health/ready` on the Quarkus services) if you want the
full sweep.
