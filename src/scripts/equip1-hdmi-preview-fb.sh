#!/bin/sh
# Equip-1 HDMI framebuffer preview.
#
# Polls the kernel DRM HDMI connector state and, while a screen is connected,
# renders the daemon's low-cost live MKV/DV stream directly to /dev/fb0 with
# ffmpeg's fbdev muxer. This avoids Chromium, HTTP MJPEG encoding, and
# browser-side decode on the embedded HDMI output.

set -u

FFMPEG_BIN="${EQUIP1_FFMPEG_BIN:-/usr/bin/ffmpeg}"
STREAM_URL="${EQUIP1_HDMI_STREAM_URL:-http://127.0.0.1:8000/api/stream.mkv?takeover=1}"
FBDEV="${EQUIP1_HDMI_FBDEV:-/dev/fb0}"
POLL_SECONDS="${EQUIP1_HDMI_POLL_SECONDS:-1}"
ASSUME_CONNECTED_WITHOUT_DRM="${EQUIP1_HDMI_ASSUME_CONNECTED_WITHOUT_DRM:-0}"
STATUS_FILES="${EQUIP1_HDMI_STATUS_FILES:-/sys/class/drm/*HDMI*/status}"
DATA_LOG="${EQUIP1_HDMI_DATA_LOG:-/var/log/equip1/hdmi-preview-data.log}"
FFMPEG_LOGLEVEL="${EQUIP1_HDMI_FFMPEG_LOGLEVEL:-info}"
FFMPEG_PROGRESS="${EQUIP1_HDMI_FFMPEG_PROGRESS:-0}"
FFMPEG_STATS_PERIOD="${EQUIP1_HDMI_FFMPEG_STATS_PERIOD:-5}"
CLEAR_ON_CONNECT="${EQUIP1_HDMI_CLEAR_ON_CONNECT:-1}"
LOG_LEVEL="$(printf '%s' "${EQUIP1_LOG_LEVEL:-info}" | tr 'A-Z' 'a-z')"
if [ "$LOG_LEVEL" = "quiet" ]; then
    FFMPEG_LOGLEVEL="quiet"
    FFMPEG_PROGRESS="0"
fi

ffmpeg_pid=""
last_status_summary=""
last_fb_diag_at=0

log() {
    [ "$LOG_LEVEL" = "quiet" ] && return 0
    line="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) $*"
    printf '%s\n' "$line"
    if [ -n "$DATA_LOG" ]; then
        mkdir -p "$(dirname "$DATA_LOG")" 2>/dev/null || true
        printf '%s\n' "$line" >>"$DATA_LOG" 2>/dev/null || true
    fi
}

status_summary() {
    found=0
    summary=""
    for status_file in $STATUS_FILES; do
        [ -e "$status_file" ] || continue
        found=1
        if [ -r "$status_file" ]; then
            status="$(tr -d '\r\n' < "$status_file" 2>/dev/null || true)"
        else
            status="unreadable"
        fi
        summary="${summary}${status_file}=${status} "
    done
    if [ "$found" -eq 0 ]; then
        summary="no HDMI status files matched: $STATUS_FILES"
    fi
    printf '%s\n' "$summary"
}

hdmi_connected() {
    found=0
    for status_file in $STATUS_FILES; do
        [ -r "$status_file" ] || continue
        found=1
        status="$(tr -d '\r\n' < "$status_file" 2>/dev/null || true)"
        [ "$status" = "connected" ] && return 0
    done

    [ "$found" -eq 0 ] && [ "$ASSUME_CONNECTED_WITHOUT_DRM" = "1" ]
}

ffmpeg_alive() {
    [ -n "$ffmpeg_pid" ] && kill -0 "$ffmpeg_pid" 2>/dev/null
}

fb_sys_dir() {
    basename_fb="$(basename "$FBDEV")"
    printf '/sys/class/graphics/%s' "$basename_fb"
}

