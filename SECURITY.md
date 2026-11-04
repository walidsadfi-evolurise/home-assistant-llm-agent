# Security

Report vulnerabilities privately to walid.sadfi@evolurise.com. Acknowledgement within 72 hours.

Operating notes:

- Create a dedicated Home Assistant user for the agent and give it the long-lived token; HA has no per-entity permissions, so `policy.yaml` is your permission layer — review `allow`/`deny` before going live.
- Set `HA_AGENT_API_TOKEN` if you expose the HTTP API; keep it on your LAN or behind a reverse proxy with TLS.
- Entity names and states are sent to the configured LLM provider. For privacy, use a local model (`HA_AGENT_LLM_BASE_URL` → Ollama) or the rules planner.
