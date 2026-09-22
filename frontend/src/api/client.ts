/** fetch() wrapper for the panel API: JSON in / JSON out, {error} bodies become exceptions, 401 logs the UI out. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

let unauthorized: () => void = () => {}
export function onUnauthorized(fn: () => void) { unauthorized = fn }

export async function api<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (r.status === 401) { unauthorized(); throw new ApiError(401, '未登录') }
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
  if (j && typeof j === 'object' && 'error' in j) throw new ApiError(r.status, String((j as { error: unknown }).error))
  return j as T
}

/** Raw file upload with progress (XMLHttpRequest: fetch has no upload progress). */
export function upload<T = unknown>(path: string, file: File, onProgress?: (percent: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest()
    x.open('POST', path)
    x.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded / e.total * 100)) }
    x.onload = () => {
      if (x.status === 401) { unauthorized(); return reject(new ApiError(401, '未登录')) }
      let j: unknown
      try { j = JSON.parse(x.responseText) } catch { return reject(new ApiError(x.status, `HTTP ${x.status}`)) }
      if (j && typeof j === 'object' && 'error' in j) return reject(new ApiError(x.status, String((j as { error: unknown }).error)))
      resolve(j as T)
    }
    x.onerror = () => reject(new ApiError(0, '网络错误'))
    x.send(file)
  })
}
