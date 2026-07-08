from __future__ import annotations

import copy
import io
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .display import OledFontSet, render_oled_image
from .screens import BootScreen, DeckScreen, GameScreen, NetworkScreen, RecordingScreen, Screen, StorageScreen, UsbTransferScreen

WIDTH = 128
HEIGHT = 64


def _base_state(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "camera": {"connected": True, "name": "DV Cam", "device": "/dev/fw1"},
        "recording": {"active": False, "filename": None, "started_at": None, "elapsed_seconds": 0, "pid": None},
        "storage": {
            "capture_dir": "/var/lib/equip1/captures",
            "total_bytes": 128 * 1024**3,
            "used_bytes": 44 * 1024**3,
            "free_bytes": 84 * 1024**3,
            "recording_minutes_available": 252,
            "device": "/dev/sda1",
            "device_kind": "usb",
            "mount_point": "/data",
            "filesystem_type": "exfat",
        },
        "network": {
            "ip": "10.42.0.1",
            "hostname": "equip1",
            "url": "http://10.42.0.1:8000",
            "mode": "access_point",
            "ssid": "Equip-1",
            "password": "firesecret",
            "ap_ip": "10.42.0.1",
            "iface": "wlan0",
        },
        "deck": {
            "available": True,
            "status": "stopped",
            "timecode": "00:12:43:08",
            "last_command": None,
            "error": None,
        },
        "error": None,
    }


def _scenario_states() -> dict[str, dict[str, Any]]:
    boot = _base_state("boot")
    ready = _base_state("idle")
    recording = _base_state("recording")
    recording["recording"] = {
        "active": True,
        "filename": "2026-07-03_120000.dv",
        "started_at": "2026-07-03T12:00:00+00:00",
        "elapsed_seconds": 83,
        "pid": 1234,
    }
    low_storage = _base_state("idle")
    low_storage["storage"].update(
        {
            "used_bytes": 126 * 1024**3,
            "free_bytes": 2 * 1024**3,
            "recording_minutes_available": 6,
        }
    )
    no_network = _base_state("idle")
    no_network["network"] = {"ip": None, "hostname": "equip1", "url": None, "mode": "offline", "ssid": "Equip-1", "password": "firesecret", "ap_ip": None, "iface": "wlan0"}
    no_camera = _base_state("no_camera")
    no_camera["camera"] = {"connected": False, "name": None, "device": None}
    storage_full = _base_state("storage_full")
    storage_full["storage"].update({"used_bytes": 128 * 1024**3, "free_bytes": 0, "recording_minutes_available": 0})
    error = _base_state("error")
    error["error"] = {"message": "Recorder failed", "detail": "dvgrab exited 1", "at": "2026-07-03T12:00:00+00:00"}
    offline = {
        "mode": "offline",
        "recording": {"active": False, "elapsed_seconds": 0},
        "storage": {"recording_minutes_available": 0, "device_kind": "unknown"},
        "network": {},
        "error": {"message": "Daemon offline", "detail": "Connection refused"},
    }
    usb_transfer = _base_state("usb_transfer")
    return {
        "boot": boot,
        "ready": ready,
        "recording": recording,
        "low_storage": low_storage,
        "no_network": no_network,
        "no_camera": no_camera,
        "storage_full": storage_full,
        "error": error,
        "offline": offline,
        "usb_transfer": usb_transfer,
    }


SCENARIOS = _scenario_states()


class DesignerAppAdapter:
    def __init__(self, session: "DesignerSession") -> None:
        self.session = session

    @property
    def state(self) -> dict[str, Any]:
        return self.session.state

    def command(self, name: str) -> None:
        self.session.command(name)

    def next_screen(self) -> None:
        self.session.change_screen(1)


