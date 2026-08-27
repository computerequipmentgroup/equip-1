<script setup lang="ts">
const {
  state,
  connected,
  error,
  refresh,
  command,
  setLightColors,
  setLightsEnabled,
  setLightsBrightness,
  setRecordingFormat,
  setConversionSettings,
  setOledRotate180,
  setCaptureNaming,
  connectEvents,
  mock,
} = useEquip1State();
const {
  captures,
  error: capturesError,
  load,
  downloadUrl,
  watchUrl,
  createSidecar,
  deleteCapture,
} = useEquip1Captures();
const { system, error: systemError, load: loadSystem } = useEquip1System();
const config = useRuntimeConfig();

type UpdateStatus = Record<string, any>;
const defaultSoftwareVersion = "v0.1.0";
const ssidMaxLabelLength = 18;
const truncateSsid = (value: any) => {
  const text = String(value || "").trim();
  return text.length > ssidMaxLabelLength ? `${text.slice(0, ssidMaxLabelLength - 1)}…` : text;
};
const showNativeMessage = (message: string) => {
  if (import.meta.client) window.alert(message);
};
const formatUpdateVersion = (value: any) => {
  const text = String(value || "").trim();
  const exact = text.match(/^v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$/i);
  if (exact) return `v${exact[1]}`;
  const embedded = text.match(/(?:^|[^0-9A-Za-z])v?(\d+\.\d+\.\d+)(?:[^0-9A-Za-z]|$)/i);
  return embedded ? `v${embedded[1]}` : defaultSoftwareVersion;
};

const defaultCaptureNaming = { prefix: "capture_", template: "{date}_{time}" };
const captureNamingVariables = [
  "date",
  "time",
  "datetime",
  "year",
  "month",
  "day",
  "hour",
  "minute",
  "second",
];
const captureStem = (capture: Record<string, any>) => {
  const name = String(capture.name || "");
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(0, dot) : name;
};
const captureExt = (capture: Record<string, any>) =>
  String(capture.name || "")
    .split(".")
    .pop()
    ?.toLowerCase() || "";
const isSidecarCapture = (capture: Record<string, any>) =>
  captureExt(capture) === "mp4";
const isTemporaryCapture = (capture: Record<string, any>) =>
  captureStem(capture).endsWith(".tmp");
const groupedCaptures = computed(() => {
  const groups = new Map<
    string,
    { key: string; primary: Record<string, any> | null; sidecars: Record<string, any>[] }
  >();
  for (const capture of captures.value) {
    if (isTemporaryCapture(capture)) continue;
    const key = captureStem(capture);
    if (!groups.has(key)) groups.set(key, { key, primary: null, sidecars: [] });
    const group = groups.get(key)!;
    if (isSidecarCapture(capture)) group.sidecars.push(capture);
    else group.primary = capture;
  }
  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      primary: group.primary || group.sidecars[0] || null,
      sidecars: group.sidecars.sort(
        (a, b) => Number(b.modified_at || 0) - Number(a.modified_at || 0),
      ),
    }))
    .filter((group) => group.primary)
    .sort(
      (a, b) =>
        Number(b.primary?.modified_at || 0) - Number(a.primary?.modified_at || 0),
    );
});
const capturePageSize = 6;
const capturePage = ref(1);
const capturePageCount = computed(() =>
  Math.max(1, Math.ceil(groupedCaptures.value.length / capturePageSize)),
);
const paginatedCaptures = computed(() => {
  const start = (capturePage.value - 1) * capturePageSize;
  return groupedCaptures.value.slice(start, start + capturePageSize);
});
const setCapturePage = (page: number) => {
  const next = Math.max(1, Math.min(capturePageCount.value, page));
  capturePage.value = next;
  openCaptureKey.value = null;
  watchingCaptureKey.value = null;
};
type CaptureGroup = {
  key: string;
  primary: Record<string, any> | null;
  sidecars: Record<string, any>[];
};

const openCaptureKey = ref<string | null>(null);
const watchingCaptureKey = ref<string | null>(null);
const convertingWatchKey = ref<string | null>(null);
const watchRequestId = ref(0);
const toggleCaptureMenu = (key: string) => {
  openCaptureKey.value = openCaptureKey.value === key ? null : key;
  if (openCaptureKey.value !== key) {
    watchingCaptureKey.value = null;
    if (convertingWatchKey.value === key) {
      convertingWatchKey.value = null;
      watchRequestId.value += 1;
    }
  }
};
const watchTarget = (group: Pick<CaptureGroup, "primary" | "sidecars">) =>
  group.sidecars.find((sidecar) => captureExt(sidecar) === "mp4") || group.primary;
const mp4SidecarForKey = (key: string) =>
  captures.value.find(
    (capture) => captureStem(capture) === key && captureExt(capture) === "mp4",
  ) || null;
const mp4NameForCapture = (capture: Record<string, any>) => {
  const name = String(capture.name || "");
  const dot = name.lastIndexOf(".");
  return `${dot >= 0 ? name.slice(0, dot) : name}.mp4`;
};
const conversionMatchesCapture = (capture: Record<string, any>) => {
  const current = conversion.value;
  if (!current?.active) return false;
  const targetName = mp4NameForCapture(capture);
  return current.source === capture.name || current.target === targetName;
};
const captureHasMp4Sidecar = (group: Pick<CaptureGroup, "sidecars">) =>
  group.sidecars.some((sidecar) => captureExt(sidecar) === "mp4");
const conversionProgressPercent = () =>
  Math.max(0, Math.min(100, Math.round(Number(conversion.value?.progress_percent || 0))));
const conversionMatchesGroup = (group: Pick<CaptureGroup, "primary">) =>
  Boolean(group.primary && conversionMatchesCapture(group.primary));
