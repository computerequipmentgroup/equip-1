from __future__ import annotations

import asyncio
import contextlib
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import perf
from .service import CommandError, Equip1Daemon
from .sysinfo import get_system_stats


daemon = Equip1Daemon.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await daemon.start_monitor()
    await daemon.publish_state()
    try:
        yield
    finally:
        await daemon.shutdown()


app = FastAPI(title="Equip-1 Daemon", version="0.1.0", lifespan=lifespan)


@app.get("/api/state")
async def get_state() -> dict:
    started = time.perf_counter()
    try:
        return await daemon.snapshot()
    finally:
        perf.log_elapsed("api.state", started)


@app.get("/api/storage")
async def get_storage() -> dict:
    started = time.perf_counter()
    try:
        state = await daemon.snapshot()
        return state["storage"]
    finally:
        perf.log_elapsed("api.storage", started)


@app.get("/api/system")
async def get_system() -> dict:
    started = time.perf_counter()
    try:
        return get_system_stats()
    finally:
        perf.log_elapsed("api.system", started)


@app.get("/api/captures")
async def get_captures() -> list[dict]:
    started = time.perf_counter()
    try:
        return await daemon.list_captures()
    finally:
        perf.log_elapsed("api.captures", started)


@app.post("/api/time")
async def sync_time(payload: dict) -> dict:
    now = payload.get("now")
    if now is None:
        raise HTTPException(status_code=400, detail="Missing 'now'")
    try:
        return await daemon.sync_time(float(now))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid 'now'") from exc


@app.get("/api/captures/{capture_name}/download")
async def download_capture(capture_name: str) -> FileResponse:
    path = await daemon.capture_path(capture_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Capture not found")
    return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)


@app.get("/api/captures/{capture_name}/thumbnail")
async def capture_thumbnail(capture_name: str) -> FileResponse:
    path = await daemon.thumbnail_path(capture_name)
    if path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/api/preview.mjpg")
async def live_preview() -> StreamingResponse:
    try:
        stream = await daemon.preview_stream()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(stream, media_type=daemon.preview_media_type())


@app.get("/api/stream.mkv")
async def live_mkv_stream(takeover: bool = False) -> StreamingResponse:
    # Raw DV remuxed into Matroska for VLC and other network players. Open
    # http://<device-ip>:8000/api/stream.mkv in VLC's "Open Network Stream".
    # The HDMI framebuffer watcher passes takeover=1 so plugging in a monitor
    # preempts a browser MJPEG preview that may already be holding the stream.
    try:
        stream = await daemon.mkv_stream(takeover=takeover)
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(stream, media_type=daemon.mkv_media_type())


@app.post("/api/commands/start-recording")
async def start_recording() -> dict:
    try:
        return await daemon.start_recording()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/stop-recording")
async def stop_recording() -> dict:
    return await daemon.stop_recording()


@app.post("/api/commands/rescan-camera")
async def rescan_camera() -> dict:
    return await daemon.rescan_camera()


@app.post("/api/commands/deck-play")
async def deck_play() -> dict:
    try:
        return await daemon.deck_command("play")
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/deck-stop")
async def deck_stop() -> dict:
    try:
        return await daemon.deck_command("stop")
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/deck-rewind")
async def deck_rewind() -> dict:
    try:
        return await daemon.deck_command("rewind")
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/deck-fast-forward")
async def deck_fast_forward() -> dict:
    try:
        return await daemon.deck_command("fast-forward")
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/clear-error")
async def clear_error() -> dict:
    return await daemon.clear_error()


@app.post("/api/commands/shutdown")
async def shutdown_host() -> dict:
    return await daemon.shutdown_host()


@app.post("/api/commands/reboot")
async def reboot_host() -> dict:
    return await daemon.reboot_host()


@app.post("/api/commands/usb-storage-start")
async def usb_storage_start() -> dict:
    try:
        return await daemon.start_usb_storage()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/usb-storage-stop")
async def usb_storage_stop() -> dict:
    try:
        return await daemon.stop_usb_storage()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/storage-switch-usb")
async def storage_switch_usb() -> dict:
    try:
        return await daemon.switch_storage_usb()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/commands/storage-switch-sd")
async def storage_switch_sd() -> dict:
    try:
        return await daemon.switch_storage_sd()
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _handle_ws_command(message: object) -> None:
    if not isinstance(message, dict):
        return
    if message.get("type") == "set-light-color":
        payload = message.get("colors")
        if payload is None:
            payload = message.get("color")
        with contextlib.suppress(CommandError):
            await daemon.set_light_color(payload)
    elif message.get("type") == "set-lights-enabled":
        with contextlib.suppress(CommandError):
            await daemon.set_lights_enabled(bool(message.get("enabled")))
    elif message.get("type") == "set-lights-brightness":
        with contextlib.suppress(CommandError):
            await daemon.set_lights_brightness(message.get("brightness"))


@app.websocket("/api/events")
async def events(websocket: WebSocket) -> None:
    await websocket.accept()
    async with daemon.events.subscribe() as queue:
        started = time.perf_counter()
        await websocket.send_json({"type": "state", "state": await daemon.snapshot(), "server_sent_at": time.time()})
        perf.log_elapsed("ws.initial_state", started)
        started = time.perf_counter()
        await websocket.send_json({"type": "captures", "captures": await daemon.list_captures(), "server_sent_at": time.time()})
        perf.log_elapsed("ws.initial_captures", started)

        async def pump_outgoing() -> None:
            while True:
                event = await queue.get()
                started = time.perf_counter()
                payload = {**event, "server_sent_at": time.time()}
                await websocket.send_json(payload)
                perf.log_elapsed("ws.send", started, type=event.get("type"))

        outgoing = asyncio.create_task(pump_outgoing())
        try:
            while True:
                message = await websocket.receive_json()
                await _handle_ws_command(message)
        except WebSocketDisconnect:
            return
        finally:
            outgoing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await outgoing


def _mount_static_web() -> None:
    web_dir = Path(os.environ.get("EQUIP1_WEB_DIR", "uis/web/.output/public"))
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")


_mount_static_web()
