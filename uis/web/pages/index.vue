<script setup lang="ts">
const { state, connected, error, refresh, command, connectEvents } = useFirehatState()

const mode = computed(() => state.value?.mode || 'offline')
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const camera = computed(() => state.value?.camera || {})
const network = computed(() => state.value?.network || {})
const actionError = ref<string | null>(null)
const elapsed = computed(() => {
  const total = Number(recording.value.elapsed_seconds || 0)
  const hh = Math.floor(total / 3600).toString().padStart(2, '0')
  const mm = Math.floor((total % 3600) / 60).toString().padStart(2, '0')
  const ss = Math.floor(total % 60).toString().padStart(2, '0')
  return `${hh}:${mm}:${ss}`
})
const freeGb = computed(() => ((storage.value.free_bytes || 0) / 1024 / 1024 / 1024).toFixed(1))

const runCommand = async (name: string) => {
  try {
    actionError.value = null
    await command(name)
  } catch (err: any) {
    actionError.value = err?.data?.detail || err?.message || `Could not run ${name}`
    await refresh()
  }
}

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
          @click="runCommand('start-recording')"
        >Start recording</button>
        <button v-else class="primary" @click="runCommand('stop-recording')">Stop recording</button>
        <button @click="runCommand('rescan-camera')">Rescan</button>
        <button v-if="mode === 'error'" @click="runCommand('clear-error')">Clear error</button>
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

    <article class="card">
      <p class="label">USB-C transfer</p>
      <h2>{{ mode === 'usb_transfer' ? 'USB disk active' : 'Native file copy' }}</h2>
      <p v-if="mode === 'usb_transfer'">Eject EQUIP1 on your computer, then stop USB disk mode.</p>
      <p v-else>Expose the EQUIP1 captures partition as a USB Mass Storage disk.</p>
      <div class="actions">
        <button v-if="mode !== 'usb_transfer'" :disabled="mode === 'recording'" @click="runCommand('usb-storage-start')">Start USB disk</button>
        <button v-else class="primary" @click="runCommand('usb-storage-stop')">Stop USB disk</button>
      </div>
    </article>
  </section>

  <p v-if="!connected" class="error">Daemon connection lost.</p>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-if="actionError" class="error">{{ actionError }}</p>
  <p v-if="state?.error" class="error">{{ state.error.message }}: {{ state.error.detail }}</p>
</template>