const captureConversionStatus = (group: CaptureGroup) => {
  if (conversionMatchesGroup(group)) return `conversion ${conversionProgressPercent()}%`;
  if (captureHasMp4Sidecar(group)) return "conversion ready";
  return "";
};
const captureConversionActionLabel = (group: CaptureGroup) => {
  if (conversionMatchesGroup(group)) return `Converting ${conversionProgressPercent()}%`;
  if (captureHasMp4Sidecar(group)) return "Conversion ready";
  return "Create conversion";
};
const waitForMp4Sidecar = async (
  groupKey: string,
  primary: Record<string, any>,
  token: number,
) => {
  const targetName = mp4NameForCapture(primary);
  while (watchRequestId.value === token) {
    const sidecar = mp4SidecarForKey(groupKey);
    if (sidecar) return sidecar;
    const current = conversion.value;
    if (
      !current?.active &&
      current?.last_error &&
      (current.source === primary.name || current.target === targetName)
    ) {
      throw new Error(String(current.last_error));
    }
    await wait(1200);
    await Promise.all([load(), refresh()]);
  }
  return null;
};
const ensureWatchTarget = async (group: CaptureGroup, token: number) => {
  const existingMp4 = mp4SidecarForKey(group.key);
  if (existingMp4) return existingMp4;
  const target = watchTarget(group);
  if (target && captureExt(target) === "mp4") return target;
  const primary = group.primary;
  if (!primary) return target || null;
  if (isSidecarCapture(primary)) return primary;
  if (!conversionMatchesCapture(primary)) await createSidecar(primary);
  await Promise.all([load(), refresh()]);
  return mp4SidecarForKey(group.key) || waitForMp4Sidecar(group.key, primary, token);
};
const toggleCaptureWatch = async (group: CaptureGroup) => {
  if (watchingCaptureKey.value === group.key) {
    watchingCaptureKey.value = null;
    return;
  }
  if (convertingWatchKey.value) return;
  const token = watchRequestId.value + 1;
  watchRequestId.value = token;
  convertingWatchKey.value = group.key;
  watchingCaptureKey.value = null;
  try {
    actionError.value = null;
    const target = await ensureWatchTarget(group, token);
    if (target && watchRequestId.value === token) watchingCaptureKey.value = group.key;
  } catch (err: any) {
    if (watchRequestId.value === token) {
      actionError.value = err?.data?.detail || err?.message || "Could not prepare video";
    }
  } finally {
    if (watchRequestId.value === token) convertingWatchKey.value = null;
  }
};

const mode = computed(() => state.value?.mode || "offline");
const isMounting = computed(() => mode.value === "mounting");
const recording = computed(() => state.value?.recording || {});
const storage = computed(() => state.value?.storage || {});
const deviceSettings = computed(() => state.value?.settings || {});
const conversion = computed(() => state.value?.conversion || {});
const mp4ConversionModes = ["off", "foreground", "background"];
const mp4ConversionMode = computed(() => {
  const mode = String(
    conversion.value.auto_mp4_mode ||
      (conversion.value.auto_mp4_enabled !== false ? "background" : "off"),
  ).toLowerCase();
  return mp4ConversionModes.includes(mode) ? mode : "off";
});
const mp4ExportEnabled = computed(() => mp4ConversionMode.value !== "off");
const mp4ConversionModeLabel = computed(() => {
  if (mp4ConversionMode.value === "foreground") return "Blocking";
  if (mp4ConversionMode.value === "background") return "Background";
  return "Off";
});
const mp4DeinterlaceEnabled = computed(
  () => conversion.value.mp4_deinterlace_enabled === true,
);
const mp4DeinterlaceAlgorithmLabel = computed(() => {
  if (!mp4DeinterlaceEnabled.value) return "";
  const algorithm = String(
    conversion.value.mp4_deinterlace_algorithm || "yadif",
  ).toLowerCase();
  return algorithm === "nnedi3" && !conversion.value.mp4_deinterlace_fallback
    ? "NNEDI3"
    : "YADIF fallback";
});
const recordingFormat = computed(() =>
  String(deviceSettings.value.recording_format || "mov").toLowerCase(),
);
const recordingFormatOptions = ["dv", "mov", "avi"];
const oledRotate180 = computed(() =>
  Boolean(deviceSettings.value.oled_rotate_180),
);
const oledFlipLabel = computed(() =>
  oledRotate180.value ? "Buttons left" : "Buttons right",
);
const captureNaming = computed(
  () => state.value?.capture_naming || defaultCaptureNaming,
);
const captureNamingPatternFromState = computed(
  () =>
    `${captureNaming.value.prefix ?? defaultCaptureNaming.prefix}${captureNaming.value.template || defaultCaptureNaming.template}`,
);
const namingDirty = computed(
  () => captureNamingPattern.value !== captureNamingPatternFromState.value,
);
const actionError = ref<string | null>(null);
const captureNamingPattern = ref(
  `${defaultCaptureNaming.prefix}${defaultCaptureNaming.template}`,
);
const namingSaving = ref(false);
const namingSaved = ref(false);
const namingTouched = ref(false);
const namingError = ref<string | null>(null);
const namingSaveTimer = ref<ReturnType<typeof setTimeout> | null>(null);
const systemInterval = ref<ReturnType<typeof setInterval> | null>(null);
const closedCardsStorageKey = "equip1.closedCards";
const closedCards = ref<Record<string, boolean>>({});
const loadClosedCards = () => {
  if (!import.meta.client) return;
  try {
    const saved = JSON.parse(
      localStorage.getItem(closedCardsStorageKey) || "{}",
    );
    if (saved && typeof saved === "object" && !Array.isArray(saved)) {
      closedCards.value = Object.fromEntries(
        Object.entries(saved).filter(([, value]) => typeof value === "boolean"),
      ) as Record<string, boolean>;
    }
  } catch {
    closedCards.value = {};
  }
};
const saveClosedCards = () => {
  if (!import.meta.client) return;
  localStorage.setItem(
    closedCardsStorageKey,
    JSON.stringify(closedCards.value),
  );
};
const cardOpen = (name: string) => !closedCards.value[name];
const toggleCard = (name: string) => {
  closedCards.value = { ...closedCards.value, [name]: cardOpen(name) };
  saveClosedCards();
};

