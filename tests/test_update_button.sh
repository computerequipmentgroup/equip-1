#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'class AppUpdater' src/equip1d/updater.py || fail "daemon must include release-bundle updater"
grep -q '_asset_matches' src/equip1d/updater.py || fail "updater must accept versioned app update bundles"
grep -q 'package-update.sh' <(find src/scripts -maxdepth 1 -type f -print) || fail "repo must include app update bundle packaging script"
grep -q '/api/update/check' src/equip1d/api.py || fail "API must expose update check endpoint"
grep -q '/api/update/apply' src/equip1d/api.py || fail "API must expose update apply endpoint"
grep -q 'BR2_PACKAGE_CA_CERTIFICATES=y' src/buildroot/configs/equip1_defconfig || fail "image must include CA certificates for HTTPS update checks"
grep -q 'version.json' src/buildroot/scripts/build.sh || fail "build must stamp current software version"
grep -q 'GIT_VERSION_TAG' src/buildroot/scripts/build.sh || fail "build must stamp tag-like software version instead of commit hash"
! grep -q '"version": "${GIT_TAG:-$GIT_COMMIT}"' src/buildroot/scripts/build.sh || fail "build version must not fall back to commit hash"
grep -q 'window.confirm(`Install ${updateLatestLabel.value} now?`)' src/uis/web/pages/index.vue || fail "web UI must use native update-available confirmation"
grep -q 'update/apply' src/uis/web/pages/index.vue || fail "web UI must expose update button"
grep -q 'defaultSoftwareVersion = "v0.1.0"' src/uis/web/pages/index.vue || fail "mock web UI must default to the first release tag"
grep -q 'return embedded ? `v${embedded\[1\]}` : defaultSoftwareVersion' src/uis/web/pages/index.vue || fail "web UI must display software versions as v-prefixed tags, not hashes"
! grep -q 'current.tag || current.version || current.commit' src/uis/web/pages/index.vue || fail "web UI must not fall back to commit hashes for software version"
grep -q '<span>{{ updateSoftwareLabel }}</span>' src/uis/web/pages/index.vue || fail "System body must show software version/update state"
grep -q '!updateAvailable' src/uis/web/pages/index.vue || fail "Update button must be disabled when no update is available"
grep -q 'card > .error.system-notification' src/uis/web/assets/main.css || fail "System load-failed error must have explicit bottom spacing"
grep -q 'margin-bottom: 0.8rem' src/uis/web/assets/main.css || fail "System notification must have bottom spacing"
! grep -q 'border-bottom: 1px solid currentColor' src/uis/web/assets/main.css || fail "System notification must not add a border bottom"
grep -q 'Already up to date\.' src/uis/web/pages/index.vue || fail "web UI must show git-style no-update-needed label"
grep -q '4000' src/uis/web/pages/index.vue || fail "up-to-date label must be temporary"
grep -q 'Connect Equip-1 to Wi-Fi for updates\.' src/uis/web/pages/index.vue || fail "web UI must explain that updates need device Wi-Fi/LAN"

PYTHONPATH=src python3 - <<'PY' || fail "updater must not advertise releases without installable bundles"
from equip1d.updater import AppUpdater, ReleaseInfo
latest = ReleaseInfo(tag="v9.9.9", name="", body="", url="", asset_name=None, asset_url=None, published_at=None)
assert AppUpdater._is_available({"tag": "v0.1.0"}, latest) is False
latest = ReleaseInfo(tag="v9.9.9", name="", body="", url="", asset_name="equip1-update.tar.gz", asset_url="https://example.invalid/equip1-update.tar.gz", published_at=None)
assert AppUpdater._is_available({"tag": "v0.1.0"}, latest) is True
updater = AppUpdater()
assert updater._asset_matches("equip1-update.tar.gz", "v0.1.1") is True
assert updater._asset_matches("equip-1-v0.1.1-update.tar.gz", "v0.1.1") is True
assert updater._asset_matches("equip-1-v0.1.1-rock2f.img.xz", "v0.1.1") is False
PY

echo "ok - web update button and updater API are wired"
