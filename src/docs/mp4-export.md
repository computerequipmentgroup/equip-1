# MP4 export options

Equip-1 always records the original camera stream first. DV captures default to a full-quality `.mov` container, with `.dv` and `.avi` available in settings; HDV captures stay native `.m2t`. MP4 export is an optional **sidecar** conversion that writes a same-stem `.mp4` beside the original capture.

Example:

```text
/data/captures/capture_20260802_142000.mov
/data/captures/capture_20260802_142000.mp4
```

## When export runs

MP4 export runs **after recording stops**, not during recording:

1. The recorder writes the original full-quality capture file.
2. Stop is requested from OLED/web/API.
3. The recorder closes the capture and immediately publishes the non-recording state.
4. Finalization continues in the background.
5. If automatic MP4 export is enabled, the daemon runs `ffmpeg` and creates the sidecar `.mp4`. MP4 export is off by default; users can choose whether export runs in **Blocking** or **Background**, and can also trigger **Convert all** from settings to process existing captures on demand.

The original recording path is therefore not slowed down by MP4 encoding. In Blocking mode the post-recording export marks the daemon as `converting` and blocks starting a new recording until the sidecar is done. In Background mode the export still runs after recording stops, but the daemon can start another recording while FFmpeg works, for hosts with enough CPU and storage bandwidth.

## OLED setting

The OLED settings screen shows MP4 export as:

```text
MP4 export [OFF]
```

Cycle order:

```text
[OFF] -> [FG] -> [BG]
```

`[FG]` means automatic conversion blocks the next recording. `[BG]` means automatic conversion continues in the background and allows another recording to start. Default:

```text
[OFF]
```

While exporting, the OLED record screen replaces remaining minutes with `XX% MP4`, using the daemon's conversion progress estimate.

## Presets

| OLED label | INI/API value | x264 CRF | MPEG-4 fallback q:v | Audio | Intended use |
| --- | --- | ---: | ---: | --- | --- |
| `[28]` | `small` | 28 | 7 | AAC 128k | Smallest MP4 files; visibly more compression |
| `[23]` | `balanced` | 23 | 5 | AAC 128k | Middle ground between size and quality |
| `[18]` | `high` | 18 | 3 | AAC 128k | Visually close to source for most DV material |
| `[14]` | `max` | 14 | 1 | AAC 192k | Highest available quality; larger and slower |
| `[OFF]` | `auto_convert_mp4_mode = off` | — | — | — | Do not create MP4 sidecars |
| `[FG]` / `[BG]` | `auto_convert_mp4_mode = foreground` / `background` | Uses `mp4_quality` | Uses `mp4_quality` | Uses `mp4_quality` | Create MP4 sidecars after recording; FG/Blocking blocks the next recording, BG/Background does not |

The daemon first tries H.264 via `libx264`:

```text
-c:v libx264 -preset veryfast -crf <preset> -pix_fmt yuv420p
```

If that fails, it tries a compatibility fallback using FFmpeg's native MPEG-4 encoder:

```text
-c:v mpeg4 -q:v <preset> -pix_fmt yuv420p
```

Both variants scale to even dimensions with:

```text
-vf scale=trunc(iw/2)*2:trunc(ih/2)*2
```

This avoids encoders rejecting odd-sized input. When MP4 deinterlacing is enabled, the daemon first tries FFmpeg's `nnedi` filter before scaling:

```text
-vf nnedi=weights=/opt/equip1/share/nnedi3_weights.bin:deint=interlaced:field=af:qual=fast,scale=trunc(iw/2)*2:trunc(ih/2)*2
```

NNEDI is FFmpeg's neural-network edge-directed interpolation deinterlacer. It needs the `nnedi3_weights.bin` file shipped in the image. If the weights file is missing or the target FFmpeg build does not include `nnedi`, export falls back to the existing `yadif` deinterlacer:

```text
-vf yadif=mode=send_frame:parity=auto:deint=all,scale=trunc(iw/2)*2:trunc(ih/2)*2
```

## Runtime settings

In `/etc/equip1/equip-1.ini`:

```ini
[recording]
auto_convert_mp4 = true
auto_convert_mp4_mode = background
mp4_quality = high
mp4_deinterlace = false
nnedi_weights = /opt/equip1/share/nnedi3_weights.bin
```

Environment overrides:

| Env var | Values |
| --- | --- |
| `EQUIP1_AUTO_CONVERT_MP4_MODE` | `off`, `foreground`, `background` |
| `EQUIP1_AUTO_CONVERT_MP4` | Legacy boolean: `true`/`false`, `1`/`0`, `on`/`off`; `true` maps to the default `background` mode when no explicit mode is set |
| `EQUIP1_MP4_QUALITY` | `small`, `balanced`, `high`, `max` |
| `EQUIP1_MP4_DEINTERLACE` | `true`/`false`, `1`/`0`, `on`/`off` |
| `EQUIP1_NNEDI_WEIGHTS` | Path to `nnedi3_weights.bin`; default `/opt/equip1/share/nnedi3_weights.bin` |

Aliases accepted by the daemon include:

| Alias | Normalized value |
| --- | --- |
| `low` | `small` |
| `medium` | `balanced` |
| `best`, `maximum`, `ultra`, `archive`, `archival` | `max` |

Unknown mode values fall back to `off`. Unknown quality values fall back to `high`.

## API and state

OLED uses:

```http
POST /api/settings/conversion
```

Example payloads:

```json
{ "auto_mp4_mode": "foreground", "mp4_quality": "high" }
```

```json
{ "mp4_deinterlace_enabled": true }
```

```json
{ "auto_mp4_mode": "off" }
```

On-demand conversion of all captures that do not already have a non-empty same-stem `.mp4` sidecar uses:

```http
POST /api/commands/convert-all-mp4
```

Daemon state includes:

```json
{
  "conversion": {
    "auto_mp4_enabled": true,
    "auto_mp4_mode": "background",
    "mp4_quality": "high",
    "mp4_deinterlace_enabled": false,
    "active": false,
    "progress_percent": 0,
    "source": null,
    "target": null,
    "last_error": null
  }
}
```

During export, `conversion.active` is `true` and `conversion.progress_percent` reports `0` through `100`. `state.mode` becomes `converting` for Blocking conversion when the recorder is idle; Background conversion leaves the daemon otherwise recordable while `conversion.active` remains true.

## Notes and trade-offs

- The original capture is kept; MP4 export does not replace it.
- Existing non-empty `.mp4` sidecars are not regenerated.
- Higher quality settings take longer and produce larger files.
- `[14]` can be significantly slower than `[18]`; use it when size and conversion time are less important.
- Deinterlacing is on by default for interlaced DV tapes and progressive playback; disable it if you want the MP4 sidecar to preserve the source interlaced look.
- MP4 export quality and deinterlacing do not change live preview, HDMI preview, or the source recording quality.
