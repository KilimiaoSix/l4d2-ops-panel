/** Shapes of the panel's JSON API (see panel/l4d2panel/api). */
export interface SysInfo { load?: string; mem_used_mb?: number; mem_total_mb?: number; uptime_h?: number }

export interface Features {
  lgsm: boolean; workshop: boolean; workshop_search: boolean; console_log: boolean; perf: boolean
  sourcemod: boolean; whitelist: boolean; preset: boolean; points: boolean
}

export interface Status {
  online: boolean
  name?: string; map?: string; players?: number; max?: number; bots?: number
  srcds: boolean; degraded?: boolean
  sys: SysInfo
  action: { running: string | null; last: string }
  account: { user: string; role: string } | null
  features: Features
  title: string; display_host: string
  perf: { t: string; fps: string; out_kb: number } | null
  preset: string; whitelist: boolean | null; difficulty: string; ff: number | null; burn: number | null
}

export interface Player { userid: string; name: string; steamid: string; time: string; ping: string; loss: string; state: string }

export interface Addon { name: string; size_mb: number; maps: string[]; mission: string; protected: boolean }

export interface Job {
  state: 'running' | 'done' | 'error'; msg: string
  files?: string[]; name?: string; title?: string; done?: number; total?: number; speed?: number; cancel?: boolean
  token?: string; size_mb?: number
}

export interface AddonsResponse { addons: Addon[]; jobs: Record<string, Job>; zips: Record<string, Job> }

/** /api/upload: every campaign vpk installed (from a .vpk or the vpks inside a .zip), the rest with the reason it was refused. */
export interface UploadResult { ok: true; installed: Addon[]; skipped: { name: string; reason: string }[]; out: string }

export interface WorkshopItem {
  id: string; title: string; size_mb: number; subs: number; updated: number; preview: string; tags: string[]; score: number; desc: string
}
export interface WorkshopSearch { items: WorkshopItem[]; total: number; page: number }

export interface PluginsResponse { enabled: { file: string; protected: boolean }[]; disabled: { file: string }[]; raw: string }

export interface Me { username: string; role: string; steamid: string | null; flags: string; created: number; last_login: number | null }

export interface Account {
  id: number; username: string; role: string; steamid: string | null; flags: string | null; note: string | null
  created: number; last_login: number | null
}

export interface PerfRow { t: string; humans: number; cpu: number; out_kb: number; fps: number }

export interface Out { out: string }
