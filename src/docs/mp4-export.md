# MP4 export options

Equip-1 always records the original camera stream first. For DV/HDV captures this means the source `.dv`, `.dif`, `.m2t`, `.mts`, or transport/container file is kept unchanged. MP4 export is an optional **sidecar** conversion that writes a same-stem `.mp4` beside the original capture.

Example:

```text
/data/captures/capture_20260802_142000.dv
/data/captures/capture_20260802_142000.mp4
```

## When export runs

MP4 export runs **after recording stops**, not during recording:

1. The recorder writes the original capture file.
2. Stop is requested from OLED/web/API.
3. The recorder closes the capture and immediately publishes the non-recording state.
4. Finalization continues in the background.
5. If MP4 export is enabled, the daemon runs `ffmpeg` and creates the sidecar `.mp4`.

The original recording path is therefore not slowed down by MP4 encoding. The device can still be busy after recording while the export is running.

## OLED setting

The OLED settings screen shows MP4 export as:

```text
MP4 export [18]
```

The bracket value is the x264 CRF number. Lower CRF means higher quality and larger files.

Cycle order:

```text
[28] -> [23] -> [18] -> [14] -> [OFF]
```

Default:

```text
[18]
```

While exporting, the OLED record screen replaces remaining minutes with `EXPORT` and shows a blinking dot indicator.

## Presets

| OLED label | INI/API value | x264 CRF | MPEG-4 fallback q:v | Audio | Intended use |
| --- | --- | ---: | ---: | --- | --- |
| `[28]` | `small` | 28 | 7 | AAC 128k | Smallest MP4 files; visibly more compression |
| `[23]` | `balanced` | 23 | 5 | AAC 128k | Middle ground between size and quality |
| `[18]` | `high` | 18 | 3 | AAC 128k | Default; visually close to source for most DV material |
| `[14]` | `max` | 14 | 1 | AAC 192k | Highest available quality; larger and slower |
| `[OFF]` | `auto_convert_mp4 = false` | — | — | — | Do not create MP4 sidecars |

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

This avoids encoders rejecting odd-sized input.

## Runtime settings

In `/etc/equip1/equip-1.ini`:

```ini
[recording]
auto_convert_mp4 = true
mp4_quality = high
```

Environment overrides:

| Env var | Values |
| --- | --- |
| `EQUIP1_AUTO_CONVERT_MP4` | `true`/`false`, `1`/`0`, `on`/`off` |
| `EQUIP1_MP4_QUALITY` | `small`, `balanced`, `high`, `max` |

Aliases accepted by the daemon include:

| Alias | Normalized value |
| --- | --- |
| `low` | `small` |
| `medium` | `balanced` |
| `best`, `maximum`, `ultra`, `archive`, `archival` | `max` |

Unknown quality values fall back to `high`.

## API and state

OLED uses:

```http
POST /api/settings/conversion
```

Example payloads:

```json
{ "auto_mp4_enabled": true, "mp4_quality": "high" }
```

```json
{ "auto_mp4_enabled": false }
```

Daemon state includes:

```json
{
  "conversion": {
    "auto_mp4_enabled": true,
    "mp4_quality": "high",
    "active": false,
    "source": null,
    "target": null,
    "last_error": null
  }
}
```

During export, `conversion.active` is `true` and `state.mode` becomes `converting` when the recorder is idle.

## Notes and trade-offs

- The original capture is kept; MP4 export does not replace it.
- Existing non-empty `.mp4` sidecars are not regenerated.
- Higher quality settings take longer and produce larger files.
- `[14]` can be significantly slower than `[18]`; use it when size and conversion time are less important.
- MP4 export quality does not change live preview, HDMI preview, or the source recording quality.