class DesignerSession:
    def __init__(self) -> None:
        self.screens: list[Screen] = [RecordingScreen(), DeckScreen(), StorageScreen(), UsbTransferScreen(), NetworkScreen(), GameScreen()]
        self.boot_screen = BootScreen()
        self.boot_duration_seconds = 3.0
        self.boot_hold_seconds = 1.1
        self.screen_index = 0
        self.scenario_name = "ready"
        self.custom_state: dict[str, Any] | None = None
        self.scenario_started_at = time.monotonic()
        self.command_log: list[str] = []
        self.fonts = OledFontSet()

    @property
    def current_screen(self) -> Screen:
        return self.screens[self.screen_index]

    @property
    def boot_elapsed(self) -> float:
        return time.monotonic() - self.scenario_started_at

    @property
    def is_booting(self) -> bool:
        return self.scenario_name == "boot" and self.boot_elapsed < self.boot_duration_seconds

    def _finish_boot_if_done(self) -> None:
        if self.scenario_name == "boot" and not self.is_booting:
            self.scenario_name = "ready"
            self.scenario_started_at = time.monotonic()

    @property
    def render_screen(self) -> Screen:
        self._finish_boot_if_done()
        return self.boot_screen if self.is_booting else self.current_screen

    @property
    def state(self) -> dict[str, Any]:
        self._finish_boot_if_done()
        state = copy.deepcopy(self.custom_state if self.custom_state is not None else SCENARIOS[self.scenario_name])
        if state.get("mode") == "recording":
            recording = state.setdefault("recording", {})
            recording["elapsed_seconds"] = int(recording.get("elapsed_seconds") or 0) + int(
                time.monotonic() - self.scenario_started_at
            )
        return state

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise KeyError(name)
        self.scenario_name = name
        self.custom_state = None
        self.scenario_started_at = time.monotonic()
        if name == "boot":
            self.screen_index = 0

    def set_custom_state(self, state: dict[str, Any]) -> None:
        self.custom_state = state
        self.scenario_name = "custom"
        self.scenario_started_at = time.monotonic()

    def set_screen(self, index: int) -> None:
        if index < 0 or index >= len(self.screens):
            raise IndexError(index)
        self.screen_index = index
        self._notify_enter()

    def change_screen(self, delta: int) -> None:
        self.screen_index = (self.screen_index + delta) % len(self.screens)
        self._notify_enter()

    def _notify_enter(self) -> None:
        on_enter = getattr(self.current_screen, "on_enter", None)
        if on_enter is not None:
            on_enter(DesignerAppAdapter(self))

    def button(self, name: str) -> None:
        app = DesignerAppAdapter(self)
        if name == "up":
            if not self.current_screen.on_up(app) and self.current_screen.can_navigate(self.state):
                self.change_screen(-1)
        elif name == "down":
            if not self.current_screen.on_down(app) and self.current_screen.can_navigate(self.state):
                self.change_screen(1)
        elif name == "select":
            self.current_screen.on_select(app)
        else:
            raise KeyError(name)

    def command(self, name: str) -> None:
        self.command_log.insert(0, f"{time.strftime('%H:%M:%S')} {name}")
        del self.command_log[20:]
        if name == "start-recording":
            self.set_scenario("recording")
        elif name in {"stop-recording", "clear-error", "usb-storage-stop"}:
            self.set_scenario("ready")
        elif name == "usb-storage-start":
            self.set_scenario("usb_transfer")
        elif name == "storage-switch-usb":
            if self.custom_state is None:
                self.custom_state = self.state
                self.scenario_name = "custom"
            storage = self.custom_state.setdefault("storage", {})
            storage.update({"device": "/dev/sda1", "device_kind": "usb", "mount_point": "/data", "filesystem_type": "exfat"})
        elif name == "storage-switch-sd":
            if self.custom_state is None:
                self.custom_state = self.state
                self.scenario_name = "custom"
            storage = self.custom_state.setdefault("storage", {})
            storage.update({"device": "/dev/mmcblk0p2", "device_kind": "sd", "mount_point": "/data", "filesystem_type": "exfat"})
        elif name.startswith("deck-"):
            if self.custom_state is None:
                self.custom_state = self.state
                self.scenario_name = "custom"
            deck = self.custom_state.setdefault("deck", {})
            deck["last_command"] = name.removeprefix("deck-")
            deck["status"] = deck["last_command"]

    def summary(self) -> dict[str, Any]:
        self._finish_boot_if_done()
        return {
            "screenIndex": self.screen_index,
            "screenName": self.current_screen.title,
            "screens": [screen.title for screen in self.screens],
            "scenario": self.scenario_name,
            "scenarios": list(SCENARIOS.keys()),
            "state": self.state,
            "commandLog": self.command_log,
        }