dump_fb_diagnostics() {
    now="$(date +%s 2>/dev/null || echo 0)"
    if [ $((now - last_fb_diag_at)) -lt 10 ]; then
        return 0
    fi
    last_fb_diag_at="$now"
    sys_dir="$(fb_sys_dir)"
    log "fb diag: /proc/cmdline=$(cat /proc/cmdline 2>/dev/null || echo '?')"
    log "fb diag: /sys/class/graphics=$(ls -1 /sys/class/graphics 2>/dev/null | tr '\n' ' ' || echo '?')"
    log "fb diag: /dev/fb*=$(ls -l /dev/fb* 2>&1 | tr '\n' ' ')"
    log "fb diag: /dev/dri=$(ls -l /dev/dri 2>&1 | tr '\n' ' ')"
    log "fb diag: vtconsole=$(for v in /sys/class/vtconsole/vtcon*; do [ -e "$v/name" ] && printf '%s:%s:bind=%s ' "$(basename "$v")" "$(cat "$v/name" 2>/dev/null)" "$(cat "$v/bind" 2>/dev/null || echo '?')"; done)"
    log "fb diag: sysfs name=$(cat "$sys_dir/name" 2>/dev/null || echo '?') stride=$(cat "$sys_dir/stride" 2>/dev/null || echo '?') blank=$(cat "$sys_dir/blank" 2>/dev/null || echo '?') state=$(cat "$sys_dir/state" 2>/dev/null || echo '?') rotate=$(cat "$sys_dir/rotate" 2>/dev/null || echo '?')"
    log "fb diag: drm dmesg=$(dmesg 2>/dev/null | grep -iE 'drm|hdmi|fbdev|fbcon|framebuffer|rockchip' | tail -40 | tr '\n' '|' || echo '?')"
}

ensure_fbdev_node() {
    [ -e "$FBDEV" ] && return 0

    sys_dir="$(fb_sys_dir)"
    if [ ! -r "$sys_dir/dev" ]; then
        log "framebuffer sysfs not available: $sys_dir"
        dump_fb_diagnostics
        return 1
    fi

    devno="$(cat "$sys_dir/dev" 2>/dev/null || true)"
    major="${devno%:*}"
    minor="${devno#*:}"
    case "$major:$minor" in
        *[!0-9:]*|:|*:) log "invalid framebuffer dev number for $sys_dir: $devno"; return 1 ;;
    esac

    mkdir -p "$(dirname "$FBDEV")" 2>/dev/null || true
    if command -v mknod >/dev/null 2>&1; then
        mknod "$FBDEV" c "$major" "$minor" 2>/dev/null || true
        chmod 600 "$FBDEV" 2>/dev/null || true
    fi

    if [ -e "$FBDEV" ]; then
        log "created framebuffer node $FBDEV from $sys_dir/dev=$devno"
        return 0
    fi

    log "framebuffer node missing and could not be created: $FBDEV from $sys_dir/dev=$devno"
    return 1
}

fb_geometry() {
    sys_dir="$(fb_sys_dir)"

    # Prefer the active virtual size. /sys/class/graphics/fb0/modes can keep
    # listing the boot/fallback mode even after a runtime mode switch.
    if [ -r "$sys_dir/virtual_size" ]; then
        geometry="$(sed -n 's/^\([0-9][0-9]*\),\([0-9][0-9]*\).*/\1 \2/p' "$sys_dir/virtual_size" 2>/dev/null | head -n 1)"
        if [ -n "$geometry" ]; then
            printf '%s\n' "$geometry"
            return
        fi
    fi

    if [ -r "$sys_dir/modes" ]; then
        geometry="$(sed -n '1s/.*:\([0-9][0-9]*\)x\([0-9][0-9]*\).*/\1 \2/p' "$sys_dir/modes" 2>/dev/null | head -n 1)"
        if [ -n "$geometry" ]; then
            printf '%s\n' "$geometry"
            return
        fi
    fi

    printf '720 540\n'
}

fb_pix_fmt() {
    sys_dir="$(fb_sys_dir)"
    bpp="$(cat "$sys_dir/bits_per_pixel" 2>/dev/null || printf '32')"
    case "$bpp" in
        16) printf 'rgb565le\n' ;;
        24) printf 'rgb24\n' ;;
        # ffmpeg's fbdev muxer rejects bgr0 and asks for bgra for 32-bit fbdev.
        # Rockchip fbdev reports XRGB8888, but the muxer handles the accepted
        # BGRA byte layout for this output path.
        *) printf 'bgra\n' ;;
    esac
}

clear_framebuffer() {
    [ "$CLEAR_ON_CONNECT" = "1" ] || [ "$CLEAR_ON_CONNECT" = "true" ] || return 0
    ensure_fbdev_node || return 0

    set -- $(fb_geometry)
    width="$1"
    height="$2"
    pix_fmt="${EQUIP1_HDMI_PIX_FMT:-$(fb_pix_fmt)}"
    log "clearing framebuffer ${width}x${height} ${pix_fmt} before preview using ffmpeg fbdev"
    "$FFMPEG_BIN" \
        -hide_banner \
        -loglevel error \
        -nostdin \
        -nostats \
        -f lavfi \
        -i "color=c=black:s=${width}x${height}:r=1" \
        -frames:v 1 \
        -vf "format=${pix_fmt}" \
        -pix_fmt "$pix_fmt" \
        -f fbdev "$FBDEV" >>"$DATA_LOG" 2>&1 || true
}

