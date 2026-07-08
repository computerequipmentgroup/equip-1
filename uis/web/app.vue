<script setup lang="ts">
const { state, connected, refresh, connectEvents, syncTime } = useEquip1State()

const mode = computed(() => state.value?.mode || 'offline')
const headerChipLabel = computed(() => {
  if (!connected.value) return 'Offline'
  if (mode.value === 'recording') return 'Recording'
  if (mode.value === 'usb_transfer') return 'USB mode'
  if (mode.value === 'booting') return 'Booting'
  if (mode.value === 'no_camera') return 'No cam'
  if (mode.value === 'storage_full') return 'Storage full'
  if (mode.value === 'error') return 'Error'
  return 'Ready'
})
const headerChipClass = computed(() => ({
  offline: !connected.value,
  recording: connected.value && mode.value === 'recording',
  usb: connected.value && mode.value === 'usb_transfer',
  warning: connected.value && ['booting', 'no_camera', 'storage_full'].includes(mode.value),
  error: connected.value && mode.value === 'error',
  ready: connected.value && mode.value === 'idle'
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