const elapsedParts = computed(() => {
  const total = Number(recording.value.elapsed_seconds || 0);
  return {
    hh: Math.floor(total / 3600)
      .toString()
      .padStart(2, "0"),
    mm: Math.floor((total % 3600) / 60)
      .toString()
      .padStart(2, "0"),
    ss: Math.floor(total % 60)
      .toString()
      .padStart(2, "0"),
  };
});
const elapsed = computed(
  () =>
    `${elapsedParts.value.hh}:${elapsedParts.value.mm}:${elapsedParts.value.ss}`,
);
const freeGb = computed(() =>
  ((storage.value.free_bytes || 0) / 1024 / 1024 / 1024).toFixed(1),
);
const usedGb = computed(() =>
  ((storage.value.used_bytes || 0) / 1024 / 1024 / 1024).toFixed(1),
);
const storagePercent = computed(() => {
  const total = Number(storage.value.total_bytes || 0);
  const used = Number(storage.value.used_bytes || 0);
  if (!total) return 0;
  return Math.max(0, Math.min(100, Math.round((used / total) * 100)));
});
const storageDeviceLabel = computed(() => {
  const kind = String(storage.value.device_kind || "").toLowerCase();
  if (kind === "usb") return "USB";
  if (kind === "sd") return "SD card";
  if (kind === "nvme") return "NVMe";
  if (kind === "transfer") return "USB transfer";
  if (kind === "mounting") return "Mounting";
  if (kind === "rootfs") return "Rootfs";

  const device = String(storage.value.device || "");
  if (device.startsWith("/dev/sd")) return "USB";
  if (device.startsWith("/dev/mmcblk")) return "SD card";
  if (device.startsWith("/dev/nvme")) return "NVMe";
  if (device === "rootfs" || device === "/dev/root") return "Rootfs";
  return "Unknown";
});
const cpuPercent = computed(() =>
  Math.max(
    0,
    Math.min(100, Math.round(Number(system.value?.cpu?.percent || 0))),
  ),
);
const memoryPercent = computed(() =>
  Math.max(
    0,
    Math.min(100, Math.round(Number(system.value?.memory?.percent || 0))),
  ),
);
const temperaturePercent = computed(() =>
  Math.max(
    0,
    Math.min(100, Math.round(Number(system.value?.temperature?.percent || 0))),
  ),
);
const updateStatus = ref<UpdateStatus | null>(null);
const wifiSsid = ref("");
const wifiPassword = ref("");
const wifiNetworks = ref<string[]>([]);
const wifiScanning = ref(false);
const wifiSaving = ref(false);
const wifiMessage = ref<string | null>(null);
const wifiError = ref<string | null>(null);
const wifiSetupOpen = ref(false);
const wifiSwitchPending = ref(false);
const updateChecking = ref(false);
const updateApplying = ref(false);
const updateUpToDateVisible = ref(false);
const updateUpToDateTimer = ref<ReturnType<typeof setTimeout> | null>(null);
const updateError = ref<string | null>(null);
const recDockHidden = ref(false);
const recDockHideScrollY = 220;
const updateAvailable = computed(() => Boolean(updateStatus.value?.available));
const updateNetworkMode = computed(() =>
  String(state.value?.network?.mode || "").toLowerCase(),
);
const networkIp = computed(() =>
  String(state.value?.network?.ip || state.value?.network?.url || "10.42.0.1").replace(/^https?:\/\//, "").split("/", 1)[0],
);
const isApIp = computed(() => networkIp.value === "10.42.0.1");
const isAccessPointNetwork = computed(() =>
  isApIp.value || (["access_point", "ap"].includes(updateNetworkMode.value) && !networkIp.value),
);
const networkUrlLabel = computed(() => networkIp.value);
const connectedWifiSsid = computed(() => {
  if (isAccessPointNetwork.value) return "";
  if (!["lan", "client", "station", "sta"].includes(updateNetworkMode.value)) return "";
  return truncateSsid(state.value?.network?.ssid);
});
const updateNeedsWifi = computed(
  () => isAccessPointNetwork.value || updateNetworkMode.value === "offline",
);
const updateNetworkHint = computed(() =>
  updateNeedsWifi.value ? "Connect Equip-1 to Wi-Fi for updates." : "",
);
const updateCurrentLabel = computed(() => {
  const current = updateStatus.value?.current || {};
  return formatUpdateVersion(current.tag || current.version);
});
const updateLatestLabel = computed(() =>
  updateStatus.value?.latest?.tag ? formatUpdateVersion(updateStatus.value.latest.tag) : "No update",
);
const updateSoftwareLabel = computed(() => {
  if (updateAvailable.value) return updateLatestLabel.value;
  if (updateUpToDateVisible.value) return "Already up to date.";
  return updateCurrentLabel.value;
});
const recordDimmed = computed(
  () => !["idle", "recording"].includes(mode.value),
);
const convertAllDisabled = computed(
  () =>
    ["recording", "mounting", "usb_transfer", "offline", "converting"].includes(
      mode.value,
    ) || Boolean(conversion.value.active),
);
const previewing = ref(false);
const previewLoaded = ref(false);
const previewError = ref<string | null>(null);
const previewNonce = ref(0);
const previewAspectRatio = ref("4 / 3");
const previewImage = ref<HTMLImageElement | null>(null);
const previewRetryTimer = ref<ReturnType<typeof setTimeout> | null>(null);
const previewDimensionInterval = ref<ReturnType<typeof setInterval> | null>(null);
const previewAllowed = computed(
  () => connected.value && ["idle", "recording"].includes(mode.value),
);
const previewSrc = computed(
  () => `${config.public.apiBase}/preview.mjpg?t=${previewNonce.value}`,
);
// Absolute URL so it resolves inside a separate player app, not just the
// dashboard's own origin. The daemon serves both the web UI and the stream.
const streamUrl = computed(() => {
  const base = import.meta.client ? window.location.origin : "";
  return `${base}${config.public.apiBase}/stream.mkv`;
});
// Displayed without the scheme so the URL reads cleaner; the href keeps it.
const streamUrlLabel = computed(() =>
  streamUrl.value.replace(/^https?:\/\//, ""),
);
const previewStatus = computed(() => {
  if (previewing.value) return "Live";
  if (mode.value === "recording") return "Recording";
  if (mode.value === "usb_transfer") return "USB";
  if (mode.value === "mounting") return "Mounting";
  if (mode.value === "no_camera") return "No cam";
  return "Off";
});
// Shown on the placeholder while the MJPEG stream is not yet flowing — most
// visible during the record/stop transition, when the preview pipeline is torn
// down and re-established against the new source.
const placeholderStatus = computed(() => {
  if (!connected.value) return "daemon offline";
  if (previewError.value) return "preview unavailable, retrying";
  if (mode.value === "recording") return "buffering capture stream…";
  if (mode.value === "idle") return "acquiring DV signal…";
  if (mode.value === "usb_transfer") return "usb disk mode";
  if (mode.value === "mounting") return "mounting storage…";
  if (mode.value === "no_camera") return "no DV/HDV camera detected";
  return "camera offline";
});

const lightsLocked = ref(true);
const lightsEnabled = computed(() => state.value?.lights?.enabled !== false);
const lightColors = computed<number[][]>(() => {
  const colors = state.value?.lights?.default_colors;
  if (Array.isArray(colors) && colors.length) {
    return colors.map((rgb) =>
      Array.isArray(rgb)
        ? rgb.slice(0, 3).map((v) => Number(v) || 0)
        : [0, 0, 255],
    );
  }
  return [
    [0, 0, 255],
    [0, 0, 255],
    [0, 0, 255],
  ];
});
const rgbToHex = (rgb: number[]) =>
  `#${rgb
    .map((v) =>
      Math.max(0, Math.min(255, Math.round(v)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
const lightHexes = computed(() => lightColors.value.map(rgbToHex));
const lightsBrightness = computed(() => {
  const value = Number(state.value?.lights?.brightness);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0.25;
});
const lightsBrightnessPercent = computed(() =>
  Math.round(lightsBrightness.value * 100),
);
const lightsBrightnessRatio = computed(() =>
  Math.max(0, Math.min(1, (lightsBrightnessPercent.value - 1) / 99)),
);
const lightsBrightnessKnobLeft = computed(
  () =>
    `calc(0.2rem + ${lightsBrightnessRatio.value * 100}% - ${lightsBrightnessRatio.value * 1.56}rem)`,
);
const onLightInput = (index: number, event: Event) => {
  const match = /^#?([0-9a-fA-F]{6})$/.exec(
    (event.target as HTMLInputElement).value,
  );
  if (!match) return;
  const int = parseInt(match[1], 16);
  const rgb = [(int >> 16) & 255, (int >> 8) & 255, int & 255];
  // Locked: every LED tracks the one being edited. Unlocked: only this LED.
  const next = lightColors.value.map((existing, i) =>
    lightsLocked.value || i === index ? rgb : existing,
  );
  setLightColors(next);
};
const toggleLightsEnabled = () => setLightsEnabled(!lightsEnabled.value);
const selectRecordingFormat = (format: string) => {
  if (mode.value === "recording") return;
  setRecordingFormat(format);
};
const toggleMp4Export = () => {
  const nextMode =
    mp4ConversionMode.value === "off"
      ? "foreground"
      : mp4ConversionMode.value === "foreground"
        ? "background"
        : "off";
  setConversionSettings({ auto_mp4_mode: nextMode });
};
const toggleMp4Deinterlace = () =>
  setConversionSettings({
    mp4_deinterlace_enabled: !mp4DeinterlaceEnabled.value,
  });
const toggleOledRotate180 = () => setOledRotate180(!oledRotate180.value);
const onLightsBrightnessInput = (event: Event) => {
  const percent = Number((event.target as HTMLInputElement).value);
  if (!Number.isFinite(percent)) return;
  setLightsBrightness(percent / 100);
};

const sizeGb = (bytes: number) =>
  `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
const captureMinutes = (
  capture: Record<string, any> | null | undefined,
) => {
  const durationSeconds = Number(capture?.duration_seconds || 0);
  if (durationSeconds > 0) return Math.max(1, Math.round(durationSeconds / 60));
  const sizeBytes = Number(capture?.size_bytes || 0);
  if (sizeBytes <= 0) return 0;
  return Math.max(1, Math.round(sizeBytes / (216 * 1024 * 1024)));
};
const systemLoadLabel = computed(() => {
  const load = Number(system.value?.cpu?.load_1m || 0).toFixed(2);
  const count = Number(system.value?.cpu?.count || 0);
  return count ? `${load} / ${count} cores` : load;
});
const systemMemoryLabel = computed(() => {
  const used = Number(system.value?.memory?.used_bytes || 0) / 1024 / 1024;
  const total = Number(system.value?.memory?.total_bytes || 0) / 1024 / 1024;
  if (!total) return "Unknown";
  return `${Math.round(used)} / ${Math.round(total)} MB`;
});
const systemTempLabel = computed(() => {
  const temp = system.value?.temperature?.celsius;
  return typeof temp === "number" ? `${temp.toFixed(1)} °C` : "Unknown";
});
const systemModelLabel = computed(() => String(system.value?.model || "ROCK compute"));
const modified = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || value === "")
    return "Unknown date";
  const numeric = Number(value);
  const millis = Number.isFinite(numeric)
    ? numeric < 10_000_000_000
      ? numeric * 1000
      : numeric
    : Date.parse(String(value));
  const date = new Date(millis);
  return Number.isNaN(date.getTime()) ? "Unknown date" : date.toLocaleString();
};
const captureThumbnailUrl = (capture: Record<string, any> | null | undefined) => {
  const url = String(capture?.thumbnail_url || "");
  if (!url || url === "mock-thumbnail") return "";
  if (/^(data:|blob:|https?:\/\/)/i.test(url)) return url;
  if (url.startsWith("/api/")) {
    const apiBase = String(config.public.apiBase || "/api").replace(/\/$/, "");
    return `${apiBase}${url.slice(4)}`;
  }
  return url;
};

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const saveCaptureNaming = async (throwOnError = false) => {
  if (namingSaveTimer.value) {
    clearTimeout(namingSaveTimer.value);
    namingSaveTimer.value = null;
  }
  const pattern = captureNamingPattern.value;
  namingSaving.value = true;
  namingSaved.value = false;
  namingError.value = null;
  try {
    await setCaptureNaming("", pattern);
    if (captureNamingPattern.value === pattern) {
      namingTouched.value = false;
      namingSaved.value = true;
    }
  } catch (err: any) {
    namingError.value =
      err?.data?.detail || err?.message || "Could not save file name settings";
    if (throwOnError) throw err;
  } finally {
    namingSaving.value = false;
  }
};
const scheduleCaptureNamingSave = () => {
  namingTouched.value = true;
  namingSaved.value = false;
  if (namingSaveTimer.value) clearTimeout(namingSaveTimer.value);
  namingSaveTimer.value = setTimeout(() => {
    namingSaveTimer.value = null;
    if (namingDirty.value || namingTouched.value) saveCaptureNaming();
  }, 700);
};
const appendCaptureNamingVariable = (variable: string) => {
  if (mode.value === "recording") return;
  captureNamingPattern.value = `${captureNamingPattern.value}{${variable}}`;
  scheduleCaptureNamingSave();
};

