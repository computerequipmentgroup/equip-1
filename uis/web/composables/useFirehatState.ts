type FirehatState = Record<string, any>
type CaptureEntry = Record<string, any>

export const useFirehatState = () => {
  const config = useRuntimeConfig()
  const state = useState<FirehatState | null>('firehat-state', () => null)
  const connected = useState<boolean>('firehat-connected', () => false)
  const error = useState<string | null>('firehat-error', () => null)
  const ws = useState<WebSocket | null>('firehat-ws', () => null)
  const captures = useState<CaptureEntry[]>('firehat-captures', () => [])

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

  // The device has no clock; hand it the browser's time so captures are stamped
  // with a real date. Best-effort — the daemon only applies it when its own
  // clock is still unset.
  const syncTime = async () => {
    if (!import.meta.client) return
    try {
      await $fetch(`${apiBase}/time`, { method: 'POST', body: { now: Date.now() / 1000 } })
    } catch {
      /* non-fatal */
    }
  }

  const connectEvents = () => {
    if (!import.meta.client) return
    if (ws.value) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = wsBase.startsWith('ws') ? wsBase : `${protocol}//${window.location.host}${wsBase}`
    ws.value = new WebSocket(url)
    ws.value.onopen = () => { connected.value = true }
    ws.value.onmessage = (event) => {
      const payload = JSON.parse(event.data)
      if (payload.type === 'state') state.value = payload.state
      else if (payload.type === 'captures') captures.value = payload.captures
    }
    ws.value.onerror = () => { error.value = 'Event stream failed' }
    ws.value.onclose = () => {
      connected.value = false
      ws.value = null
      setTimeout(connectEvents, 1500)
    }
  }

  return { state, connected, error, refresh, command, connectEvents, syncTime }
}

export const useFirehatCaptures = () => {
  const config = useRuntimeConfig()
  const captures = useState<CaptureEntry[]>('firehat-captures', () => [])
  const error = useState<string | null>('firehat-captures-error', () => null)

  const load = async () => {
    try {
      captures.value = await $fetch<CaptureEntry[]>(`${config.public.apiBase}/captures`)
      error.value = null
    } catch (err: any) {
      error.value = err?.message || 'Could not load captures'
    }
  }

  const downloadUrl = (capture: CaptureEntry) =>
    `${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}/download`

  return { captures, error, load, downloadUrl }
}
