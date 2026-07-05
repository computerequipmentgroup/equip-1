export default defineNuxtPlugin(() => {
  if (!('serviceWorker' in navigator)) return
  if (import.meta.dev) return

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // PWA support is best-effort; the dashboard must still work normally.
    })
  })
})
