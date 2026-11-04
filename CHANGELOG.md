# Changelog

## 0.1.0 — 2026-11-04

- Rule-based (FR/EN) and LLM planners; LLM output validated, unknown entities dropped.
- Policy: allow/deny/confirm globs, per-domain services, temperature limits, quiet hours, volume cap, action cap.
- Confirmation flow with ids and TTL; `--yes` for scripted use.
- Execution with state verification and JSONL audit; dry-run mode.
- CLI (`ask`, `entities`, `check`, `serve`), FastAPI (`/ask`, `/confirm/{id}`, `/pending`), Docker.
- 18 tests against a fake Home Assistant REST API.
