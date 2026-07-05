<script setup lang="ts">
const { state, connected, error, refresh, command, connectEvents, mock } = useFirehatState()
const { captures, error: capturesError, load, downloadUrl } = useFirehatCaptures()
const { system, error: systemError, load: loadSystem } = useFirehatSystem()
const config = useRuntimeConfig()

// Only surface captures whose thumbnail has finished rendering, so a new
// recording appears in the list complete rather than as a blank placeholder.
const readyCaptures = computed(() => captures.value.filter((capture) => capture.thumbnail_url))

const mode = computed(() => state.value?.mode || 'offline')
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const actionError = ref<string | null>(null)
const systemInterval = ref<ReturnType<typeof setInterval> | null>(null)

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
      <div class="hero-top">
        <span class="card-title">Record</span>
      </div>
      <div class="timecode-fit big" :class="{ dimmed: recordDimmed }" aria-label="Elapsed recording time">
        <span>{{ elapsedParts.hh }}</span
        ><b>:</b><span>{{ elapsedParts.mm }}</span
        ><b>:</b><span>{{ elapsedParts.ss }}</span>
      </div>
    </article>

    <article class="card">
      <div class="card-top">
        <span class="card-title">Storage</span>
        <!-- <span class="spec-chip">microSD</span> -->
      </div>
      <div class="storage-bar" aria-label="Storage usage">
        <span :style="{ width: `${storagePercent}%` }" />
      </div>
      <div class="storage-legend">
        <span>{{ usedGb }} GB used</span>
        <span>{{ freeGb }} GB free</span>
      </div>
      <p class="hero-subtitle" style="margin-top: 0.8rem">
        {{ storage.recording_minutes_available || 0 }} minutes available
      </p>
    </article>

    <article class="card full-span">
      <div class="card-top">
        <span class="card-title">System</span>
        <span class="spec-chip">{{ system?.model || 'ROCK compute' }}</span>
      </div>
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
          <div class="storage-bar" aria-label="Temperature"><span :style="{ width: `${temperaturePercent}%` }" /></div>
        </div>
      </div>
    </article>

    <article class="card full-span">
      <div class="card-top">
        <span class="card-title">Captures</span>
      </div>
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
    </article>

    <article class="card full-span">
      <div class="card-top">
        <span class="card-title">Transfer</span>
      </div>
      <h2>{{ mode === 'usb_transfer' ? 'Exposed' : 'Inactive' }}</h2>
      <p class="hero-subtitle" v-if="mode === 'usb_transfer'">
        Eject EQUIP1 on your computer, then stop USB disk mode.
      </p>
      <p class="hero-subtitle" v-else>Unmount local storage and present the captures partition as a USB disk.</p>
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
