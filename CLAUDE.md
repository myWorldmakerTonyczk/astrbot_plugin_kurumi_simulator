# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

An AstrBot plugin ("久留美模拟器" / Kurumi Simulator): AI agents trade a **paper** forex account against real public quotes. Nothing is ever sent to a broker. Python 3.10+, one runtime dependency (`aiohttp`); AstrBot itself is provided by the host. The UI is a static AstrBot View page (vanilla JS, no build step). User-facing text and docs are Chinese; module docstrings/comments are English.

## Commands

Run from the repo root (tests import `src.*` as a top-level package):

```bash
python -m unittest discover -s tests -v          # full offline unit suite
python -m unittest tests.test_engine.LedgerTests.test_name -v   # single test
ruff check .                                     # lint (repo has ruff cache; no config file)
```

Integration harnesses (not part of `discover`; each prints a `... passed` line):

```bash
python tests/runtime_check.py   # needs astrbot + starlette installed: constructors, 7 web routes x2, auth, lifecycle
python tests/smoke_view.py      # needs playwright + Edge/Chromium: drives views/dashboard with a mocked bridge
```

There is no build step, package metadata, or `pyproject.toml`. `_conf_schema.json` is intentionally `{}` (all configuration lives in the dashboard/SQLite).

## Architecture

### Entry and lifecycle
- `main.py` is the thin AstrBot `Star` subclass: declares every `@filter.llm_tool` and `@filter.on_llm_request`, then delegates to `src/` (`console`, `read_logs`, `list_instances`, `select_instance`).
- `src/plugin.py` (`KurumiMixin`) owns the lifecycle and the authenticated View API. `__init__` opens the DB and registers routes at `/{plugin_name}/{state,alerts,history,command,settings,connection-test,decision}`. Every handler fails closed on `request.username` (Dashboard login).
- A single background `loop()` runs every 10 s: refresh quotes → record candles for all six pairs → `engine.tick()` each game → launch scheduled AI decisions when `auto` is due. Tasks spawned via `spawn()` so `terminate()` can cancel them.

