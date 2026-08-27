type Equip1State = Record<string, any>
type CaptureEntry = Record<string, any>
type SystemStats = Record<string, any>

const dvBytesPerSecond = Math.floor((216 * 1024 * 1024) / 60)

const nowIso = () => new Date().toISOString()
const defaultCaptureNaming = { prefix: 'capture_', template: '{date}_{time}' }
const defaultRecordingFormat = 'mov'

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

const mockThumbnail = (_label: string, _color = '') => 'mock-thumbnail'

const normalizeRecordingFormat = (value: any) => {
  const format = String(value || defaultRecordingFormat).toLowerCase().replace(/^\./, '')
  return ['dv', 'mov', 'avi'].includes(format) ? format : defaultRecordingFormat
}

const normalizeAutoMp4Mode = (value: any, fallback = 'off') => {
  const mode = String(value || fallback).toLowerCase().replace(/-/g, '_')
  const aliases: Record<string, string> = {
    fg: 'foreground',
    front: 'foreground',
    blocking: 'foreground',
    bg: 'background',
    back: 'background',
    nonblocking: 'background',
    non_blocking: 'background',
    on: 'foreground',
    true: 'foreground',
    yes: 'foreground',
    '1': 'foreground',
    false: 'off',
    no: 'off',
    '0': 'off'
  }
  const clean = aliases[mode] || mode
  return ['off', 'foreground', 'background'].includes(clean) ? clean : 'off'
}

const formatCaptureName = (date = new Date(), naming: Record<string, any> = defaultCaptureNaming, streamFormat = 'dv', recordingFormat = defaultRecordingFormat) =>
  `${renderCaptureStem(naming, date)}.${streamFormat === 'hdv' ? 'm2t' : normalizeRecordingFormat(recordingFormat)}`

const mockCaptureRows = (): CaptureEntry[] => {
  const now = Date.now() / 1000
  const rows: CaptureEntry[] = []
  for (let i = 1; i <= 27; i += 1) {
    const stem = `capture_20260704_${String(210000 + i).padStart(6, '0')}-${String(i).padStart(3, '0')}`
    const extension = i % 7 === 0 ? 'avi' : i % 5 === 0 ? 'mov' : 'dv'
    const sizeBytes = 980_000_000 + i * 137_000_000
    rows.push({
      name: `${stem}.${extension}`,
      path: `/data/captures/${stem}.${extension}`,
      size_bytes: sizeBytes,
      modified_at: now - i * 1800,
      download_url: 'data:text/plain,mock capture',
      watch_url: 'data:video/mp4,',
      thumbnail_url: mockThumbnail(`capture ${i}`, '#5500ff')
    })
    if (i % 4 === 1) {
      rows.push({
        name: `${stem}.mp4`,
        path: `/data/captures/${stem}.mp4`,
        size_bytes: Math.max(1_000_000, Math.round(sizeBytes * 0.14)),
        modified_at: now - i * 1800 + 120,
        download_url: 'data:text/plain,mock mp4 conversion',
        watch_url: 'data:video/mp4,',
        thumbnail_url: mockThumbnail(`mp4 conversion ${i}`, '#44aa22')
      })
    }
  }
  return rows
}

