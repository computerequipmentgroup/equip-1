type Equip1State = Record<string, any>
type CaptureEntry = Record<string, any>
type SystemStats = Record<string, any>

const dvBytesPerSecond = Math.floor((216 * 1024 * 1024) / 60)

const nowIso = () => new Date().toISOString()
const defaultCaptureNaming = { prefix: 'capture_', template: '{date}_{time}' }

const pad2 = (value: number) => value.toString().padStart(2, '0')
const filenameTagValues = (date = new Date()) => ({
  date: `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}`,
  time: `${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`,
  datetime: `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}_${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`,
  year: `${date.getFullYear()}`,
  month: pad2(date.getMonth() + 1),
  day: pad2(date.getDate()),
  hour: pad2(date.getHours()),
  minute: pad2(date.getMinutes()),
  second: pad2(date.getSeconds())
})
const sanitizeCaptureStem = (value: string) => {
  const stem = value.replace(/[\\/:*?"<>|\s]+/g, '_').replace(/_+/g, '_').replace(/^[._-]+|[._-]+$/g, '')
  return (stem || 'capture').slice(0, 120).replace(/^[._-]+|[._-]+$/g, '') || 'capture'
}
const renderCaptureStem = (naming: Record<string, any> = defaultCaptureNaming, date = new Date()) => {
  const tags = filenameTagValues(date)
  const prefix = typeof naming.prefix === 'string' ? naming.prefix : defaultCaptureNaming.prefix
  const template = typeof naming.template === 'string' ? naming.template : defaultCaptureNaming.template
  return sanitizeCaptureStem(`${prefix}${template.replace(/\{([a-zA-Z_]+)\}/g, (_, tag) => tags[String(tag).toLowerCase()] || '')}`)
}

const isMockEnabled = () => {
  const config = useRuntimeConfig()
  const setting = String(config.public.equip1Mock ?? '').toLowerCase()
  return setting === '1' || setting === 'true' || (import.meta.dev && setting !== '0' && setting !== 'false')
}

const mockThumbnail = (label: string, color = '#5500ff') =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect width="160" height="90" fill="#050505"/><rect y="54" width="160" height="36" fill="${color}" opacity=".82"/><circle cx="116" cy="34" r="22" fill="#fff" opacity=".18"/><text x="10" y="78" fill="#fff" font-family="monospace" font-size="13">${label}</text></svg>`)}`

const formatCaptureName = (date = new Date(), naming: Record<string, any> = defaultCaptureNaming, streamFormat = 'dv') =>
  `${renderCaptureStem(naming, date)}.${streamFormat === 'hdv' ? 'm2t' : 'dv'}`

const mockCaptureRows = (): CaptureEntry[] => [
  {
    name: 'capture_20260704_211642-001.dv',
    path: '/data/captures/capture_20260704_211642-001.dv',
    size_bytes: 1_640_000_000,
    modified_at: Date.now() / 1000 - 1800,
    download_url: 'data:text/plain,mock capture',
    thumbnail_url: mockThumbnail('capture 01', '#5500ff')
  },
  {
    name: 'sony_trv900_tape_03.dv',
    path: '/data/captures/sony_trv900_tape_03.dv',
    size_bytes: 4_380_000_000,
    modified_at: Date.now() / 1000 - 86_400,
    download_url: 'data:text/plain,mock capture',
    thumbnail_url: mockThumbnail('tape 03', '#2444ff')
  },
  {
    name: 'family_archive_1999.dv',
    path: '/data/captures/family_archive_1999.dv',
    size_bytes: 2_210_000_000,
    modified_at: Date.now() / 1000 - 604_800,
    download_url: 'data:text/plain,mock capture',
    thumbnail_url: mockThumbnail('1999', '#8844ff')
  }
]

const mockSystemStats = (): SystemStats => ({
  model: 'Radxa ROCK 2F / RK3528A',
  cpu: {
    load_1m: 0.74,
    count: 4,
    percent: 19
  },
  memory: {
    total_bytes: 2 * 1024 * 1024 * 1024,
    used_bytes: 820 * 1024 * 1024,
    available_bytes: 1228 * 1024 * 1024,
    percent: 40
  },
  temperature: {
    celsius: 48.6,
    percent: 57
  }
})

const mockState = (): Equip1State => ({
  mode: 'idle',
  camera: {
    connected: true,
    name: 'Sony DCR-TRV900',
    device: '/dev/fw1',
    format: 'dv'
  },
  recording: {
    active: false,
    filename: null,
    started_at: null,
    elapsed_seconds: 0,
    pid: null,
    format: 'unknown'
  },
  storage: {
    capture_dir: '/data/captures',
    total_bytes: 119 * 1024 * 1024 * 1024,
    used_bytes: 34 * 1024 * 1024 * 1024,
    free_bytes: 85 * 1024 * 1024 * 1024,
    recording_minutes_available: 393,
    device: '/dev/sda2',
    device_kind: 'usb',
    mount_point: '/data',
    filesystem_type: 'exfat'
  },
  network: {
    mode: 'ap',
    ssid: 'Equip-1',
    ip: '10.42.0.1',
    dashboard_url: 'http://10.42.0.1:8000'
  },
  deck: {
    available: true,
    status: 'stopped',
    timecode: '00:00:00:00',
    last_command: null,
    error: null
  },
  lights: {
    default_colors: [
      [0, 0, 255],
      [0, 0, 255],
      [0, 0, 255]
    ],
    enabled: true,
    brightness: 0.25
  },
  capture_naming: { ...defaultCaptureNaming },
  conversion: {
    auto_mp4_enabled: true,
    mp4_quality: 'high',
    mp4_deinterlace_enabled: true,
    active: false,
    progress_percent: 0,
    source: null,
    target: null,
    last_error: null
  },
  settings: {
    auto_storage_switch: true,
    hdmi_preview_enabled: true,
    oled_rotate_180: false
  },
  error: null
})

const tickMockState = (state: Equip1State | null) => {
  if (!state?.recording?.active || !state.recording.started_at) return state
  const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(state.recording.started_at)) / 1000))
  const baseUsed = Number(state.storage.base_used_bytes || state.storage.used_bytes || 0)
  state.recording.elapsed_seconds = elapsed
  state.storage.used_bytes = baseUsed + elapsed * dvBytesPerSecond
  state.storage.free_bytes = Math.max(0, Number(state.storage.total_bytes || 0) - state.storage.used_bytes)
  state.storage.recording_minutes_available = Math.floor(state.storage.free_bytes / (216 * 1024 * 1024))
  return state
}

