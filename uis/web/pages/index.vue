<script setup lang="ts">
const { state, connected, error, refresh, command, connectEvents } = useFirehatState()
const { captures, error: capturesError, load, downloadUrl } = useFirehatCaptures()

// Only surface captures whose thumbnail has finished rendering, so a new
// recording appears in the list complete rather than as a blank placeholder.
const readyCaptures = computed(() => captures.value.filter((capture) => capture.thumbnail_url))

const mode = computed(() => state.value?.mode || 'offline')
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const actionError = ref<string | null>(null)

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
const recordDimmed = computed(() => !['idle', 'recording'].includes(mode.value))

const sizeGb = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
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

const runCommand = async (name: string) => {
  try {
    actionError.value = null
    await command(name)
    await refresh()
  } catch (err: any) {
    actionError.value = err?.data?.detail || err?.message || `Could not run ${name}`
    await refresh()
  }
}

onMounted(async () => {
  await Promise.all([refresh(), load()])
  connectEvents()
})
</script>

<template>
  <section class="screen">
    <article class="hero-card full-span">
      <div class="hero-top">
        <span class="card-title">Record</span>
      </div>
      <div class="timecode-fit big" :class="{ dimmed: recordDimmed }" aria-label="Elapsed recording time">
        <span>{{ elapsedParts.hh }}</span
        ><b>:</b><span>{{ elapsedParts.mm }}</span
        ><b>:</b><span>{{ elapsedParts.ss }}</span>
      </div>
      <div class="actions">
        <button
          v-if="mode !== 'recording'"
          class="primary"
          :disabled="mode !== 'idle'"
          @click="runCommand('start-recording')"
        >
          Start
        </button>
        <button v-else class="danger" @click="runCommand('stop-recording')">Stop</button>
        <button @click="runCommand('rescan-camera')">Rescan</button>
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
        <span>{{ freeGb }} GB free</span>
        <span>{{ usedGb }} GB used</span>
      </div>
      <p class="hero-subtitle" style="margin-top: 0.8rem">
        {{ storage.recording_minutes_available || 0 }} minutes available
      </p>
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
            <a class="download-arrow" :href="downloadUrl(capture)" :download="capture.name" aria-label="Download capture">↓</a>
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
          :disabled="mode === 'recording'"
          @click="runCommand('usb-storage-start')"
        >
          Mount
        </button>
        <button v-else class="primary" @click="runCommand('usb-storage-stop')">Unmount</button>
      </div>
    </article>

    <p v-if="!connected" class="error full-span">Daemon connection lost.</p>
    <p v-if="error" class="error full-span">{{ error }}</p>
    <p v-if="actionError" class="error full-span">{{ actionError }}</p>
    <p v-if="state?.error" class="error full-span">{{ state.error.message }}: {{ state.error.detail }}</p>
  </section>
</template>
