type FirehatState = Record<string, any>

export const useFirehatState = () => {
  const config = useRuntimeConfig()
  const state = useState<FirehatState | null>('firehat-state', () => null)
  const connected = useState<boolean>('firehat-connected', () => false)
  const error = useState<string | null>('firehat-error', () => null)
  const ws = useState<WebSocket | null>('firehat-ws', () => null)

  const apiBase = config.public.apiBase as string
  const wsBase = config.public.wsBase as string

  const refresh = async () => {
    try {
      state.value = await $fetch<FirehatState>(`${apiBase}/state`)
      connected.value = true
      error.value = null
    } catch (err: any) {
      connected.value = false
      error.value = err?.message || 'Daemon unavailable'
    }
  }

  const command = async (name: string) => {
    state.value = await $fetch<FirehatState>(`${apiBase}/commands/${name}`, { method: 'POST' })
  }

  const connectEvents = () => {
    if (!import.meta.client || ws.value) return
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = wsBase.startsWith('ws') ? wsBase : `${protocol}//${window.location.host}${wsBase}`
    ws.value = new WebSocket(url)
    ws.value.onopen = () => { connected.value = true }
    ws.value.onmessage = (event) => {
      const payload = JSON.parse(event.data)
      if (payload.type === 'state') state.value = payload.state
    }
    ws.value.onerror = () => { error.value = 'Event stream failed' }
    ws.value.onclose = () => {
      connected.value = false
      ws.value = null
      setTimeout(connectEvents, 1500)
    }
  }

  return { state, connected, error, refresh, command, connectEvents }
}