const updateRecDockVisibility = () => {
  if (!import.meta.client) return;
  recDockHidden.value = window.scrollY > recDockHideScrollY;
};

const showUpToDateBriefly = () => {
  updateUpToDateVisible.value = true;
  if (updateUpToDateTimer.value) clearTimeout(updateUpToDateTimer.value);
  updateUpToDateTimer.value = setTimeout(() => {
    updateUpToDateVisible.value = false;
    updateUpToDateTimer.value = null;
  }, 4000);
};

const loadUpdateStatus = async (check = false, prompt = false) => {
  if (check && updateNeedsWifi.value) {
    updateError.value = null;
    return;
  }
  if (mock.value) {
    updateStatus.value = {
      current: { version: defaultSoftwareVersion, tag: defaultSoftwareVersion },
      latest: null,
      available: false,
      last_checked_at: check ? new Date().toISOString() : null,
      last_error: null,
    };
    if (check) showUpToDateBriefly();
    return;
  }
  updateChecking.value = check;
  updateError.value = null;
  try {
    updateStatus.value = await $fetch<UpdateStatus>(
      `${config.public.apiBase}/update${check ? "/check" : ""}`,
      check ? { method: "POST" } : undefined,
    );
    if (prompt && updateStatus.value?.available) {
      const install = !import.meta.client || window.confirm(`Install ${updateLatestLabel.value} now?`);
      if (install) await applyUpdate();
    }
    if (check && !updateStatus.value?.available && !updateStatus.value?.last_error) showUpToDateBriefly();
  } catch (err: any) {
    updateError.value = err?.data?.detail || err?.message || "Could not check for updates";
  } finally {
    updateChecking.value = false;
  }
};