### Ledger core (`src/engine.py`)
- SQLite, `isolation_level=None` with explicit `transaction()` (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`). Games are JSON blobs in `games`; `logs` is append-only; `requests` gives `request_id` idempotency.
- Money is `Decimal` internally; game state stores numbers as strings (`dump()` → JSON).
- `Engine.action()` validates and mutates through `_action()`, always writes a log entry, and records rejected attempts (`status="rejected"`) without pre-committing balance changes. `revision` bumps on any write; `action_revision` bumps only on account-affecting changes and is the optimistic-concurrency token for AI decisions.
- `tick()` enforces SL/TP, margin-call logging (<100%), simulated liquidation (<50% collateral/margin, worst PnL first), and game-end rules. `mark()` maintains a deposit-adjusted equity index and drawdown.
- `quote()` refuses stale (>30 s), untradeable, or missing quotes — never fabricate a fill.

### Market data (`src/market.py`, `src/market_settings.py`)
- Three selectable adapters: `biquote` (default), `sina`, `oanda` Practice. Quote cache is in-memory only and cleared when the source/endpoint signature changes or a game has open positions.
- URL validation blocks non-HTTPS, localhost/private IPs, credentials, fragments, and non-global DNS resolution (SSRF hardening). Redirects are disabled; responses capped at 1 MB.
- `probe()` runs against an isolated `Market` instance so connection tests never touch live quotes or saved settings. `public_settings()` strips `market_key`; saved OANDA credentials are never forwarded to public sources.

### History (`src/history.py`, `src/reference_history.py`)
- Six-pair OHLC is persisted per period while the loop samples; `history_source` is separate from the execution source:
  - `"market"` — real candles from the selected quote provider (biquote/sina/OANDA), including backward pagination.
  - `"frankfurter"` — daily reference rates only (1d/1w/1M), explicitly not intraday OHLC and never used for fills.
- Cache keys include a hashed feed identity, so switching source/credentials cannot stitch different markets together. Weekly/monthly bars are aggregated in natural periods (Monday / calendar month; Sina uses UTC+8).

### Two AI execution paths
Both go through `src/trading.py:execute()` — the single write gate with `WRITE_ACTIONS`, mandatory `reason`, and a per-instance `asyncio.Lock`:
1. **Chat tools** (`src/tools.py`): resolve the caller's game via `src/identity.py`, then execute.
2. **Background decisions** (`src/ai.py`): `decide()` builds a `ToolSet`, runs `context.tool_loop_agent` with a `SilentEvent` (send is forbidden) and `max_steps=12`. It snapshots `action_revision` and rejects writes if the account changed under the model. The persona prompt is combined with `RULES`; the result summary is logged, not sent to chat.

`public_snapshot()` strips `user_binding` and restricts quotes to the six pairs before anything reaches the model or UI.

### Identity and ownership (`src/identity.py`, `src/ownership.py`)
- Users are bound by QQ, full private-chat UMO (`<platform>:FriendMessage:<id>`), or an admin-issued random ID (`krm_` + 20 hex). Bindings normalize to `sim_user_aliases`; the random ID is a bearer token stored in `sim_user_tokens` and can be rotated, which invalidates the old ID.
- Only private chats are allowed for trading tools. Selection is scoped per `umo + sender`; `sim_reference_grants` records which sessions may supply chat history to background decisions.
- Deleted instances get a tombstone in `sim_deleted_instances`; `Engine.save()` refuses to write them back.

### Dashboard (`views/dashboard/`)
- Loaded by AstrBot as a plugin view; all I/O goes through `window.AstrBotPluginView` (`apiGet`/`apiPost`), so the page has no standalone server. Keep all fetches relative to that bridge.
- `app.js` (main UI/state/polling), `history-chart.js` (Lightweight Charts 5.0.9, vendored locally with license — no CDN), `instance-catalog.js` (user-grouped catalog), `notifications.js` (alert polling/dedupe).
- Alerts are projected server-side in `src/alerts.py` from the immutable log; the client cursor lives in the browser so refreshes do not replay old notices.

## Invariants to preserve

- **Paper only.** No broker order endpoints, no real funds, no deposit/withdraw of money.
- Every state-affecting path must write a log entry (success or rejected), use transactions, and never partially apply a failed action.
- AI must not fabricate fills: tool errors are not trades, and executions require a fresh quote plus a non-empty reason.
- The AI tool surface is read-only or writes virtual money; it can never create users, raise loan limits, change rules, or deposit for itself. Deposits/pause/resume are human-only.
- Credentials (`market_key`) and `user_binding` tokens must never appear in dashboard payloads, model context, plan text, or reasons.
- Ownership is **not** fully enforced yet. All routes currently share the Dashboard-admin login, and instance grouping in the UI is presentation, not authorization. See `docs/WORKSPACES.md` before claiming multi-user isolation.
- Ownerless legacy games remain "未分配用户"; do not silently migrate them.

## Persistence

DB: `StarTools.get_data_dir("astrbot_plugin_kurumi_simulator")/ledger.sqlite3` (WAL). It may contain real market credentials — never commit/upload it (`.gitignore` covers `*.sqlite3*`). Core tables: `games`, `logs`, `requests`, `settings`, `sim_users/aliases/tokens/counters`, `sim_selections`, `sim_reference_grants`, `sim_deleted_instances`, `candles`, `history_pages`, `history_refresh`, `reference_rates`, `reference_ranges`.

## Docs map

`docs/PLAN.md` (product requirements and roadmap), `docs/PROGRESS.md` (what is/isn't implemented), `docs/VALIDATION.md` (what has actually been verified — don't overstate beyond it), `docs/WORKSPACES.md` (ownership/auth boundaries), `docs/ARTWORK.md` (bundled themed images).