const finishMockRecording = (state: Equip1State, captures: Ref<CaptureEntry[]>) => {
  const elapsed = Math.max(1, Number(state.recording.elapsed_seconds || 1))
  const filename = state.recording.filename || formatCaptureName()
  captures.value = [
    {
      name: filename,
      path: `/data/captures/${filename}`,
      size_bytes: elapsed * dvBytesPerSecond,
      modified_at: Date.now() / 1000,
      download_url: 'data:text/plain,mock capture',
      thumbnail_url: mockThumbnail('new capture', '#aa22ff')
    },
    ...captures.value.filter((capture) => capture.name !== filename)
  ]
  state.recording = {
    active: false,
    filename: null,
    started_at: null,
    elapsed_seconds: 0,
    pid: null,
    format: 'unknown'
  }
  state.mode = 'idle'
  delete state.storage.base_used_bytes
}

const applyMockCommand = (state: Ref<Equip1State | null>, captures: Ref<CaptureEntry[]>, name: string) => {
  if (!state.value) state.value = mockState()
  const current = tickMockState(state.value) || mockState()
  if (!captures.value.length) captures.value = mockCaptureRows()

  if (name === 'start-recording') {
    if (current.mode !== 'idle') throw new Error('Mock recorder is not ready')
    const startedAt = nowIso()
    current.mode = 'recording'
    current.storage.base_used_bytes = current.storage.used_bytes
    current.recording = {
      active: true,
      filename: formatCaptureName(new Date(startedAt), current.capture_naming || defaultCaptureNaming, current.camera?.format || 'dv'),
      started_at: startedAt,
      elapsed_seconds: 0,
      pid: 4242,
      format: current.camera?.format || 'dv'
    }
  } else if (name === 'stop-recording') {
    if (current.recording.active) finishMockRecording(current, captures)
  } else if (name === 'rescan-camera') {
    current.camera.connected = true
    current.camera.name = 'Sony DCR-TRV900'
    current.camera.device = '/dev/fw1'
    current.camera.format = current.camera.format || 'dv'
    if (current.mode === 'no_camera') current.mode = 'idle'
  } else if (name === 'usb-storage-start') {
    current.mode = 'usb_transfer'
  } else if (name === 'usb-storage-stop') {
    current.mode = 'idle'
  } else if (name === 'storage-switch-usb') {
    current.mode = 'idle'
    current.storage.device = '/dev/sda1'
    current.storage.device_kind = 'usb'
  } else if (name === 'storage-switch-sd') {
    current.mode = 'idle'
    current.storage.device = '/dev/mmcblk0p2'
    current.storage.device_kind = 'sd'
  } else if (name === 'clear-error') {
    current.error = null
    current.mode = 'idle'
  }

  state.value = { ...current }
}