session = DesignerSession()
app = FastAPI(title="Equip-1 Designer", version="0.1.0")


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Equip-1 ◯ DESIGNER</title>
  <style>
    :root { color-scheme: light; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { min-height: 100vh; margin: 0; background: #000; color: #213040; display: grid; place-items: center; }
    main { max-width: 880px; margin: 0; padding: 2em 4em; display: grid; grid-template-columns: max-content 300px; align-items: center; gap: 24px; transform: scale(1.3); transform-origin: center; }
    .previewPanel { --preview-padding-y: 3.4em; --preview-padding-x: 2.4em; position: relative; isolation: isolate; overflow: hidden; justify-self: center; background: radial-gradient(circle at 28% 18%, rgba(255,255,255,.30), rgba(255,255,255,.11) 34%, rgba(210,225,235,.09) 70%), linear-gradient(145deg, rgba(255,255,255,.27), rgba(170,190,205,.19)); backdrop-filter: blur(18px) saturate(115%); border-radius: 25px; padding: var(--preview-padding-y) var(--preview-padding-x); border: 0; box-shadow: inset 0 3px 18px rgba(255,255,255,.66), inset 0 -22px 38px rgba(115,135,150,.22), 0 34px 110px rgba(82, 103, 125, .38), 0 8px 28px rgba(0,0,0,.28); width: fit-content; }
    .controlsPanel { padding: 0; display: grid; grid-template-columns: 1fr; gap: 10px; align-items: start; }
    .previewControls { position: relative; z-index: 1; display: flex; align-items: center; justify-content: center; gap: 0.7em; }
    .previewWrap { padding: 2em 1.8em; border-radius: 1.1em; display: grid; place-items: center; background: black; }
    img.preview { width: 128px; height: 64px; background: #000; border: 1px solid transparent; }
    img.preview.showBorder { border-color: rgba(127, 244, 255, .2); }
    input[type="checkbox"] { width: 12px; height: 12px; margin: 0; accent-color: #7ff4ff; }
    select, textarea, button { border-radius: 4px; border: 1px solid rgba(255, 255, 255, .2); background: #000; color: #dfe7ed; font: inherit; }
    .controlsPanel select, .controlsPanel textarea, .controlsPanel button { border-color: rgba(255, 255, 255, .1); }
    select, button { padding: 6px 8px; font-size: 12px; }
    textarea { min-height: 260px; padding: 8px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; line-height: 1.25; }
    button { cursor: pointer; background: #000; }
    .buttons { display: flex; flex-direction: column; gap: 5px; }
    .buttons button { position: relative; overflow: hidden; width: 28px; height: 28px; padding: 0; border-radius: 8px; box-shadow: inset 0 2px 3px rgba(255,255,255,.18), inset 0 -3px 5px rgba(0,0,0,.85), 0 2px 0 rgba(255,255,255,.08); }
    .buttons button::before { content: ""; position: absolute; inset: 1px; border-radius: 6px; background: linear-gradient(135deg, rgba(255,255,255,.34), transparent 42%), repeating-radial-gradient(circle at 30% 20%, rgba(255,255,255,.18) 0 1px, transparent 1px 4px); opacity: .82; mix-blend-mode: screen; pointer-events: none; }
    .buttons button::after { content: ""; position: absolute; inset: 4px; border-radius: 4px; border: 1px solid rgba(255,255,255,.16); box-shadow: inset 0 1px 2px rgba(255,255,255,.18), inset 0 -1px 2px rgba(0,0,0,.7); pointer-events: none; }
    .rangeControl { width: 100%; accent-color: #7ff4ff; }
    .log { min-height: 48px; max-height: 90px; overflow: auto; margin: 0; padding: 0; list-style: none; color: rgba(223, 231, 237, .55); font-size: 11px; }
    @media (max-width: 860px) { main {grid-template-columns: 1fr; padding: 18px; } }
  </style>
</head>
<body>
  <main>
    <section class="previewPanel">
      <div class="previewControls">
        <div class="previewWrap"><img id="preview" class="preview" alt="OLED preview" /></div>
        <div class="buttons">
          <button data-button="up" aria-label="Up" title="Up"></button>
          <button data-button="select" aria-label="Select" title="Select"></button>
          <button data-button="down" aria-label="Down" title="Down"></button>
        </div>
      </div>
    </section>
    <section class="controlsPanel">
      <select id="screen" title="Screen"></select>
      <select id="scenario" title="Scenario"></select>
      <input id="paddingSlider" class="rangeControl" type="range" min="0" max="100" value="100" title="Panel padding" aria-label="Panel padding" />
      <textarea id="state" title="State JSON"></textarea>
      <ul id="log" class="log"></ul>
    </section>
  </main>
<script>
const preview = document.querySelector('#preview');
const previewPanel = document.querySelector('.previewPanel');
const paddingSlider = document.querySelector('#paddingSlider');
const screenSelect = document.querySelector('#screen');
const scenarioSelect = document.querySelector('#scenario');
const stateBox = document.querySelector('#state');
const log = document.querySelector('#log');
let refreshToken = 0;

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function fillSelect(select, values, selected) {
  if (document.activeElement === select) return;
  const currentValues = Array.from(select.options).map(option => option.value);
  const sameValues = currentValues.length === values.length && currentValues.every((value, index) => value === values[index]);
  if (sameValues && select.value === selected) return;

  const previous = select.value;
  select.innerHTML = '';
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  select.value = selected ?? previous;
}

async function refresh({updateText = true} = {}) {
  const token = ++refreshToken;
  const data = await (await fetch('/api/session')).json();
  if (token !== refreshToken) return;
  fillSelect(screenSelect, data.screens.map((name, index) => `${index}:${name}`), `${data.screenIndex}:${data.screenName}`);
  fillSelect(scenarioSelect, data.scenarios.concat(data.scenario === 'custom' ? ['custom'] : []), data.scenario);
  if (updateText && document.activeElement !== stateBox) stateBox.value = JSON.stringify(data.state, null, 2);
  log.innerHTML = '';
  for (const item of data.commandLog) {
    const li = document.createElement('li');
    li.textContent = item;
    log.append(li);
  }
  preview.src = `/preview.png?${Date.now()}`;
}

screenSelect.addEventListener('change', async () => {
  await post('/api/screen', { index: Number(screenSelect.value.split(':')[0]) });
  await refresh();
});
scenarioSelect.addEventListener('change', async () => {
  if (scenarioSelect.value !== 'custom') await post('/api/scenario', { name: scenarioSelect.value });
  await refresh();
});
async function pressButton(name) {
  await post('/api/button', { name });
  await refresh();
}

document.querySelectorAll('[data-button]').forEach(button => button.addEventListener('click', async () => {
  await pressButton(button.dataset.button);
}));

function setPreviewPadding(value) {
  const amount = Number(value) / 100;
  const y = 0.4 + (3.4 - 0.4) * amount;
  const x = 0.4 + (2.4 - 0.4) * amount;
  previewPanel.style.setProperty('--preview-padding-y', `${y.toFixed(2)}em`);
  previewPanel.style.setProperty('--preview-padding-x', `${x.toFixed(2)}em`);
}
paddingSlider.addEventListener('input', () => setPreviewPadding(paddingSlider.value));
setPreviewPadding(paddingSlider.value);

document.addEventListener('keydown', async event => {
  if (event.target.matches('input, textarea, select, button')) return;
  const keys = { ArrowUp: 'up', ArrowDown: 'down', Enter: 'select' };
  const name = keys[event.key];
  if (!name) return;
  event.preventDefault();
  await pressButton(name);
});
refresh();
setInterval(() => refresh({updateText: false}), 100);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    session.set_scenario("boot")
    return HTML


@app.get("/api/session")
def get_session() -> dict[str, Any]:
    return session.summary()


@app.post("/api/scenario")
async def set_scenario(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        session.set_scenario(str(body["name"]))
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Unknown scenario") from exc
    return session.summary()


@app.post("/api/screen")
async def set_screen(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        session.set_screen(int(body["index"]))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail="Unknown screen") from exc
    return session.summary()


@app.post("/api/button")
async def press_button(request: Request) -> dict[str, Any]:
    body = await request.json()
    try:
        session.button(str(body["name"]))
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Unknown button") from exc
    return session.summary()


@app.post("/api/custom-state")
async def set_custom_state(request: Request) -> dict[str, Any]:
    body = await request.json()
    state = body.get("state")
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="state must be a JSON object")
    session.set_custom_state(state)
    return session.summary()


@app.get("/preview.png")
def preview_png() -> Response:
    from PIL import ImageOps

    image = render_oled_image(
        session.render_screen.render,
        {
            "state": session.state,
            "boot_elapsed": session.boot_elapsed,
            "boot_duration_seconds": session.boot_duration_seconds,
            "boot_hold_seconds": session.boot_hold_seconds,
        },
        WIDTH,
        HEIGHT,
        session.fonts,
    )
    image = ImageOps.colorize(image.convert("L"), black="#000000", white="#7ff4ff")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


def main() -> None:
    import uvicorn

    host = os.environ.get("EQUIP1_OLED_DESIGNER_HOST", "127.0.0.1")
    port = int(os.environ.get("EQUIP1_OLED_DESIGNER_PORT", "8765"))
    uvicorn.run("uis.oled.designer:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
