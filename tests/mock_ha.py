"""A fake Home Assistant REST API: enough states and services to exercise the agent end to end."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

TOKEN = "test-token"

INITIAL: dict[str, dict[str, Any]] = {
    "light.salon": {"state": "off", "attributes": {"friendly_name": "Lumière salon", "brightness": 0}},
    "light.cuisine": {"state": "on", "attributes": {"friendly_name": "Lumière cuisine", "brightness": 200}},
    "light.chambre": {"state": "off", "attributes": {"friendly_name": "Chambre"}},
    "switch.machine_a_laver": {"state": "off", "attributes": {"friendly_name": "Lave-linge"}},
    "switch.boiler_main": {"state": "on", "attributes": {"friendly_name": "Chaudière"}},
    "cover.volet_salon": {"state": "open", "attributes": {"friendly_name": "Volet salon", "position": 100}},
    "cover.garage_door": {"state": "closed", "attributes": {"friendly_name": "Porte garage"}},
    "climate.thermostat": {
        "state": "heat",
        "attributes": {
            "friendly_name": "Thermostat",
            "temperature": 19.0,
            "current_temperature": 18.4,
            "hvac_mode": "heat",
        },
    },
    "lock.porte_entree": {"state": "locked", "attributes": {"friendly_name": "Porte d'entrée"}},
    "media_player.salon_tv": {
        "state": "playing",
        "attributes": {"friendly_name": "TV salon", "volume_level": 0.3},
    },
    "camera.entree": {"state": "idle", "attributes": {"friendly_name": "Caméra entrée"}},
    "sensor.temperature_exterieure": {
        "state": "11.2",
        "attributes": {"friendly_name": "Température extérieure", "unit_of_measurement": "°C"},
    },
    "scene.soiree": {"state": "scening", "attributes": {"friendly_name": "Scène soirée"}},
}

TRANSITIONS = {
    ("light", "turn_on"): "on",
    ("light", "turn_off"): "off",
    ("light", "toggle"): None,
    ("switch", "turn_on"): "on",
    ("switch", "turn_off"): "off",
    ("cover", "open_cover"): "open",
    ("cover", "close_cover"): "closed",
    ("lock", "lock"): "locked",
    ("lock", "unlock"): "unlocked",
    ("media_player", "media_pause"): "paused",
    ("media_player", "media_play"): "playing",
    ("media_player", "turn_off"): "off",
    ("climate", "set_temperature"): "heat",
    ("scene", "turn_on"): "scening",
}


class MockHA:
    def __init__(self) -> None:
        self.states = json.loads(json.dumps(INITIAL))
        self.calls: list[dict[str, Any]] = []
        self.fail_services: set[str] = set()
        self.flaky_entities: set[str] = set()  # service call "succeeds" but state does not change
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence
                pass

            def _send(self, code: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self) -> bool:
                if self.headers.get("authorization") != f"Bearer {TOKEN}":
                    self._send(401, {"message": "Unauthorized"})
                    return False
                return True

            def do_GET(self) -> None:  # noqa: N802
                if not self._auth():
                    return
                if self.path == "/api/":
                    return self._send(200, {"message": "API running."})
                if self.path == "/api/states":
                    return self._send(200, [{"entity_id": k, **v} for k, v in mock.states.items()])
                if self.path.startswith("/api/states/"):
                    eid = self.path.rsplit("/", 1)[1]
                    if eid in mock.states:
                        return self._send(200, {"entity_id": eid, **mock.states[eid]})
                    return self._send(404, {"message": "Entity not found."})
                self._send(404, {"message": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._auth():
                    return
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "services"]:
                    domain, service = parts[2], parts[3]
                    mock.calls.append({"domain": domain, "service": service, **body})
                    if f"{domain}.{service}" in mock.fail_services:
                        return self._send(500, {"message": "boom"})
                    eid = body.get("entity_id")
                    if eid not in mock.states:
                        return self._send(400, {"message": "unknown entity"})
                    if eid in mock.flaky_entities:
                        return self._send(200, [])
                    new = TRANSITIONS.get((domain, service))
                    if new is None and service == "toggle":
                        new = "off" if mock.states[eid]["state"] == "on" else "on"
                    if new is not None:
                        mock.states[eid]["state"] = new
                    if service == "set_temperature" and "temperature" in body:
                        mock.states[eid]["attributes"]["temperature"] = body["temperature"]
                    if service == "volume_set":
                        mock.states[eid]["attributes"]["volume_level"] = body["volume_level"]
                    return self._send(200, [{"entity_id": eid, **mock.states[eid]}])
                self._send(404, {"message": "not found"})

        ThreadingHTTPServer.daemon_threads = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.05
        self.thread = Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
