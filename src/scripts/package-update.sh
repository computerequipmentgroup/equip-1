#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$SRC_DIR")"
OUT_DIR="${1:-$PROJECT_DIR/dist}"
REPO="${EQUIP1_UPDATE_REPO:-computerequipmentgroup/equip-1}"
TAG="${EQUIP1_VERSION_TAG:-$(git -C "$PROJECT_DIR" describe --tags --exact-match HEAD 2>/dev/null || git -C "$PROJECT_DIR" describe --tags --match 'v[0-9]*' --abbrev=0 2>/dev/null || echo v0.1.0)}"
COMMIT="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
BRANCH="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
DIRTY="$(git -C "$PROJECT_DIR" diff --quiet --ignore-submodules HEAD -- 2>/dev/null && echo false || echo true)"

mkdir -p "$OUT_DIR"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

WEB_DIR="$SRC_DIR/uis/web"
if [ -f "$WEB_DIR/package.json" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: npm is required to build the web UI but was not found on PATH." >&2
        exit 1
    fi
    echo "==> Building web UI (nuxt generate)..."
    if [ -d "$WEB_DIR/node_modules" ]; then
        ( cd "$WEB_DIR" && npm install --no-audit --no-fund )
    else
        ( cd "$WEB_DIR" && npm ci --no-audit --no-fund )
    fi
    ( cd "$WEB_DIR" && rm -rf .output .nuxt && npm run generate )
fi

PAYLOAD="$TMP/equip1-update"
mkdir -p "$PAYLOAD"
rsync -a --delete "$SRC_DIR/equip1d" "$PAYLOAD/"
rsync -a --delete \
    --exclude 'web/node_modules' \
    --exclude 'web/.nuxt' \
    "$SRC_DIR/uis" "$PAYLOAD/"
rsync -a --delete "$SRC_DIR/fonts" "$PAYLOAD/"
cp "$SRC_DIR/requirements.txt" "$PAYLOAD/requirements.txt"
cat > "$PAYLOAD/version.json" <<EOF
{
  "version": "$TAG",
  "tag": "$TAG",
  "commit": "$COMMIT",
  "branch": "$BRANCH",
  "dirty": $DIRTY,
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo": "$REPO"
}
EOF

BUNDLE="$OUT_DIR/equip1-update.tar.gz"
tar -C "$TMP" -czf "$BUNDLE" equip1-update

echo "==> Update bundle ready: $BUNDLE"
echo "Attach this asset to the GitHub release for $TAG."
