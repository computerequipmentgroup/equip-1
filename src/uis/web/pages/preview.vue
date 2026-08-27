<script setup lang="ts">
const { state, connected, error, refresh, connectEvents, mock } = useEquip1State()
const config = useRuntimeConfig()

const mode = computed(() => state.value?.mode || 'offline')
const previewing = ref(false)
const previewLoaded = ref(false)
const previewError = ref<string | null>(null)
const previewNonce = ref(0)
const previewAspectRatio = ref('4 / 3')
const previewImage = ref<HTMLImageElement | null>(null)
const previewRetryTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const previewDimensionInterval = ref<ReturnType<typeof setInterval> | null>(null)
const previewAllowed = computed(() => connected.value && ['idle', 'recording'].includes(mode.value))
const previewSrc = computed(
  () => `${config.public.apiBase}/preview.mjpg?t=${previewNonce.value}`
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

const updatePreviewAspectRatio = (img = previewImage.value) => {
  if (!img || img.naturalWidth <= 0 || img.naturalHeight <= 0) return
  const next = `${img.naturalWidth} / ${img.naturalHeight}`
  if (previewAspectRatio.value !== next) previewAspectRatio.value = next
}

const handlePreviewLoad = (event: Event) => {
  updatePreviewAspectRatio(event.target as HTMLImageElement)
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
  if (previewDimensionInterval.value) clearInterval(previewDimensionInterval.value)
})

onMounted(async () => {
  await refresh()
  connectEvents()
  previewDimensionInterval.value = setInterval(() => updatePreviewAspectRatio(), 250)
  if (previewAllowed.value) startPreview()
})
</script>

<template>
  <main class="hdmi-preview-page">
    <section
      class="hdmi-preview-stage"
      :class="{ active: previewing, loaded: previewLoaded }"
      :style="{ '--preview-aspect': previewAspectRatio }"
    >
      <div class="hdmi-preview-placeholder">
        <strong>{{ previewStatus }}</strong>
        <span>{{ placeholderStatus }}</span>
        <small>Equip-1 HDMI preview</small>
      </div>
      <img
        v-if="previewing && !mock"
        ref="previewImage"
        :src="previewSrc"
        alt="Live DV/HDV preview"
        :class="{ loaded: previewLoaded }"
        @load="handlePreviewLoad"
        @error="handlePreviewError"
      />
    </section>
  </main>
</template>
