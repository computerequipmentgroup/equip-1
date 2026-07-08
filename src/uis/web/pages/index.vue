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
  connectEvents,
  mock
} = useEquip1State()
const { captures, error: capturesError, load, downloadUrl } = useEquip1Captures()
const { system, error: systemError, load: loadSystem } = useEquip1System()
const config = useRuntimeConfig()

// Only surface captures whose thumbnail has finished rendering, so a new
// recording appears in the list complete rather than as a blank placeholder.
const readyCaptures = computed(() => captures.value.filter((capture) => capture.thumbnail_url))

const mode = computed(() => state.value?.mode || 'offline')
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const actionError = ref<string | null>(null)
const systemInterval = ref<ReturnType<typeof setInterval> | null>(null)
const closedCards = ref<Record<string, boolean>>({})
const cardOpen = (name: string) => !closedCards.value[name]
const toggleCard = (name: string) => {
  closedCards.value = { ...closedCards.value, [name]: cardOpen(name) }
}

const elapsedParts = computed(() => {
  const total = Number(recording.value.elapsed_seconds || 0)
  return {
    hh: Math.floor(total / 3600)
      .toString()
      .padStart(2, '0'),
    mm: Math.floor((total % 3600) / 60)
      .toString()
      .padStart(2, '0'),
    ss: Math.floor(total % 60)
      .toString()
      .padStart(2, '0')
  }
})
const elapsed = computed(() => `${elapsedParts.value.hh}:${elapsedParts.value.mm}:${elapsedParts.value.ss}`)
const freeGb = computed(() => ((storage.value.free_bytes || 0) / 1024 / 1024 / 1024).toFixed(1))
const usedGb = computed(() => ((storage.value.used_bytes || 0) / 1024 / 1024 / 1024).toFixed(1))
const storagePercent = computed(() => {
  const total = Number(storage.value.total_bytes || 0)
  const used = Number(storage.value.used_bytes || 0)
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((used / total) * 100)))
})
const storageDeviceLabel = computed(() => {
  const kind = String(storage.value.device_kind || '').toLowerCase()
  if (kind === 'usb') return 'USB'
  if (kind === 'sd') return 'SD card'
  if (kind === 'nvme') return 'NVMe'
  if (kind === 'transfer') return 'USB transfer'
  if (kind === 'rootfs') return 'Rootfs'

  const device = String(storage.value.device || '')
  if (device.startsWith('/dev/sd')) return 'USB'
  if (device.startsWith('/dev/mmcblk')) return 'SD card'
  if (device.startsWith('/dev/nvme')) return 'NVMe'
  if (device === 'rootfs' || device === '/dev/root') return 'Rootfs'
  return 'Unknown'
})
const cpuPercent = computed(() => Math.max(0, Math.min(100, Math.round(Number(system.value?.cpu?.percent || 0)))))
const memoryPercent = computed(() => Math.max(0, Math.min(100, Math.round(Number(system.value?.memory?.percent || 0)))))
const temperaturePercent = computed(() =>
  Math.max(0, Math.min(100, Math.round(Number(system.value?.temperature?.percent || 0))))
)
const recordDimmed = computed(() => !['idle', 'recording'].includes(mode.value))
const previewing = ref(false)
const previewLoaded = ref(false)
const previewError = ref<string | null>(null)
const previewNonce = ref(0)
const previewRetryTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const previewAllowed = computed(() => connected.value && ['idle', 'recording'].includes(mode.value))
const mockPreviewSrc = computed(
  () =>
    `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#080808"/><stop offset="1" stop-color="#5500ff"/></linearGradient></defs><rect width="320" height="240" fill="url(#g)"/><g opacity=".2" stroke="#fff">${Array.from({ length: 12 }, (_, i) => `<path d="M0 ${i * 24}H320"/>`).join('')}${Array.from({ length: 16 }, (_, i) => `<path d="M${i * 24} 0V240"/>`).join('')}</g><circle cx="225" cy="92" r="42" fill="#fff" opacity=".16"/><rect x="32" y="154" width="196" height="34" fill="#000" opacity=".55"/><text x="42" y="176" fill="#fff" font-family="monospace" font-size="18">MOCK LIVE DV</text><text x="42" y="204" fill="#fff" opacity=".68" font-family="monospace" font-size="12">Sony DCR-TRV900 / ${previewNonce.value}</text></svg>`)}`
)
const previewSrc = computed(() =>
  mock.value ? mockPreviewSrc.value : `${config.public.apiBase}/preview.mjpg?t=${previewNonce.value}`
)
// Absolute URL so it resolves inside a separate player app, not just the
// dashboard's own origin. The daemon serves both the web UI and the stream.
const streamUrl = computed(() => {
  const base = import.meta.client ? window.location.origin : ''
  return `${base}${config.public.apiBase}/stream.mkv`
})
// Displayed without the scheme so the URL reads cleaner; the href keeps it.
const streamUrlLabel = computed(() => streamUrl.value.replace(/^https?:\/\//, ''))
const previewStatus = computed(() => {
  if (previewing.value) return 'Live'
  if (mode.value === 'recording') return 'Recording'
  if (mode.value === 'usb_transfer') return 'USB'
  if (mode.value === 'no_camera') return 'No cam'
  return 'Off'
})
// Shown on the placeholder while the MJPEG stream is not yet flowing — most
// visible during the record/stop transition, when the preview pipeline is torn
// down and re-established against the new source.
const placeholderStatus = computed(() => {
  if (!connected.value) return 'daemon offline'
  if (previewError.value) return 'preview unavailable, retrying'
  if (mode.value === 'recording') return 'buffering capture stream…'
  if (mode.value === 'idle') return 'acquiring DV signal…'
  if (mode.value === 'usb_transfer') return 'usb disk mode'
  if (mode.value === 'no_camera') return 'no DV camera detected'
  return 'camera offline'
})

const lightsLocked = ref(true)
const lightsEnabled = computed(() => state.value?.lights?.enabled !== false)
const lightColors = computed<number[][]>(() => {
  const colors = state.value?.lights?.default_colors
  if (Array.isArray(colors) && colors.length) {
    return colors.map((rgb) => (Array.isArray(rgb) ? rgb.slice(0, 3).map((v) => Number(v) || 0) : [0, 0, 255]))
  }
  return [
    [0, 0, 255],
    [0, 0, 255],
    [0, 0, 255]
  ]
})
const rgbToHex = (rgb: number[]) =>
  `#${rgb
    .map((v) =>
      Math.max(0, Math.min(255, Math.round(v)))
        .toString(16)
        .padStart(2, '0')
    )
    .join('')}`
const lightHexes = computed(() => lightColors.value.map(rgbToHex))
const lightsBrightness = computed(() => {
  const value = Number(state.value?.lights?.brightness)
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0.25
})
const lightsBrightnessPercent = computed(() => Math.round(lightsBrightness.value * 100))
const onLightInput = (index: number, event: Event) => {
  const match = /^#?([0-9a-fA-F]{6})$/.exec((event.target as HTMLInputElement).value)
  if (!match) return
  const int = parseInt(match[1], 16)
  const rgb = [(int >> 16) & 255, (int >> 8) & 255, int & 255]
  // Locked: every LED tracks the one being edited. Unlocked: only this LED.
  const next = lightColors.value.map((existing, i) => (lightsLocked.value || i === index ? rgb : existing))
  setLightColors(next)
}
const toggleLightsEnabled = () => setLightsEnabled(!lightsEnabled.value)
const onLightsBrightnessInput = (event: Event) => {
  const percent = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(percent)) return
  setLightsBrightness(percent / 100)
}

const sizeGb = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
const systemLoadLabel = computed(() => {
  const load = Number(system.value?.cpu?.load_1m || 0).toFixed(2)
  const count = Number(system.value?.cpu?.count || 0)
  return count ? `${load} / ${count} cores` : load
})
const systemMemoryLabel = computed(() => {
  const used = Number(system.value?.memory?.used_bytes || 0) / 1024 / 1024
  const total = Number(system.value?.memory?.total_bytes || 0) / 1024 / 1024
  if (!total) return 'Unknown'
  return `${Math.round(used)} / ${Math.round(total)} MB`
})
const systemTempLabel = computed(() => {
  const temp = system.value?.temperature?.celsius
  return typeof temp === 'number' ? `${temp.toFixed(1)} °C` : 'Unknown'
})
const modified = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || value === '') return 'Unknown date'
  const numeric = Number(value)
  const millis = Number.isFinite(numeric)
    ? numeric < 10_000_000_000
      ? numeric * 1000
      : numeric
    : Date.parse(String(value))
  const date = new Date(millis)
  return Number.isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleString()
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const runCommand = async (name: string) => {
  try {
    actionError.value = null
    if (name === 'start-recording' && previewing.value) {
      previewing.value = false
      await nextTick()
      await wait(250)
    }
    await command(name)
    await refresh()
  } catch (err: any) {
    actionError.value = err?.data?.detail || err?.message || `Could not run ${name}`
    await refresh()
  }
}

const startPreview = () => {
  if (!previewAllowed.value || previewing.value) return
  if (previewRetryTimer.value) {
    clearTimeout(previewRetryTimer.value)
    previewRetryTimer.value = null
  }
  previewError.value = null
  previewLoaded.value = false
  previewNonce.value = Date.now()
  previewing.value = true
}

const handlePreviewLoad = () => {
  previewLoaded.value = true
}

const handlePreviewError = () => {
  previewError.value = 'Preview unavailable'
  previewLoaded.value = false
  previewing.value = false
  if (previewAllowed.value && !previewRetryTimer.value) {
    previewRetryTimer.value = setTimeout(() => {
      previewRetryTimer.value = null
      startPreview()
    }, 1000)
  }
}

watch(previewAllowed, (allowed) => {
  if (!allowed) {
    previewing.value = false
    return
  }
  startPreview()
})

watch(mode, async (next, previous) => {
  if (next === previous || !previewAllowed.value) return
  if (previewing.value) {
    previewing.value = false
    await nextTick()
    await wait(250)
  }
  startPreview()
})

onBeforeUnmount(() => {
  previewing.value = false
  if (previewRetryTimer.value) clearTimeout(previewRetryTimer.value)
  if (systemInterval.value) clearInterval(systemInterval.value)
})

onMounted(async () => {
  await Promise.all([refresh(), load(), loadSystem()])
  connectEvents()
  systemInterval.value = setInterval(loadSystem, 3000)
  if (previewAllowed.value) startPreview()
})
</script>

<template>
  <section class="screen">
    <p v-if="!connected" class="error full-span">Daemon connection lost.</p>
    <p v-if="error" class="error full-span">{{ error }}</p>
    <p v-if="actionError" class="error full-span">{{ actionError }}</p>
    <p v-if="state?.error" class="error full-span">{{ state.error.message }}: {{ state.error.detail }}</p>

    <article class="preview-section full-span">
      <div class="live-preview" :class="{ active: previewing }">
        <div class="live-placeholder">{{ placeholderStatus }}</div>
        <img
          v-if="previewing"
          :src="previewSrc"
          alt="Live DV preview"
          :class="{ loaded: previewLoaded }"
          @load="handlePreviewLoad"
          @error="handlePreviewError"
        />
      </div>
    </article>

    <article class="hero-card full-span">
      <div class="hero-top" @click="toggleCard('record')">
        <span class="card-title">Record</span>
      </div>
      <div
        v-if="cardOpen('record')"
        class="timecode-fit big"
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
        <!-- <span class="spec-chip">microSD</span> -->
      </div>
      <template v-if="cardOpen('storage')">
        <div class="storage-bar" aria-label="Storage usage">
          <span :style="{ width: `${storagePercent}%` }" />
        </div>
        <div class="storage-legend">
          <span>{{ usedGb }} GB used</span>
          <span>{{ freeGb }} GB free</span>
        </div>
        <div class="storage-summary hero-subtitle">
          <span>{{ storage.recording_minutes_available || 0 }} minutes available</span>
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
        <div v-if="readyCaptures.length" class="list">
          <div v-for="capture in readyCaptures" :key="capture.path" class="row capture-row">
            <div class="capture-thumb">
              <img :src="capture.thumbnail_url" alt="" loading="lazy" />
            </div>
            <div class="row-main">
              <strong class="row-title">{{ capture.name }}</strong>
              <div class="row-meta">{{ modified(capture.modified_at) }}</div>
            </div>
            <div class="row-side capture-actions">
              <span class="spec-chip">{{ sizeGb(capture.size_bytes) }}</span>
              <a
                class="download-arrow"
                :href="downloadUrl(capture)"
                :download="capture.name"
                aria-label="Download capture"
                >↓</a
              >
            </div>
          </div>
        </div>
        <p v-else class="empty">No captures yet.</p>
      </template>
    </article>

    <article class="card full-span">
      <div class="card-top" @click="toggleCard('system')">
        <span class="card-title">System</span>
        <span class="spec-chip">{{ system?.model || 'ROCK compute' }}</span>
      </div>
      <template v-if="cardOpen('system')">
        <p v-if="systemError" class="error">{{ systemError }}</p>
        <div class="system-bars">
          <div class="system-row">
            <div class="storage-legend">
              <span>CPU load</span><span>{{ systemLoadLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="CPU load"><span :style="{ width: `${cpuPercent}%` }" /></div>
          </div>
          <div class="system-row">
            <div class="storage-legend">
              <span>Memory</span><span>{{ systemMemoryLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="Memory usage"><span :style="{ width: `${memoryPercent}%` }" /></div>
          </div>
          <div class="system-row">
            <div class="storage-legend">
              <span>Temperature</span><span>{{ systemTempLabel }}</span>
            </div>
            <div class="storage-bar" aria-label="Temperature">
              <span :style="{ width: `${temperaturePercent}%` }" />
            </div>
          </div>
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
              boxShadow: lightsEnabled ? `0 0 10px ${hex}, 0 0 24px ${hex}, 0 0 42px ${hex}` : 'none'
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
            :aria-label="lightsLocked ? 'Unlock LEDs to set individually' : 'Lock LEDs to one color'"
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
          <label class="light-brightness">
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
      <div class="card-top" @click="toggleCard('transfer')">
        <span class="card-title">Transfer</span>
      </div>
      <template v-if="cardOpen('transfer')">
        <h2>{{ mode === 'usb_transfer' ? 'Exposed' : 'Inactive' }}</h2>
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
            :disabled="mode === 'recording'"
            @click="runCommand('usb-storage-start')"
          >
            <span>Mount</span>
          </button>
          <button v-else class="gloss-pill gloss-green" @click="runCommand('usb-storage-stop')">
            <span>Unmount</span>
          </button>
        </div>
      </template>
    </article>

    <div class="rec-dock" aria-label="Recording controls">
      <button
        v-if="mode !== 'recording'"
        class="rec-button"
        :disabled="mode !== 'idle'"
        @click="runCommand('start-recording')"
        aria-label="Start recording"
      >
        <span class="rec-button-label"></span>
      </button>
      <button v-else class="rec-button recording" @click="runCommand('stop-recording')" aria-label="Stop recording">
        <span class="rec-button-label"></span>
      </button>
    </div>
  </section>
</template>