start_ffmpeg() {
    ffmpeg_alive && return 0

    if [ ! -x "$FFMPEG_BIN" ]; then
        log "ffmpeg not executable: $FFMPEG_BIN"
        return 1
    fi
    if ! ensure_fbdev_node; then
        return 1
    fi
    set -- $(fb_geometry)
    width="$1"
    height="$2"
    pix_fmt="${EQUIP1_HDMI_PIX_FMT:-$(fb_pix_fmt)}"
    filter="${EQUIP1_HDMI_FILTER:-scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=${pix_fmt}}"

    stride="$(cat "$(fb_sys_dir)/stride" 2>/dev/null || echo '')"
    log "HDMI connected; starting framebuffer preview ${width}x${height} ${pix_fmt} from $STREAM_URL"
    log "framebuffer sysfs: dir=$(fb_sys_dir) name=$(cat "$(fb_sys_dir)/name" 2>/dev/null || echo '?') bpp=$(cat "$(fb_sys_dir)/bits_per_pixel" 2>/dev/null || echo '?') virtual=$(cat "$(fb_sys_dir)/virtual_size" 2>/dev/null || echo '?') stride=${stride:-?} blank=$(cat "$(fb_sys_dir)/blank" 2>/dev/null || echo '?') state=$(cat "$(fb_sys_dir)/state" 2>/dev/null || echo '?') modes=$(head -n 1 "$(fb_sys_dir)/modes" 2>/dev/null || echo '?')"
    dump_fb_diagnostics

    stats_args="-nostats"
    if [ "$FFMPEG_PROGRESS" = "1" ] || [ "$FFMPEG_PROGRESS" = "true" ]; then
        stats_args="-stats_period $FFMPEG_STATS_PERIOD -progress pipe:2"
        log "ffmpeg progress logging enabled interval=${FFMPEG_STATS_PERIOD}s loglevel=${FFMPEG_LOGLEVEL}"
    fi

    # shellcheck disable=SC2086 # stats_args intentionally expands to ffmpeg option words.
    "$FFMPEG_BIN" \
        -hide_banner \
        -loglevel "$FFMPEG_LOGLEVEL" \
        -nostdin \
        $stats_args \
        -fflags nobuffer \
        -flags low_delay \
        -probesize 32768 \
        -analyzeduration 1000000 \
        -reconnect 1 \
        -reconnect_streamed 1 \
        -reconnect_delay_max 2 \
        -i "$STREAM_URL" \
        -an \
        -vf "$filter" \
        -pix_fmt "$pix_fmt" \
        -f fbdev "$FBDEV" >>"$DATA_LOG" 2>&1 &
    ffmpeg_pid="$!"
}

stop_ffmpeg() {
    ffmpeg_alive || {
        ffmpeg_pid=""
        return 0
    }

    log "HDMI disconnected; stopping framebuffer preview"
    kill "$ffmpeg_pid" 2>/dev/null || true

    tries=0
    while ffmpeg_alive && [ "$tries" -lt 5 ]; do
        sleep 1
        tries=$((tries + 1))
    done

    if ffmpeg_alive; then
        kill -9 "$ffmpeg_pid" 2>/dev/null || true
    fi
    wait "$ffmpeg_pid" 2>/dev/null || true
    ffmpeg_pid=""
}

cleanup() {
    stop_ffmpeg
}
trap cleanup EXIT INT TERM

log "watching HDMI connectors for framebuffer preview"
while true; do
    current_status_summary="$(status_summary)"
    if [ "$current_status_summary" != "$last_status_summary" ]; then
        log "HDMI status: $current_status_summary"
        last_status_summary="$current_status_summary"
        case "$current_status_summary" in
            *=connected*) clear_framebuffer ;;
        esac
    fi

    if hdmi_connected; then
        start_ffmpeg
    else
        stop_ffmpeg
    fi

    if [ -n "$ffmpeg_pid" ] && ! ffmpeg_alive; then
        wait "$ffmpeg_pid" 2>/dev/null
        rc="$?"
        log "ffmpeg exited rc=$rc"
        ffmpeg_pid=""
    fi

    sleep "$POLL_SECONDS"
done
