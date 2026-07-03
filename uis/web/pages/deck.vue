<script setup lang="ts">
const { state, connected, error, refresh, command, connectEvents } = useFirehatState()
const actionError = ref<string | null>(null)

const mode = computed(() => state.value?.mode || 'offline')
const camera = computed(() => state.value?.camera || {})
const deck = computed(() => state.value?.deck || {})
const recording = computed(() => state.value?.recording || {})
const storage = computed(() => state.value?.storage || {})
const canControlDeck = computed(() => Boolean(camera.value.connected) && mode.value !== 'offline')
const elapsed = computed(() => {
  const total = Number(recording.value.elapsed_seconds || 0)
  const hh = Math.floor(total / 3600).toString().padStart(2, '0')
  const mm = Math.floor((total % 3600) / 60).toString().padStart(2, '0')
  const ss = Math.floor(total % 60).toString().padStart(2, '0')
  return `${hh}:${mm}:${ss}`
})

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
    <article class="card deck-hero">
      <p class="label">Deck</p>
      <h1>{{ deck.status || 'Unknown' }}</h1>
      <p>{{ camera.connected ? camera.name || 'DV Camera' : 'No DV camera detected' }}</p>
      <p v-if="deck.timecode" class="timecode">{{ deck.timecode }}</p>
      <p v-if="deck.error" class="error">{{ deck.error }}</p>
    </article>

    <article class="card">
      <p class="label">Transport</p>
      <div class="deck-controls">
        <button :disabled="!canControlDeck" @click="runCommand('deck-rewind')">Rewind</button>
        <button class="primary" :disabled="!canControlDeck" @click="runCommand('deck-play')">Play</button>
        <button :disabled="!canControlDeck" @click="runCommand('deck-stop')">Stop</button>
        <button :disabled="!canControlDeck" @click="runCommand('deck-fast-forward')">Fast forward</button>
      </div>
    </article>

    <article class="card">
      <p class="label">Capture</p>
      <h2>{{ mode }}</h2>
      <p>{{ recording.filename || 'No active capture' }}</p>
      <div v-if="recording.active" class="big small">{{ elapsed }}</div>
      <p>{{ storage.recording_minutes_available || 0 }} minutes available</p>
      <div class="actions">
        <button
          v-if="!recording.active"
          class="primary"
          :disabled="mode !== 'idle'"
          @click="runCommand('start-recording')"
        >Start capture</button>
        <button v-else class="primary" @click="runCommand('stop-recording')">Stop capture</button>
      </div>
    </article>

    <article class="card">
      <p class="label">Guided ingest</p>
      <h2>Manual MVP</h2>
      <p>Use Rewind, Play, then Start capture. Full “rewind + capture tape” automation can build on this deck control API.</p>
    </article>
  </section>

  <p v-if="!connected" class="error">Daemon connection lost.</p>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-if="actionError" class="error">{{ actionError }}</p>
  <p v-if="state?.error" class="error">{{ state.error.message }}: {{ state.error.detail }}</p>
</template>