const mockSystemStats = (): SystemStats => ({
  model: 'ROCK 2F',
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
    url: 'http://10.42.0.1',
    dashboard_url: 'http://10.42.0.1'
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
    auto_mp4_mode: 'background',
    mp4_quality: 'high',
    mp4_deinterlace_enabled: false,
    mp4_deinterlace_algorithm: 'off',
    mp4_deinterlace_fallback: false,
    active: false,
    progress_percent: 0,
    source: null,
    target: null,
    last_error: null
  },
  settings: {
    auto_storage_switch: true,
    hdmi_preview_enabled: true,
    oled_rotate_180: false,
    recording_format: defaultRecordingFormat
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
      filename: formatCaptureName(new Date(startedAt), current.capture_naming || defaultCaptureNaming, current.camera?.format || 'dv', current.settings?.recording_format),
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
  } else if (name === 'convert-all-mp4') {
    current.mode = 'converting'
    current.conversion = {
      ...(current.conversion || {}),
      active: true,
      progress_percent: 42,
      source: captures.value.find((capture) => !String(capture.name || '').endsWith('.mp4'))?.name || 'capture.mov',
      target: 'capture.mp4',
      last_error: null
    }
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

  const setRecordingFormat = async (format: string) => {
    const clean = normalizeRecordingFormat(format)
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, settings: { ...(state.value.settings || {}), recording_format: clean } }
      return state.value
    }
    state.value = await timedFetch<Equip1State>('settings.recording_format', `${apiBase}/settings/recording-format`, {
      method: 'POST',
      body: { format: clean }
    })
    return state.value
  }

  const setConversionSettings = async (payload: Record<string, any>) => {
    const clean: Record<string, any> = {}
    if ('auto_mp4_mode' in payload) {
      clean.auto_mp4_mode = normalizeAutoMp4Mode(payload.auto_mp4_mode)
      clean.auto_mp4_enabled = clean.auto_mp4_mode !== 'off'
    } else if ('auto_mp4_enabled' in payload) {
      clean.auto_mp4_enabled = Boolean(payload.auto_mp4_enabled)
      clean.auto_mp4_mode = clean.auto_mp4_enabled ? 'foreground' : 'off'
    }
    if ('mp4_deinterlace_enabled' in payload) clean.mp4_deinterlace_enabled = Boolean(payload.mp4_deinterlace_enabled)
    if ('mp4_quality' in payload) clean.mp4_quality = String(payload.mp4_quality || 'high')
    if (mock.value) {
      if (!state.value) state.value = mockState()
      state.value = { ...state.value, conversion: { ...(state.value.conversion || {}), ...clean } }
      return state.value
    }
    state.value = await timedFetch<Equip1State>('settings.conversion', `${apiBase}/settings/conversion`, {
      method: 'POST',
      body: clean
    })
    return state.value
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

  return { state, connected, error, refresh, command, setLightColors, setLightsEnabled, setLightsBrightness, setRecordingFormat, setConversionSettings, setOledRotate180, setCaptureNaming, connectEvents, syncTime, mock }
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

  const watchUrl = (capture: CaptureEntry) => {
    if (mock.value && capture.watch_url) return capture.watch_url
    return `${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}/watch`
  }

  const createSidecar = async (capture: CaptureEntry) => {
    if (mock.value) {
      const name = String(capture.name || '')
      const dot = name.lastIndexOf('.')
      const sidecarName = `${dot >= 0 ? name.slice(0, dot) : name}.mp4`
      if (!captures.value.some((row) => row.name === sidecarName)) {
        captures.value = [
          ...captures.value,
          {
            name: sidecarName,
            path: `/data/captures/${sidecarName}`,
            size_bytes: Math.max(1_000_000, Math.round(Number(capture.size_bytes || 0) * 0.14)),
            modified_at: Date.now() / 1000,
            download_url: 'data:text/plain,mock mp4 conversion',
            watch_url: 'data:video/mp4,',
            thumbnail_url: capture.thumbnail_url || mockThumbnail('mp4 conversion', '#44aa22')
          }
        ]
      }
      return
    }
    await $fetch(`${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}/conversion`, { method: 'POST' })
    await load()
  }

  const deleteCapture = async (capture: CaptureEntry, related = false) => {
    if (mock.value) {
      const name = String(capture.name || '')
      const dot = name.lastIndexOf('.')
      const stem = dot >= 0 ? name.slice(0, dot) : name
      captures.value = captures.value.filter((row) => {
        if (row.name === name) return false
        if (related && String(row.name || '').startsWith(`${stem}.`)) return false
        return true
      })
      return
    }
    await $fetch(`${config.public.apiBase}/captures/${encodeURIComponent(capture.name)}${related ? '?related=true' : ''}`, { method: 'DELETE' })
    await load()
  }

  return { captures, error, load, downloadUrl, watchUrl, createSidecar, deleteCapture, mock }
}
