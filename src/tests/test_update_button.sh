#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

grep -q 'class AppUpdater' src/equip1d/updater.py || fail "daemon must include release-bundle updater"
grep -q '_asset_matches' src/equip1d/updater.py || fail "updater must match app update bundles by configured asset name"
grep -q 'package-update.sh' <(find src/scripts -maxdepth 1 -type f -print) || fail "repo must include app update bundle packaging script"
grep -q -- "--exclude 'web/dist'" src/scripts/package-update.sh || fail "update bundle must not ship local Nuxt dist symlink"
grep -q -- "--exclude 'web/dist'" src/buildroot/scripts/build.sh || fail "Buildroot overlay must not ship local Nuxt dist symlink"
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
assert updater._asset_matches("equip-1-v0.1.1-update.tar.gz", "v0.1.1") is False
assert updater._asset_matches("equip-1-v0.1.1-rock2f.img.xz", "v0.1.1") is False
PY

PYTHONPATH=src python3 - <<'PY' || fail "updater must log attempts and skip stale symlinks when backing up to data"
import os
import tarfile
import tempfile
from pathlib import Path

from equip1d.updater import AppUpdater, ReleaseInfo

with tempfile.TemporaryDirectory() as tmp_name:
    tmp = Path(tmp_name)
    app_dir = tmp / "app"
    update_dir = tmp / "updates"
    log_file = tmp / "logs" / "update.log"
    version_file = app_dir / "version.json"
    old_uis = app_dir / "uis" / "web"
    old_uis.mkdir(parents=True)
    (app_dir / "equip1d").mkdir(parents=True)
    (app_dir / "fonts").mkdir(parents=True)
    (app_dir / "requirements.txt").write_text("old\n", encoding="utf-8")
    (old_uis / "dist").symlink_to("/definitely/not/on/device/.output/public", target_is_directory=True)

    payload = tmp / "payload" / "equip1-update"
    (payload / "equip1d").mkdir(parents=True)
    (payload / "equip1d" / "__init__.py").write_text("", encoding="utf-8")
    (payload / "fonts").mkdir()
    (payload / "requirements.txt").write_text("new\n", encoding="utf-8")
    public = payload / "uis" / "web" / ".output" / "public"
    public.mkdir(parents=True)
    (public / "index.html").write_text("ok\n", encoding="utf-8")
    (payload / "uis" / "web" / "dist").symlink_to("/build/host/.output/public", target_is_directory=True)

    archive_path = tmp / "equip1-update.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(payload, arcname="equip1-update")

    os.environ["EQUIP1_APP_DIR"] = str(app_dir)
    os.environ["EQUIP1_UPDATE_DIR"] = str(update_dir)
    os.environ["EQUIP1_VERSION_FILE"] = str(version_file)
    os.environ["EQUIP1_UPDATE_LOG"] = str(log_file)
    updater = AppUpdater()
    assert log_file.exists()
    updater._log_update("test entry")
    assert "test entry" in log_file.read_text(encoding="utf-8")

    latest = ReleaseInfo("v9.9.9", "", "", "https://example.invalid/release", "equip1-update.tar.gz", "https://example.invalid/equip1-update.tar.gz", None)
    updater._install_bundle(archive_path, latest)

    assert (app_dir / "uis" / "web" / ".output" / "public" / "index.html").exists()
    assert not (app_dir / "uis" / "web" / "dist").is_symlink()
    backups = list(update_dir.glob("backup-*"))
    assert backups, "expected app backup"
    assert not (backups[0] / "uis" / "web" / "dist").exists(), "backup should skip stale symlinks because /data may be exFAT"
PY

PYTHONPATH=src python3 - <<'PY' || fail "updater must roll back partial app installs"
import os
import tarfile
import tempfile
from pathlib import Path

from equip1d.updater import AppUpdater, ReleaseInfo, UpdateError

with tempfile.TemporaryDirectory() as tmp_name:
    tmp = Path(tmp_name)
    app_dir = tmp / "app"
    update_dir = tmp / "updates"
    log_file = tmp / "logs" / "update.log"
    version_file = app_dir / "version.json"

    for dirname in ("uis", "fonts", "equip1d"):
        path = app_dir / dirname
        path.mkdir(parents=True)
        (path / "marker.txt").write_text(f"old {dirname}\n", encoding="utf-8")
    (app_dir / "requirements.txt").write_text("old requirements\n", encoding="utf-8")

    payload = tmp / "payload" / "equip1-update"
    for dirname in ("uis", "fonts", "equip1d"):
        path = payload / dirname
        path.mkdir(parents=True)
        (path / "marker.txt").write_text(f"new {dirname}\n", encoding="utf-8")
    (payload / "requirements.txt").write_text("new requirements\n", encoding="utf-8")

    archive_path = tmp / "equip1-update.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(payload, arcname="equip1-update")

    os.environ["EQUIP1_APP_DIR"] = str(app_dir)
    os.environ["EQUIP1_UPDATE_DIR"] = str(update_dir)
    os.environ["EQUIP1_VERSION_FILE"] = str(version_file)
    os.environ["EQUIP1_UPDATE_LOG"] = str(log_file)
    updater = AppUpdater()
    original_copy = updater._copy_payload_item

    def failing_copy(source, target):
        if source.name == "fonts":
            raise OSError("simulated copy failure")
        return original_copy(source, target)

    updater._copy_payload_item = failing_copy
    latest = ReleaseInfo("v9.9.9", "", "", "https://example.invalid/release", "equip1-update.tar.gz", "https://example.invalid/equip1-update.tar.gz", None)
    try:
        updater._install_bundle(archive_path, latest)
        raise AssertionError("expected update failure")
    except UpdateError:
        pass

    assert (app_dir / "uis" / "marker.txt").read_text(encoding="utf-8") == "old uis\n"
    assert (app_dir / "fonts" / "marker.txt").read_text(encoding="utf-8") == "old fonts\n"
    assert (app_dir / "equip1d" / "marker.txt").read_text(encoding="utf-8") == "old equip1d\n"
    assert (app_dir / "requirements.txt").read_text(encoding="utf-8") == "old requirements\n"
    assert "rolling back failed install" in log_file.read_text(encoding="utf-8")
PY

echo "ok - web update button and updater API are wired"
