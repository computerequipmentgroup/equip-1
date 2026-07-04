<script setup lang="ts">
const config = useRuntimeConfig()
const captures = ref<any[]>([])
const error = ref<string | null>(null)

const load = async () => {
  try {
    captures.value = await $fetch<any[]>(`${config.public.apiBase}/captures`)
    error.value = null
  } catch (err: any) {
    error.value = err?.message || 'Could not load captures'
  }
}

const sizeGb = (bytes: number) => `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
const modified = (seconds: number) => new Date(seconds * 1000).toLocaleString()
const downloadUrl = (capture: any) => `${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}/download`

onMounted(load)
</script>

<template>
  <section class="card">
    <div class="nav">
      <h1>Captures</h1>
      <button @click="load">Refresh</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <div v-if="captures.length" class="list">
      <div v-for="capture in captures" :key="capture.path" class="row">
        <div>
          <strong>{{ capture.name }}</strong>
          <div class="label">{{ modified(capture.modified_at) }}</div>
        </div>
        <div class="actions">
          <span>{{ sizeGb(capture.size_bytes) }}</span>
          <a class="button" :href="downloadUrl(capture)" :download="capture.name">Download</a>
        </div>
      </div>
    </div>
    <p v-else>No captures yet.</p>
  </section>
</template>
