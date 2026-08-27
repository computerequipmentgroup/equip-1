<script setup lang="ts">
const { state, connected, refresh, connectEvents, syncTime } = useEquip1State()

const mode = computed(() => state.value?.mode || 'offline')
const conversionActive = computed(() => Boolean(state.value?.conversion?.active))
const noCameraDetected = computed(() => {
  const cameraConnected = state.value?.camera?.connected
  return mode.value === 'no_camera' || cameraConnected === false || cameraConnected === 0 || cameraConnected === 'false'
})
const headerChipLabel = computed(() => {
  if (mode.value === 'recording') return 'Recording'
  if (noCameraDetected.value) return 'No cam'
  if (!connected.value) return 'Busy'
  if (conversionActive.value) return 'Busy'
  if (mode.value === 'idle') return 'Ready'
  return 'Busy'
})
const headerChipClass = computed(() => ({
  busy: !noCameraDetected.value && (!connected.value || (mode.value !== 'recording' && (conversionActive.value || !['idle', 'recording'].includes(mode.value)))),
  ready: connected.value && mode.value === 'idle' && !conversionActive.value && !noCameraDetected.value,
  recording: connected.value && mode.value === 'recording',
  'no-camera': noCameraDetected.value && mode.value !== 'recording'
}))

const reloadPage = () => {
  if (import.meta.client) window.location.reload()
}

onMounted(async () => {
  await syncTime()
  await refresh()
  connectEvents()
})
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <a href="/" class="brand-mark" aria-label="Equip-1 dashboard" @click.prevent="reloadPage">
        <span>equip-1</span>
      </a>
      <div class="header-chip" :class="headerChipClass">
        <span class="chip-dot" />
        {{ headerChipLabel }}
      </div>
    </header>

    <main class="page">
      <NuxtPage />
    </main>
  </div>
</template>