export const useEquip1State = () => {
  const config = useRuntimeConfig()
  const state = useState<Equip1State | null>('equip1-state', () => null)
  const connected = useState<boolean>('equip1-connected', () => false)
  const error = useState<string | null>('equip1-error', () => null)
  const ws = useState<WebSocket | null>('equip1-ws', () => null)
  const captures = useState<CaptureEntry[]>('equip1-captures', () => [])
  const mockInterval = useState<ReturnType<typeof setInterval> | null>('equip1-mock-interval', () => null)
  const resyncInterval = useState<ReturnType<typeof setInterval> | null>('equip1-resync-interval', () => null)
  const capturesResyncInterval = useState<ReturnType<typeof setInterval> | null>('equip1-captures-resync-interval', () => null)

  const apiBase = config.public.apiBase as string
  const wsBase = config.public.wsBase as string
  const mock = computed(() => isMockEnabled())
  const perfOn = () => import.meta.client && ['1', 'true', 'yes', 'on'].includes(String(config.public.equip1Perf ?? '').toLowerCase())
  const timedFetch = async <T>(label: string, url: string, options?: any): Promise<T> => {
    const started = import.meta.client ? performance.now() : 0
    try {
      return await $fetch<T>(url, options)
    } finally {
      if (perfOn()) console.info(`[PERF] web.${label} ${(performance.now() - started).toFixed(1)}ms`)
    }
  }

  const refresh = async () => {
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...(tickMockState(state.value) || mockState()) }
      connected.value = true
      error.value = null
      return
    }

    try {
      state.value = await timedFetch<Equip1State>('state', `${apiBase}/state`)
      connected.value = true
      error.value = null
    } catch (err: any) {
      connected.value = false
      error.value = err?.message || 'Daemon unavailable'
    }
  }

  const resyncState = async () => {
    if (mock.value) return
    try {
      state.value = await timedFetch<Equip1State>('resync_state', `${apiBase}/state`)
      connected.value = true
    } catch {
      /* websocket/reconnect path owns visible connection errors */
    }
  }

  const resyncCaptures = async () => {
    if (mock.value) return
    try {
      captures.value = await timedFetch<CaptureEntry[]>('resync_captures', `${apiBase}/captures`)
    } catch {
      /* websocket/reconnect path owns visible connection errors */
    }
  }

  const resync = async () => {
    await Promise.all([resyncState(), resyncCaptures()])
  }

  const startResync = () => {
    if (!import.meta.client || mock.value) return
    if (!resyncInterval.value) resyncInterval.value = setInterval(resyncState, 3000)
    if (!capturesResyncInterval.value) capturesResyncInterval.value = setInterval(resyncCaptures, 10000)
  }

  const command = async (name: string) => {
    if (mock.value) {
      applyMockCommand(state, captures, name)
      connected.value = true
      error.value = null
      return
    }
    state.value = await timedFetch<Equip1State>(`command.${name}`, `${apiBase}/commands/${name}`, { method: 'POST' })
  }

  // Push the per-LED standard colors to the daemon over the live websocket so
  // the OLED/LED strip updates as the user drags a picker. In mock mode there
  // is no socket, so just reflect the change into local state.
  const setLightColors = (colors: number[][]) => {
    const clean = colors.map((rgb) =>
      rgb.slice(0, 3).map((value) => Math.max(0, Math.min(255, Math.round(value))))
    )
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, lights: { ...(state.value.lights || {}), default_colors: clean } }
      return
    }
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'set-light-color', colors: clean }))
    }
  }

  const setLightsEnabled = (enabled: boolean) => {
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, lights: { ...(state.value.lights || {}), enabled } }
      return
    }
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'set-lights-enabled', enabled }))
    }
  }

  const setLightsBrightness = (brightness: number) => {
    const clean = Math.max(0, Math.min(1, Number.isFinite(brightness) ? brightness : 0.25))
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, lights: { ...(state.value.lights || {}), brightness: clean } }
      return
    }
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'set-lights-brightness', brightness: clean }))
    }
  }

  const setOledRotate180 = async (rotate_180: boolean) => {
    const enabled = Boolean(rotate_180)
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, settings: { ...(state.value.settings || {}), oled_rotate_180: enabled } }
      return state.value
    }
    state.value = await timedFetch<Equip1State>('settings.oled_rotation', `${apiBase}/settings/oled-rotation`, {
      method: 'POST',
      body: { rotate_180: enabled }
    })
    return state.value
  }

  const setCaptureNaming = async (prefix: string, template: string) => {
    const clean = {
      prefix: String(prefix ?? defaultCaptureNaming.prefix).slice(0, 48),
      template: String(template || defaultCaptureNaming.template).slice(0, 96)
    }
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, capture_naming: clean }
      return state.value
    }
    state.value = await timedFetch<Equip1State>('settings.capture_naming', `${apiBase}/settings/capture-naming`, {
      method: 'POST',
      body: clean
    })
    return state.value
  }

  // The device has no clock; hand it the browser's time so captures are stamped
  // with a real date. Best-effort — the daemon only applies it when its own
  // clock is still unset.
  const syncTime = async () => {
    if (!import.meta.client || mock.value) return
    try {
      await timedFetch('time', `${apiBase}/time`, { method: 'POST', body: { now: Date.now() / 1000 } })
    } catch {
      /* non-fatal */
    }
  }

  const connectEvents = () => {
    if (!import.meta.client) return

    if (mock.value) {
      connected.value = true
      if (mockInterval.value) return
      mockInterval.value = setInterval(refresh, 1000)
      return
    }

    if (ws.value) {
      startResync()
      return
    }
    startResync()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = wsBase.startsWith('ws') ? wsBase : `${protocol}//${window.location.host}${wsBase}`
    ws.value = new WebSocket(url)
    const wsStarted = performance.now()
    ws.value.onopen = () => {
      connected.value = true
      if (perfOn()) console.info(`[PERF] web.ws_open ${(performance.now() - wsStarted).toFixed(1)}ms`)
      resync()
    }
    ws.value.onmessage = (event) => {
      const started = performance.now()
      const payload = JSON.parse(event.data)
      if (payload.type === 'state') state.value = payload.state
      else if (payload.type === 'captures') captures.value = payload.captures
      if (perfOn()) console.info(`[PERF] web.ws_message.${payload.type || 'unknown'} ${(performance.now() - started).toFixed(1)}ms bytes=${event.data.length}`)
    }
    ws.value.onerror = () => { error.value = 'Event stream failed' }
    ws.value.onclose = () => {
      connected.value = false
      ws.value = null
      setTimeout(connectEvents, 1500)
    }
  }

  return { state, connected, error, refresh, command, setLightColors, setLightsEnabled, setLightsBrightness, setOledRotate180, setCaptureNaming, connectEvents, syncTime, mock }
}