const applyUpdate = async () => {
  updateApplying.value = true;
  updateError.value = null;
  try {
    updateStatus.value = await $fetch<UpdateStatus>(`${config.public.apiBase}/update/apply`, {
      method: "POST",
    });
  } catch (err: any) {
    updateError.value = err?.data?.detail || err?.message || "Could not install update";
  } finally {
    updateApplying.value = false;
  }
};

const scanWifiNetworks = async () => {
  wifiScanning.value = true;
  wifiError.value = null;
  try {
    if (mock.value) {
      wifiNetworks.value = ["Studio Wi-Fi", "Home Wi-Fi", "Guest"];
      if (!wifiSsid.value) wifiSsid.value = wifiNetworks.value[0];
      return;
    }
    const result = await $fetch<Record<string, any>>(`${config.public.apiBase}/network/wifi/scan`);
    wifiNetworks.value = Array.isArray(result?.ssids) ? result.ssids.map(String) : [];
    if (!wifiSsid.value && wifiNetworks.value.length) wifiSsid.value = wifiNetworks.value[0];
  } catch (err: any) {
    wifiError.value = err?.data?.detail || err?.message || "Could not scan Wi-Fi";
  } finally {
    wifiScanning.value = false;
  }
};

const openWifiSetup = () => {
  wifiSwitchPending.value = false;
  wifiSetupOpen.value = true;
  scanWifiNetworks();
};

const configureWifi = async () => {
  wifiSaving.value = true;
  wifiError.value = null;
  wifiMessage.value = null;
  wifiSwitchPending.value = false;
  try {
    if (mock.value) {
      state.value = {
        ...(state.value || {}),
        network: {
          mode: "lan",
          ssid: wifiSsid.value || "Studio Wi-Fi",
          ip: "192.168.1.42",
          url: "http://192.168.1.42",
          dashboard_url: "http://192.168.1.42",
        },
      };
      showNativeMessage("Joined Wi-Fi.");
    } else {
      const result = await $fetch<Record<string, any>>(`${config.public.apiBase}/network/wifi`, {
        method: "POST",
        body: { ssid: wifiSsid.value, password: wifiPassword.value },
      });
      const message = result?.message || "Switching to Wi-Fi. Reconnect using the IP shown on OLED.";
      wifiSwitchPending.value = true;
      showNativeMessage(message);
    }
    wifiPassword.value = "";
    wifiSetupOpen.value = false;
  } catch (err: any) {
    wifiError.value = err?.data?.detail || err?.message || "Could not save Wi-Fi";
  } finally {
    wifiSaving.value = false;
  }
};

const useAccessPointWifi = async () => {
  if (import.meta.client && !window.confirm("Switch back to AP mode?")) return;
  wifiSaving.value = true;
  wifiError.value = null;
  wifiMessage.value = null;
  wifiSwitchPending.value = false;
  try {
    if (mock.value) {
      state.value = {
        ...(state.value || {}),
        network: {
          mode: "ap",
          ssid: "Equip-1",
          ip: "10.42.0.1",
          url: "http://10.42.0.1",
          dashboard_url: "http://10.42.0.1",
        },
      };
      showNativeMessage("Switched to AP mode.");
    } else {
      const result = await $fetch<Record<string, any>>(`${config.public.apiBase}/network/ap`, {
        method: "POST",
      });
      showNativeMessage(result?.message || "Switching back to the Equip-1 access point.");
    }
  } catch (err: any) {
    wifiError.value = err?.data?.detail || err?.message || "Could not switch Wi-Fi mode";
  } finally {
    wifiSaving.value = false;
  }
};

const runCommand = async (name: string) => {
  try {
    actionError.value = null;
    if (name === "start-recording" && namingDirty.value) {
      if (namingSaveTimer.value) {
        clearTimeout(namingSaveTimer.value);
        namingSaveTimer.value = null;
      }
      await saveCaptureNaming(true);
    }
    if (name === "start-recording" && previewing.value) {
      previewing.value = false;
      await nextTick();
      await wait(250);
    }
    await command(name);
    await refresh();
  } catch (err: any) {
    actionError.value =
      err?.data?.detail || err?.message || `Could not run ${name}`;
    await refresh();
  }
};

const createCaptureSidecar = async (capture: Record<string, any>) => {
  try {
    actionError.value = null;
    await createSidecar(capture);
    await refresh();
  } catch (err: any) {
    actionError.value =
      err?.data?.detail || err?.message || "Could not create conversion";
  }
};
const deleteCaptureItem = async (capture: Record<string, any>, related = false) => {
  const message = related
    ? `Delete ${capture.name} and its conversion?`
    : `Delete ${capture.name}?`;
  if (import.meta.client && !window.confirm(message)) return;
  try {
    actionError.value = null;
    await deleteCapture(capture, related);
    if (related) {
      openCaptureKey.value = null;
      watchingCaptureKey.value = null;
    }
    await refresh();
  } catch (err: any) {
    actionError.value =
      err?.data?.detail || err?.message || "Could not delete capture";
  }
};

const startPreview = () => {
  if (!previewAllowed.value || previewing.value) return;
  if (previewRetryTimer.value) {
    clearTimeout(previewRetryTimer.value);
    previewRetryTimer.value = null;
  }
  previewError.value = null;
  previewLoaded.value = false;
  previewNonce.value = Date.now();
  previewing.value = true;
};

const updatePreviewAspectRatio = (img = previewImage.value) => {
  if (!img || img.naturalWidth <= 0 || img.naturalHeight <= 0) return;
  const next = `${img.naturalWidth} / ${img.naturalHeight}`;
  if (previewAspectRatio.value !== next) previewAspectRatio.value = next;
};

