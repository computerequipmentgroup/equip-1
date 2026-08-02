<script setup lang="ts">
const { state, connected, error, refresh, connectEvents, mock } = useEquip1State()
const config = useRuntimeConfig()

const mode = computed(() => state.value?.mode || 'offline')
const cameraName = computed(() => state.value?.camera?.name || 'DV/HDV camera')
const previewing = ref(false)
const previewLoaded = ref(false)
const previewError = ref<string | null>(null)
const previewNonce = ref(0)
const previewRetryTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const previewAllowed = computed(() => connected.value && ['idle', 'recording'].includes(mode.value))
const mockPreviewSrc = computed(
  () =>
    `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 540"><defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#050505"/><stop offset="1" stop-color="#3322aa"/></linearGradient></defs><rect width="720" height="540" fill="url(#g)"/><g opacity=".16" stroke="#fff">${Array.from({ length: 18 }, (_, i) => `<path d="M0 ${i * 32}H720"/>`).join('')}${Array.from({ length: 23 }, (_, i) => `<path d="M${i * 32} 0V540"/>`).join('')}</g><circle cx="510" cy="194" r="92" fill="#fff" opacity=".12"/><rect x="70" y="354" width="410" height="76" fill="#000" opacity=".55"/><text x="92" y="402" fill="#fff" font-family="monospace" font-size="38">MOCK LIVE DV</text><text x="94" y="450" fill="#fff" opacity=".68" font-family="monospace" font-size="22">${cameraName.value} / ${previewNonce.value}</text></svg>`)}`
)
const previewSrc = computed(() =>
  mock.value ? mockPreviewSrc.value : `${config.public.apiBase}/preview.mjpg?t=${previewNonce.value}`
)

const previewStatus = computed(() => {
  if (previewing.value && previewLoaded.value) return 'LIVE'
  if (previewing.value) return 'CONNECTING'
  if (mode.value === 'recording') return 'RECORDING'
  if (mode.value === 'usb_transfer') return 'USB MODE'
  if (mode.value === 'mounting') return 'MOUNTING'
  if (mode.value === 'no_camera') return 'NO CAMERA'
  if (!connected.value) return 'OFFLINE'
  return 'WAITING'
})

const placeholderStatus = computed(() => {
  if (error.value) return error.value
  if (!connected.value) return 'Waiting for equip1d…'
  if (previewError.value) return 'Preview unavailable; retrying…'
  if (mode.value === 'recording') return 'Buffering capture stream…'
  if (mode.value === 'idle') return 'Acquiring DV signal…'
  if (mode.value === 'usb_transfer') return 'USB disk mode is active'
  if (mode.value === 'mounting') return 'Mounting storage…'
  if (mode.value === 'no_camera') return 'No DV/HDV camera detected'
  return 'Camera offline'
})

const stopPreview = () => {
  previewing.value = false
  previewLoaded.value = false
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

const restartPreview = async () => {
  stopPreview()
  await nextTick()
  startPreview()
}

const handlePreviewLoad = () => {
  previewLoaded.value = true
}

const handlePreviewError = () => {
  previewError.value = 'Preview unavailable'
  stopPreview()
  if (previewAllowed.value && !previewRetryTimer.value) {
    previewRetryTimer.value = setTimeout(() => {
      previewRetryTimer.value = null
      startPreview()
    }, 1000)
  }
}

watch(previewAllowed, (allowed) => {
  if (!allowed) {
    stopPreview()
    return
  }
  startPreview()
})

watch(mode, async (next, previous) => {
  if (next === previous || !previewAllowed.value) return
  await restartPreview()
})

onBeforeUnmount(() => {
  stopPreview()
  if (previewRetryTimer.value) clearTimeout(previewRetryTimer.value)
})

onMounted(async () => {
  await refresh()
  connectEvents()
  if (previewAllowed.value) startPreview()
})
</script>

<template>
  <main class="hdmi-preview-page">
    <section class="hdmi-preview-stage" :class="{ active: previewing, loaded: previewLoaded }">
      <div class="hdmi-preview-placeholder">
        <strong>{{ previewStatus }}</strong>
        <span>{{ placeholderStatus }}</span>
        <small>Equip-1 HDMI preview</small>
      </div>
      <img
        v-if="previewing"
        :src="previewSrc"
        alt="Live DV/HDV preview"
        :class="{ loaded: previewLoaded }"
        @load="handlePreviewLoad"
        @error="handlePreviewError"
      />
    </section>
  </main>
</template>
