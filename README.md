# home-assistant-llm-agent

**Talk to your home in plain French or English. An LLM plans the service calls; a policy you wrote decides what it may touch, what needs your "yes", and what it can never see. Every action is verified against the real state and written to an audit log.**

[![CI](https://github.com/walidsadfi-evolurise/home-assistant-llm-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/walidsadfi-evolurise/home-assistant-llm-agent/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

*[Version française plus bas](#version-française)*

```text
$ ha-agent ask "éteins tout et ferme le volet du salon"
✓ light.turn_off → light.salon
✓ light.turn_off → light.cuisine
✓ media_player.turn_off → media_player.salon_tv
✓ cover.close_cover → cover.volet_salon
done · J'éteins Lumière salon, Lumière cuisine, TV salon, Volet salon.
  ✓ light.turn_off → light.salon  on → off
  …

$ ha-agent ask "déverrouille la porte d'entrée"
? lock.unlock → lock.porte_entree  — entity requires confirmation, service requires confirmation
Confirmer ces actions ? [y/N]: y
done · Je déverrouille Porte d'entrée.
  ✓ lock.unlock → lock.porte_entree  locked → unlocked

$ ha-agent ask "mets le chauffage à 28"
? climate.set_temperature → climate.thermostat {'temperature': 28.0}  — temperature 28.0 outside 15.0–24.0
```

The same loop as my production agents, pointed at a house instead of a CRM: **the model proposes, a policy decides, a human confirms what matters, the result is checked and logged.** It started as the washing-machine automation at home and grew into the generic version.

## How it works

```
"ferme le garage" ──► planner ──► plan (service calls) ──► policy ──► confirm? ──► execute ──► verify ──► audit
                      LLM or rules                        allow/deny/confirm   human yes    REST       read state
```

1. **Planner.** The LLM receives *only* the entities the policy lets it see (`entity_id | name | state | attrs`) and must return JSON service calls — never code. Unknown or invented `entity_id`s are dropped and reported. A **rule-based planner** handles the common commands offline (on/off, open/close, temperature, lock/unlock, scenes, "is the door locked?") and is what the tests run against.
2. **Policy** (`policy.yaml`): `allow` / `deny` globs, `confirm` globs, per-domain allowed services, temperature limits, quiet hours (speakers and the vacuum at 3 am need a yes), volume cap, max actions per request. Defaults are conservative: cameras and people are invisible, locks, alarms, garage doors and scripts always ask.
3. **Confirmation.** Risky plans get an id. Confirm from the CLI prompt, `--yes`, or `POST /confirm/{id}` (5-minute TTL). Nothing is sent to Home Assistant before that.
4. **Execute & verify.** Each service call is made over the REST API, then the entity state is read back and compared with the expected state (`light.turn_on → on`). "Succeeded but the light is still off" is reported, not hidden.
5. **Audit.** One JSON line per request: plan, verdicts, executions with before/after states.

## Quick start

```bash
pip install -e ".[dev]"
export HA_AGENT_HA_URL=http://homeassistant.local:8123
export HA_AGENT_HA_TOKEN=…            # Profile → Security → Long-lived access tokens
ha-agent check                          # connectivity + how many entities are visible/controllable
ha-agent entities --domain light
ha-agent ask "allume la cuisine" --dry-run
ha-agent ask "allume la cuisine"
```

With a model instead of the rules:

```bash
export HA_AGENT_PLANNER=anthropic HA_AGENT_LLM_MODEL=claude-haiku-4-5 HA_AGENT_ANTHROPIC_API_KEY=…
# or any OpenAI-compatible endpoint, including a local one:
export HA_AGENT_PLANNER=openai HA_AGENT_LLM_BASE_URL=http://localhost:11434/v1 HA_AGENT_LLM_MODEL=qwen2.5:7b
```

### HTTP API (for a chat UI, Telegram, or HA's conversation integration)

```bash
HA_AGENT_API_TOKEN=secret ha-agent serve --port 8090
curl -s -X POST localhost:8090/ask -H "Authorization: Bearer secret" -H 'content-type: application/json' -d '{"text":"ouvre le garage"}'
# → {"status":"pending_confirmation","confirmation_id":"a1b2c3d4", ...}
curl -s -X POST localhost:8090/confirm/a1b2c3d4 -H "Authorization: Bearer secret"
```

Docker: `docker compose -f deploy/compose.yml up -d` (see `.env.example`). Runs fine next to Home Assistant on the same box.

## Policy example

```yaml
allow: [light.*, switch.*, cover.*, climate.*, media_player.*, lock.*]
deny: [camera.*, person.*, switch.*boiler*, switch.*freezer*]
confirm: [lock.*, cover.*garage*, script.*]
confirm_services: [lock.unlock, alarm_control_panel.alarm_disarm]
climate: { min_temperature: 15, max_temperature: 24 }
quiet_hours: { start: "22:30", end: "07:00", confirm_domains: [media_player, vacuum] }
max_actions_per_request: 8
```

## Design notes

- **Least privilege for the model.** It cannot discover entities outside the allowlist because it never sees them. Denied ≠ hidden-but-refused: hidden.
- **Confirmation lives outside the model.** The policy decides what needs a yes; the model can't talk its way around it, and `--yes` is a human flag, not a model output.
- **Verification is part of execution.** A 200 from `/api/services` means "accepted", not "done". Reading the state back is what tells you the garage actually closed.
- **Rules first, model second.** Most home commands are twenty verbs and a noun. The rule-based planner costs nothing, works offline and is deterministic; the LLM is for everything else.
- **No WebSocket, no events, no automations.** This is an actuator with manners, not a replacement for Home Assistant's automation engine. Put it behind a conversation agent or a bot.

## Project layout

```
src/haagent/
  models.py    Entity, Action, Plan, Verdict, Execution, Outcome
  ha.py        REST client (states, state, call_service)
  policy.py    Policy (allow/deny/confirm/limits/quiet hours) → Verdict
  planner.py   RuleBasedPlanner (FR/EN), LLMPlanner (JSON, validated, hallucination filter)
  agent.py     handle / confirm / execute+verify / audit
  api.py       FastAPI   cli.py  ha-agent ask | entities | check | serve
policy.yaml    example policy      tests/mock_ha.py  fake Home Assistant REST API
```

## Roadmap

- [ ] WebSocket subscription for faster verification and "wait until the cover is closed"
- [ ] Home Assistant `conversation` custom component wrapper (use it from the HA UI and voice)
- [ ] Multi-step routines ("mode cinéma") compiled to scenes with a diff preview
- [ ] Per-user policies (kids can do lights, not the alarm)

## License

MIT — see [LICENSE](LICENSE). Built by [Walid Sadfi](https://www.malt.fr/profile/walidsadfi), Forward Deployed Engineer · agents IA & WooCommerce.

---

## Version française

**Parlez à votre maison en français ou en anglais. Un LLM planifie les appels de service ; une politique que vous avez écrite décide ce qu'il peut toucher, ce qui demande votre « oui », et ce qu'il ne voit jamais. Chaque action est vérifiée sur l'état réel et journalisée.**

La même boucle que mes agents en production, pointée sur une maison plutôt qu'un CRM : **le modèle propose, la politique décide, un humain confirme ce qui compte, le résultat est vérifié et consigné.** Né de l'automatisation du lave-linge à la maison, devenu la version générique.

- **Moindre privilège** : le modèle ne voit que les entités autorisées ; caméras et personnes sont invisibles, pas « refusées ».
- **Confirmation hors du modèle** : serrures, alarme, garage, scripts, température hors limites, enceintes la nuit → un humain dit oui (CLI, `--yes`, ou `POST /confirm/{id}`).
- **Vérification** : après chaque appel, l'état est relu et comparé à l'attendu ; « accepté mais la lumière est toujours éteinte » est signalé.
- **Règles d'abord, modèle ensuite** : les commandes courantes marchent hors ligne, sans clé ; le LLM prend le reste (Anthropic, OpenAI, ou un modèle local via Ollama).
- **Journal d'audit** JSONL, API HTTP, CLI, Docker, 18 tests contre une fausse API Home Assistant.

```bash
ha-agent check
ha-agent ask "allume la cuisine" --dry-run
ha-agent ask "déverrouille la porte d'entrée"     # demande confirmation
```

Un agent qui agit sur le monde réel — maison, boutique, CRM — se construit avec exactement ces garde-fous. [Parlons-en sur Malt](https://www.malt.fr/profile/walidsadfi).