const handlePreviewLoad = (event: Event) => {
  updatePreviewAspectRatio(event.target as HTMLImageElement);
  previewLoaded.value = true;
};

const handlePreviewError = () => {
  previewError.value = "Preview unavailable";
  previewLoaded.value = false;
  previewing.value = false;
  if (previewAllowed.value && !previewRetryTimer.value) {
    previewRetryTimer.value = setTimeout(() => {
      previewRetryTimer.value = null;
      startPreview();
    }, 1000);
  }
};

watch(previewAllowed, (allowed) => {
  if (!allowed) {
    previewing.value = false;
    return;
  }
  startPreview();
});

watch(mode, async (next, previous) => {
  if (next === previous || !previewAllowed.value) return;
  if (previewing.value) {
    previewing.value = false;
    await nextTick();
    await wait(250);
  }
  startPreview();
});

watch(
  captureNaming,
  () => {
    if (namingTouched.value) return;
    captureNamingPattern.value = captureNamingPatternFromState.value;
  },
  { immediate: true, deep: true },
);

watch(capturePageCount, (pageCount) => {
  if (capturePage.value > pageCount) setCapturePage(pageCount);
});

onBeforeUnmount(() => {
  previewing.value = false;
  if (previewRetryTimer.value) clearTimeout(previewRetryTimer.value);
  if (previewDimensionInterval.value) clearInterval(previewDimensionInterval.value);
  if (updateUpToDateTimer.value) clearTimeout(updateUpToDateTimer.value);
  if (namingDirty.value || namingTouched.value) saveCaptureNaming();
  else if (namingSaveTimer.value) clearTimeout(namingSaveTimer.value);
  if (systemInterval.value) clearInterval(systemInterval.value);
  if (import.meta.client) window.removeEventListener("scroll", updateRecDockVisibility);
});

onMounted(async () => {
  loadClosedCards();
  await Promise.all([refresh(), load(), loadSystem(), loadUpdateStatus(false)]);
  connectEvents();
  setTimeout(() => {
    if (!updateNeedsWifi.value) loadUpdateStatus(true, true);
  }, 2000);
  systemInterval.value = setInterval(loadSystem, 3000);
  previewDimensionInterval.value = setInterval(() => updatePreviewAspectRatio(), 250);
  if (import.meta.client) {
    updateRecDockVisibility();
    window.addEventListener("scroll", updateRecDockVisibility, { passive: true });
  }
  if (previewAllowed.value) startPreview();
});
</script>

