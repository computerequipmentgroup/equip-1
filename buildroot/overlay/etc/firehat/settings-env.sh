# Helpers for reading /etc/firehat/equip-1.ini from BusyBox init scripts.
# Environment variables keep precedence; INI values only fill unset vars.

FIREHAT_SETTINGS_FILE="${FIREHAT_SETTINGS_FILE:-/etc/firehat/equip-1.ini}"

firehat_ini_get() {
    section="$1"
    key="$2"
    [ -r "$FIREHAT_SETTINGS_FILE" ] || return 1
    awk -F= -v want_section="$section" -v want_key="$key" '
        function trim(s) { gsub(/^[ \t\r\n]+|[ \t\r\n]+$/, "", s); return s }
        /^[ \t]*[#;]/ { next }
        /^[ \t]*\[/ {
            current=$0
            sub(/^[ \t]*\[/, "", current)
            sub(/\][ \t]*$/, "", current)
            current=trim(current)
            next
        }
        current == want_section && index($0, "=") > 0 {
            k=trim($1)
            if (k == want_key) {
                sub(/^[^=]*=/, "")
                print trim($0)
                exit
            }
        }
    ' "$FIREHAT_SETTINGS_FILE"
}

firehat_ini_default() {
    var="$1"
    section="$2"
    key="$3"
    fallback="$4"

    eval "current=\${$var-}"
    if [ -n "$current" ]; then
        return 0
    fi

    value="$(firehat_ini_get "$section" "$key" 2>/dev/null || true)"
    [ -n "$value" ] || value="$fallback"
    escaped="$(printf '%s\n' "$value" | sed "s/'/'\\\\''/g")"
    eval "$var='$escaped'"
    export "$var"
}
