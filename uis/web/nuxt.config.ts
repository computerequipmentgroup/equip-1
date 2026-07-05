export default defineNuxtConfig({
  devtools: { enabled: false },
  ssr: false,
  app: {
    head: {
      title: 'Equip-1 ◯ DV RECORDER',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'theme-color', content: '#000000' },
        { name: 'application-name', content: 'Equip-1' },
        { name: 'mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' },
        { name: 'apple-mobile-web-app-title', content: 'Equip-1' },
        { name: 'format-detection', content: 'telephone=no' }
      ],
      link: [
        { rel: 'manifest', href: '/manifest.webmanifest' },
        { rel: 'icon', type: 'image/png', href: '/favicon.png' },
        { rel: 'apple-touch-icon', href: '/favicon.png' }
      ]
    }
  },
  runtimeConfig: {
    public: {
      apiBase: '/api',
      wsBase: '/api/events',
      firehatMock: ''
    }
  },
  css: ['~/assets/main.css']
})