<template>
  <section class="screen">
    <p v-if="!connected" class="error full-span">Daemon connection lost.</p>
    <p v-if="error" class="error full-span">{{ error }}</p>
    <p v-if="actionError" class="error full-span">{{ actionError }}</p>
    <p v-if="state?.error" class="error full-span">
      {{ state.error.message }}: {{ state.error.detail }}
    </p>

    <article class="preview-section full-span">
      <div
        class="live-preview"
        :class="{ active: previewing, loaded: previewLoaded }"
        :style="{ '--preview-aspect': previewAspectRatio }"
      >
        <div class="live-placeholder">{{ placeholderStatus }}</div>
        <img
          v-if="previewing && !mock"
          ref="previewImage"
          :src="previewSrc"
          alt="Live DV/HDV preview"
          :class="{ loaded: previewLoaded }"
          @load="handlePreviewLoad"
          @error="handlePreviewError"
        />
      </div>
      <div
        class="preview-timecode timecode-fit big"
        :class="{ dimmed: recordDimmed }"
        aria-label="Elapsed recording time"
      >
        <span>{{ elapsedParts.hh }}</span
        ><b>:</b><span>{{ elapsedParts.mm }}</span
        ><b>:</b><span>{{ elapsedParts.ss }}</span>
      </div>
    </article>

    <article class="card">
      <div class="card-top" @click="toggleCard('storage')">
        <span class="card-title">Storage</span>
      </div>
      <template v-if="cardOpen('storage')">
        <div
          class="storage-bar"
          :class="{ pending: isMounting }"
          aria-label="Storage usage"
        >
          <span :style="{ width: isMounting ? '45%' : `${storagePercent}%` }" />
        </div>
        <div class="storage-legend">
          <span>{{ isMounting ? "Please wait" : `${usedGb} GB used` }}</span>
          <span>{{
            isMounting ? "Preparing /data" : `${freeGb} GB free`
          }}</span>
        </div>
        <div class="storage-summary hero-subtitle">
          <span
            >{{ storage.recording_minutes_available || 0 }} minutes
            available</span
          >
          <span>{{ storageDeviceLabel }}</span>
        </div>
      </template>
    </article>

    <article class="card full-span">
      <div class="card-top" @click="toggleCard('captures')">
        <span class="card-title">Captures</span>
      </div>
      <template v-if="cardOpen('captures')">
        <p v-if="capturesError" class="error">{{ capturesError }}</p>
        <div v-if="groupedCaptures.length" class="list captures-list">
          <div
            v-for="group in paginatedCaptures"
            :key="group.key"
            class="capture-group"
          >
            <button
              type="button"
              class="row capture-row capture-row-button"
              :class="{ open: openCaptureKey === group.key }"
              :aria-expanded="openCaptureKey === group.key"
              @click="toggleCaptureMenu(group.key)"
            >
              <div class="capture-thumb" aria-hidden="true">
                <img
                  v-if="captureThumbnailUrl(group.primary)"
                  :src="captureThumbnailUrl(group.primary)"
                  alt=""
                  loading="lazy"
                />
                <span v-else></span>
              </div>
              <div class="row-main">
                <span class="row-title">{{ group.primary?.name }}</span>
                <div class="row-meta">
                  {{ sizeGb(group.primary?.size_bytes || 0) }} ·
                  {{ captureMinutes(group.primary) }} mins
                  <span v-if="captureConversionStatus(group)"> · {{ captureConversionStatus(group) }}</span>
                </div>
                <div class="row-meta">
                  {{ modified(group.primary?.modified_at) }}
                </div>
              </div>
            </button>
            <div v-if="openCaptureKey === group.key" class="capture-menu">
              <div
                v-if="watchingCaptureKey === group.key && watchTarget(group)"
                class="capture-watch"
              >
                <video
                  :src="watchUrl(watchTarget(group)!)"
                  controls
                  playsinline
                  preload="metadata"
                ></video>
              </div>
              <div class="capture-menu-actions">
                <button
                  type="button"
                  class="capture-menu-action"
                  :disabled="Boolean(convertingWatchKey) || !watchTarget(group)"
                  @click.stop="toggleCaptureWatch(group)"
                >
                  <span>{{ convertingWatchKey === group.key ? "Preparing video…" : watchingCaptureKey === group.key ? "Hide video" : "Watch video" }}</span>
                </button>
                <a
                  v-if="group.primary"
                  class="capture-menu-action"
                  :href="downloadUrl(group.primary)"
                  :download="group.primary.name"
                  @click.stop
                >
                  <span>Download capture</span>
                </a>
                <button
                  v-if="group.primary && !isSidecarCapture(group.primary)"
                  type="button"
                  class="capture-menu-action"
                  :disabled="Boolean(convertingWatchKey) || convertAllDisabled || captureHasMp4Sidecar(group)"
                  @click.stop="createCaptureSidecar(group.primary)"
                >
                  <span>{{ captureConversionActionLabel(group) }}</span>
                </button>
                <button
                  v-if="group.primary"
                  type="button"
                  class="capture-menu-action danger"
                  :disabled="mode === 'recording' || isMounting || mode === 'usb_transfer'"
                  @click.stop="deleteCaptureItem(group.primary, true)"
                >
                  <span>Delete capture</span>
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="capturePageCount > 1" class="capture-pagination">
          <button
            type="button"
            class="capture-page-button"
            :disabled="capturePage <= 1"
            @click="setCapturePage(capturePage - 1)"
          >
            Prev
          </button>
          <span>Page {{ capturePage }} / {{ capturePageCount }}</span>
          <button
            type="button"
            class="capture-page-button"
            :disabled="capturePage >= capturePageCount"
            @click="setCapturePage(capturePage + 1)"
          >
            Next
          </button>
        </div>
        <p v-if="!groupedCaptures.length" class="empty no-captures-empty">No captures yet.</p>
      </template>
    </article>

    <article class="card full-span">
      <div class="card-top" @click="toggleCard('recording-format')">
        <span class="card-title">Format</span>
      </div>
      <template v-if="cardOpen('recording-format')">
        <div class="setting-row">
          <div class="actions three no-top">
            <button
              v-for="format in recordingFormatOptions"
              :key="format"
              type="button"
              class="gloss-pill"
              :class="{ 'gloss-green': recordingFormat === format }"
              :disabled="mode === 'recording'"
              @click="selectRecordingFormat(format)"
            >
              <span>{{ format.toUpperCase() }}</span>
            </button>
          </div>
        </div>
      </template>
    </article>
    <article class="card full-span">
      <div class="card-top" @click="toggleCard('toggles')">
        <span class="card-title">Toggles</span>
      </div>
      <template v-if="cardOpen('toggles')">
        <div class="setting-row conversion-toggles">
          <label class="switch-row">
            <span class="switch-label">MP4 Conversion<span v-if="mp4ExportEnabled">: {{ mp4ConversionModeLabel }}</span></span>
            <button
              type="button"
              class="gloss-switch tri-switch"
              :class="mp4ConversionMode"
              :aria-label="`Set MP4 conversion mode (currently ${mp4ConversionModeLabel})`"
              @click="toggleMp4Export"
            >
              <span class="switch-knob"></span>
            </button>
          </label>
          <label class="switch-row">
            <span class="switch-label">
              Deinterlace Conversion<span v-if="mp4DeinterlaceAlgorithmLabel">: {{ mp4DeinterlaceAlgorithmLabel }}</span>
            </span>
            <button
              type="button"
              class="gloss-switch"
              :class="{ on: mp4DeinterlaceEnabled }"
              :aria-pressed="mp4DeinterlaceEnabled"
              aria-label="Toggle MP4 deinterlacing"
              @click="toggleMp4Deinterlace"
            >
              <span class="switch-knob"></span>
            </button>
          </label>
          <label class="switch-row">
            <span class="switch-label">Flip Display: {{ oledFlipLabel }}</span>
            <button
              type="button"
              class="gloss-switch"
              :class="{ on: oledRotate180 }"
              :aria-pressed="oledRotate180"
              aria-label="Toggle display 180-degree flip"
              @click="toggleOledRotate180"
            >
              <span class="switch-knob"></span>
            </button>
          </label>
        </div>
      </template>
    </article>
    <article class="card full-span">
      <div class="card-top" @click="toggleCard('file-names')">
        <span class="card-title">Filename</span>
      </div>
      <template v-if="cardOpen('file-names')">
        <p v-if="namingError" class="error">{{ namingError }}</p>
        <div class="naming-grid">
          <label class="field-row">
            <input
              v-model="captureNamingPattern"
              class="text-input filename-label"
              type="text"
              maxlength="96"
              placeholder="capture_{date}_{time}"
              aria-label="Filename"
              :disabled="mode === 'recording'"
              @input="scheduleCaptureNamingSave"
              @change="saveCaptureNaming"
              @blur="saveCaptureNaming"
            />
          </label>
        </div>
        <div class="naming-variables" aria-label="Available filename variables">
          <button
            v-for="variable in captureNamingVariables"
            :key="variable"
            class="naming-variable-chip"
            type="button"
            :disabled="mode === 'recording'"
            @click="appendCaptureNamingVariable(variable)"
          >
            <code>{{ "{" + variable + "}" }}</code>
          </button>
        </div>
      </template>
    </article>
    <article class="card full-span">
      <div class="card-top" @click="toggleCard('lights')">
        <span class="card-title">Lights</span>
      </div>
      <template v-if="cardOpen('lights')">
        <div class="lights-row">
          <label
            v-for="(hex, index) in lightHexes"
            :key="index"
            class="light-swatch"
            :style="{
              background: hex,
              opacity: lightsEnabled ? 1 : 0.38,
              boxShadow: lightsEnabled
                ? `0 0 10px ${hex}, 0 0 24px ${hex}, 0 0 42px ${hex}`
                : 'none',
            }"
          >
            <input
              type="color"
              :value="hex"
              @input="onLightInput(index, $event)"
              :aria-label="`LED ${index + 1} color`"
            />
          </label>
          <button
            type="button"
            class="light-lock"
            :class="{ locked: lightsLocked, disabled: !lightsEnabled }"
            :aria-pressed="lightsLocked"
            :aria-label="
              lightsLocked
                ? 'Unlock LEDs to set individually'
                : 'Lock LEDs to one color'
            "
            @click="lightsLocked = !lightsLocked"
          >
            <svg
              v-if="lightsLocked"
              class="lock-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <svg
              v-else
              class="lock-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 9.9-1" />
            </svg>
          </button>
          <button
            type="button"
            class="light-toggle"
            :class="{ off: !lightsEnabled }"
            :aria-pressed="!lightsEnabled"
            :aria-label="lightsEnabled ? 'Turn LEDs off' : 'Turn LEDs on'"
            @click="toggleLightsEnabled"
          >
            <svg
              class="power-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M12 2v10" />
              <path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
            </svg>
          </button>
          <label
            class="light-brightness"
            :style="{
              '--value': `${lightsBrightnessPercent}%`,
              '--knob-left': lightsBrightnessKnobLeft,
            }"
          >
            <span class="gloss-slider" aria-hidden="true">
              <span class="gloss-slider-knob"></span>
            </span>
            <input
              type="range"
              min="1"
              max="100"
              step="1"
              :value="lightsBrightnessPercent"
              :disabled="!lightsEnabled"
              aria-label="LED brightness"
              @input="onLightsBrightnessInput"
            />
          </label>
        </div>
      </template>
    </article>
    <article class="card full-span">
      <div class="card-top" @click="toggleCard('system')">
        <span class="card-title">System</span>
        <span class="spec-chip">{{ systemModelLabel }}</span>
      </div>
      <template v-if="cardOpen('system')">
        <p v-if="systemError" class="error system-notification">{{ systemError }}</p>
        <div class="system-bars">
          <div class="system-row system-stat-row">
            <div class="storage-legend">
              <span>CPU load</span><span>{{ systemLoadLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="CPU load">
              <span :style="{ width: `${cpuPercent}%` }" />
            </div>
          </div>
          <div class="system-row system-stat-row">
            <div class="storage-legend">
              <span>Memory</span><span>{{ systemMemoryLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="Memory usage">
              <span :style="{ width: `${memoryPercent}%` }" />
            </div>
          </div>
          <div class="system-row system-stat-row">
            <div class="storage-legend">
              <span>Temperature</span><span>{{ systemTempLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="Temperature">
              <span :style="{ width: `${temperaturePercent}%` }" />
            </div>
          </div>
          <div class="system-row system-version-row">
            <div class="storage-legend">
              <span>{{ updateAvailable ? "Update available" : "Software Version" }}</span>
              <span>{{ updateSoftwareLabel }}</span>
            </div>
          </div>
          <div class="system-row">
            <div class="storage-legend">
              <span>IP Address</span>
              <span>{{ networkUrlLabel }}</span>
            </div>
            <div v-if="connectedWifiSsid" class="storage-legend">
              <span>Network</span>
              <span>{{ connectedWifiSsid }}</span>
            </div>
            <p v-if="wifiMessage" class="hero-subtitle system-notification">{{ wifiMessage }}</p>
            <p v-if="wifiError" class="hero-subtitle update-error system-notification">{{ wifiError }}</p>
            <p v-if="updateError" class="hero-subtitle update-error system-notification">{{ updateError }}</p>
            <div v-if="!wifiSwitchPending" class="actions two">
              <button
                class="gloss-pill"
                :class="{ 'gloss-green': wifiSetupOpen }"
                :disabled="wifiSaving || (wifiSetupOpen && (!wifiSsid || wifiPassword.length < 8))"
                @click="wifiSetupOpen ? configureWifi() : isAccessPointNetwork ? openWifiSetup() : useAccessPointWifi()"
              >
                <span>{{ wifiSaving ? "Saving…" : wifiSetupOpen ? "Join" : isAccessPointNetwork ? "Network" : "AP mode" }}</span>
              </button>
              <button
                v-if="wifiSetupOpen"
                class="gloss-pill"
                :disabled="wifiSaving"
                @click="wifiSetupOpen = false"
              >
                <span>Back</span>
              </button>
              <button v-else class="gloss-pill gloss-green" :disabled="updateNeedsWifi || updateChecking || updateApplying || !updateAvailable" @click="loadUpdateStatus(true, true)">
                <span>{{ updateChecking ? "Fetching" : "Update" }}</span>
              </button>
            </div>
            <div v-if="wifiSetupOpen" class="network-fields">
              <label class="field-row">
                <select v-model="wifiSsid" class="text-input filename-label" aria-label="Wi-Fi SSID">
                  <option disabled value="">{{ wifiScanning ? "Scanning…" : "SSID" }}</option>
                  <option v-for="ssid in wifiNetworks" :key="ssid" :value="ssid">{{ ssid }}</option>
                </select>
              </label>
              <label class="field-row">
                <input v-model="wifiPassword" class="text-input filename-label" type="password" autocomplete="current-password" placeholder="Password min. 8 characters" aria-label="Wi-Fi password" />
              </label>
            </div>
          </div>
        </div>
      </template>
    </article>
    <article class="card full-span">
      <div class="card-top" @click="toggleCard('transfer')">
        <span class="card-title">Transfer</span>
      </div>
      <template v-if="cardOpen('transfer')">
        <h2>
          {{
            isMounting
              ? "Mounting…"
              : mode === "usb_transfer"
                ? "Exposed"
                : "Inactive"
          }}
        </h2>
        <p class="hero-subtitle" v-if="mode === 'usb_transfer'">
          Eject EQUIP1 on your computer, then stop USB disk mode.
        </p>
        <p class="hero-subtitle" v-else>
          Watch at
          <a class="stream-link" :href="streamUrl">{{ streamUrlLabel }}</a
          >, or mount to present the captures partition as a USB disk.
        </p>
        <div class="actions single">
          <button
            v-if="mode !== 'usb_transfer'"
            class="gloss-pill"
            :disabled="mode === 'recording' || isMounting"
            @click="runCommand('usb-storage-start')"
          >
            <span>Mount</span>
          </button>
          <button
            v-else
            class="gloss-pill gloss-green"
            @click="runCommand('usb-storage-stop')"
          >
            <span>Unmount</span>
          </button>
        </div>
      </template>
    </article>
    <div class="rec-dock" :class="{ hidden: recDockHidden }" aria-label="Recording controls">
      <button
        v-if="mode !== 'recording'"
        class="rec-button"
        :disabled="mode !== 'idle'"
        @click="runCommand('start-recording')"
        aria-label="Start recording"
      >
        <span class="rec-button-label"></span>
      </button>
      <button
        v-else
        class="rec-button recording"
        @click="runCommand('stop-recording')"
        aria-label="Stop recording"
      >
        <span class="rec-button-label"></span>
      </button>
    </div>
  </section>
</template>
