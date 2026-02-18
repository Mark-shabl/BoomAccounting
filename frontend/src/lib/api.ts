const envUrl = (import.meta as any).env?.VITE_API_BASE_URL
export const API_BASE_URL =
  envUrl && String(envUrl).trim()
    ? String(envUrl).trim()
    : import.meta.env.DEV
      ? '/api'
      : 'http://localhost:8000'

export type ApiError = {
  status: number
  message: string
}

async function readErrorMessage(res: Response): Promise<string> {
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('application/json')) {
    try {
      const data = (await res.json()) as any
      return data?.detail ? String(data.detail) : JSON.stringify(data)
    } catch {
      return `${res.status} ${res.statusText}`
    }
  }
  try {
    return await res.text()
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

export async function apiRequest<T>(
  path: string,
  opts: RequestInit & { token?: string } = {}
): Promise<T> {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  const headers = new Headers(opts.headers)
  if (!headers.has('content-type') && opts.body) headers.set('content-type', 'application/json')
  if (opts.token) headers.set('authorization', `Bearer ${opts.token}`)

  const res = await fetch(url, { ...opts, headers })
  if (!res.ok) {
    const message = await readErrorMessage(res)
    const err: ApiError = { status: res.status, message }
    throw err
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('application/json')) return (await res.json()) as T
  return (await res.text()) as any as T
}

