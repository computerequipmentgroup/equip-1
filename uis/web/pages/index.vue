<script setup lang="ts">
const { state, connected, error, refresh, command, connectEvents } = useFirehatState()

const mode = computed(() => state.value?.mode || 'offline')
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const camera = computed(() => state.value?.camera || {})
const network = computed(() => state.value?.network || {})
const elapsed = computed(() => {
  const total = Number(recording.value.elapsed_seconds || 0)
  const hh = Math.floor(total / 3600).toString().padStart(2, '0')
  const mm = Math.floor((total % 3600) / 60).toString().padStart(2, '0')
  const ss = Math.floor(total % 60).toString().padStart(2, '0')
  return `${hh}:${mm}:${ss}`
})
const freeGb = computed(() => ((storage.value.free_bytes || 0) / 1024 / 1024 / 1024).toFixed(1))

onMounted(async () => {
  await refresh()
  connectEvents()
})
</script>

<template>
  <section class="grid">
    <article class="card">
      <div class="status">
        <span class="dot" :class="{ recording: mode === 'recording' }" />
        <span>{{ mode }}</span>
      </div>
      <div class="big">{{ elapsed }}</div>
      <p class="label">{{ recording.filename || 'No active capture' }}</p>
      <div class="actions">
        <button
          v-if="mode !== 'recording'"
          class="primary"
          :disabled="mode !== 'idle'"
          @click="command('start-recording')"
        >Start recording</button>
        <button v-else class="primary" @click="command('stop-recording')">Stop recording</button>
        <button @click="command('rescan-camera')">Rescan</button>
        <button v-if="mode === 'error'" @click="command('clear-error')">Clear error</button>
      </div>
    </article>

    <article class="card">
      <p class="label">Camera</p>
      <h2>{{ camera.connected ? camera.name || 'DV Camera' : 'No camera' }}</h2>
      <p>{{ camera.device || 'Waiting for /dev/fw1' }}</p>
    </article>

    <article class="card">
      <p class="label">Storage</p>
      <h2>{{ freeGb }} GB free</h2>
      <p>{{ storage.recording_minutes_available || 0 }} minutes available</p>
    </article>

    <article class="card">
      <p class="label">Network</p>
      <h2>{{ network.url || 'Offline' }}</h2>
      <p v-if="network.ssid">Join Wi-Fi: {{ network.ssid }}</p>
      <p v-if="network.password">Password: {{ network.password }}</p>
      <p v-else>{{ network.ip || 'No IP address' }}</p>
    </article>
  </section>

  <p v-if="!connected" class="error">Daemon connection lost.</p>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-if="state?.error" class="error">{{ state.error.message }}: {{ state.error.detail }}</p>
</template>
