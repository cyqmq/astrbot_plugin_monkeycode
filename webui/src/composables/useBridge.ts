/**
 * AstrBot Plugin Page Bridge API 封装。
 * 生产环境使用 window.AstrBotPluginPage；开发模式回退到本地代理请求。
 */
interface BridgeContext {
  pluginName: string
  displayName: string
  pageName: string
  pageTitle: string
  locale: string
  i18n: Record<string, unknown>
}

interface Bridge {
  ready(): Promise<BridgeContext>
  getContext(): BridgeContext | null
  getLocale(): string
  t(key: string, fallback?: string): string
  apiGet(endpoint: string, params?: Record<string, unknown>): Promise<unknown>
  apiPost(endpoint: string, body?: unknown): Promise<unknown>
  upload(endpoint: string, file: File): Promise<unknown>
  download(endpoint: string, params?: Record<string, unknown>, filename?: string): Promise<unknown>
}

declare global {
  interface Window {
    AstrBotPluginPage?: Bridge
    AstrBotPluginView?: Bridge
  }
}

const PLUGIN_NAME = 'astrbot_plugin_monkeycode'

let bridgeReady = false
let bridgeContext: BridgeContext | null = null

function getBridge(): Bridge | null {
  if (typeof window !== 'undefined') {
    return window.AstrBotPluginPage || window.AstrBotPluginView || null
  }
  return null
}

function plain<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T)
}

export function useBridge() {
  const bridge = getBridge()

  async function init(): Promise<BridgeContext | null> {
    if (bridgeReady && bridgeContext) return bridgeContext
    if (!bridge) {
      console.warn('[Bridge] AstrBotPluginPage 不可用，可能在独立开发模式下运行')
      return null
    }
    try {
      bridgeContext = await bridge.ready()
      bridgeReady = true
      return bridgeContext
    } catch (e) {
      console.error('[Bridge] 初始化失败:', e)
      return null
    }
  }

  async function apiGet<T = unknown>(
    endpoint: string,
    params?: Record<string, unknown>,
  ): Promise<T> {
    if (bridge) {
      return (await bridge.apiGet(endpoint, plain(params))) as T
    }
    const url = new URL(
      `/api/plug/${PLUGIN_NAME}/${endpoint}`,
      window.location.origin,
    )
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
      })
    }
    const resp = await fetch(url.toString())
    return resp.json()
  }

  async function apiPost<T = unknown>(
    endpoint: string,
    body?: unknown,
  ): Promise<T> {
    if (bridge) {
      return (await bridge.apiPost(endpoint, plain(body))) as T
    }
    const url = `/api/plug/${PLUGIN_NAME}/${endpoint}`
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return resp.json()
  }

  return { init, apiGet, apiPost }
}