export const useEquip1System = () => {
  const config = useRuntimeConfig()
  const system = useState<SystemStats | null>('equip1-system', () => null)
  const error = useState<string | null>('equip1-system-error', () => null)
  const mock = computed(() => isMockEnabled())

  const load = async () => {
    if (mock.value) {
      system.value = mockSystemStats()
      error.value = null
      return
    }

    try {
      const started = import.meta.client ? performance.now() : 0
      system.value = await $fetch<SystemStats>(`${config.public.apiBase}/system`)
      if (import.meta.client && ['1', 'true', 'yes', 'on'].includes(String(config.public.equip1Perf ?? '').toLowerCase())) {
        console.info(`[PERF] web.system ${(performance.now() - started).toFixed(1)}ms`)
      }
      error.value = null
    } catch (err: any) {
      error.value = err?.message || 'Could not load system stats'
    }
  }

  return { system, error, load, mock }
}

export const useEquip1Captures = () => {
  const config = useRuntimeConfig()
  const captures = useState<CaptureEntry[]>('equip1-captures', () => [])
  const error = useState<string | null>('equip1-captures-error', () => null)
  const mock = computed(() => isMockEnabled())

  const load = async () => {
    if (mock.value) {
      if (!captures.value.length) captures.value = mockCaptureRows()
      error.value = null
      return
    }

    try {
      const started = import.meta.client ? performance.now() : 0
      captures.value = await $fetch<CaptureEntry[]>(`${config.public.apiBase}/captures`)
      if (import.meta.client && ['1', 'true', 'yes', 'on'].includes(String(config.public.equip1Perf ?? '').toLowerCase())) {
        console.info(`[PERF] web.captures ${(performance.now() - started).toFixed(1)}ms rows=${captures.value.length}`)
      }
      error.value = null
    } catch (err: any) {
      error.value = err?.message || 'Could not load captures'
    }
  }

  const downloadUrl = (capture: CaptureEntry) => {
    if (mock.value && capture.download_url) return capture.download_url
    return `${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}/download`
  }

  return { captures, error, load, downloadUrl, mock }
}
