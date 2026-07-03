export default defineNuxtConfig({
  ssr: false,
  app: {
    head: {
      title: 'Firehat',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' }
      ]
    }
  },
  runtimeConfig: {
    public: {
      apiBase: '/api',
      wsBase: '/api/events'
    }
  },
  css: ['~/assets/main.css']
})
