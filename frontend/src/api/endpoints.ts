import { api, upload } from './client'
import type { Account, AddonsResponse, InstallOverview, InstallRequest, Me, Out, PerfRow, Player, PluginConfigDocument, PluginConfigFile, PluginConfigMode, PluginConfigResult, PluginRuntimeValue, PluginsResponse, Status, UploadResult, WorkshopSearch } from './types'

export const getSetup = () => api<{ needed: boolean; username: string }>('/api/setup')
export const postSetup = (password: string) => api<{ ok: true }>('/api/setup', { password })
export const login = (username: string, password: string) => api<{ ok: true }>('/api/login', { username, password })
export const logout = () => api<{ ok: true }>('/api/logout', {})

export const getStatus = () => api<Status>('/api/status')
export const getPlayers = () => api<{ players: Player[]; raw: string }>('/api/players')
export const getWhitelist = () => api<{ list: string[] }>('/api/whitelist')
export const editWhitelist = (op: 'add' | 'del', steamid: string, note = '') => api<Out & { list: string[] }>('/api/whitelist', { op, steamid, note })
export const enableWhitelist = (enable: boolean) => api<Out>('/api/whitelist_enable', { enable })
export const kick = (userid: number | string) => api<Out>('/api/kick', { userid })
export const givePoints = (target: string, amount: number) => api<Out>('/api/points', { target, amount })

export const rcon = (cmd: string) => api<Out>('/api/rcon', { cmd })
export const setPreset = (name: string) => api<Out>('/api/preset', { name })
export const setDifficulty = (level: string) => api<Out>('/api/difficulty', { level })
export const setDamage = (o: { ff?: number; burn?: number }) => api<Out & { persisted: boolean }>('/api/damage', o)
export const changeMap = (map: string) => api<Out>('/api/map', { map })
export const serverAction = (name: string) => api<{ ok: boolean; running: string | null }>('/api/action', { name })
export const getInstall = () => api<InstallOverview>('/api/install')
export const startInstall = (o: InstallRequest) => api<{ ok: true; id: string }>('/api/install', o)
export const cancelInstall = () => api<{ ok: true }>('/api/install/cancel', {})

export const getAddons = () => api<AddonsResponse>('/api/addons')
export const deleteAddon = (name: string) => api<{ ok: true; out: string; addons: AddonsResponse['addons'] }>('/api/addons', { op: 'delete', name })
export const startWorkshop = (id: string) => api<{ ok: true; id: string }>('/api/addons', { op: 'workshop', id })
export const cancelWorkshop = (id: string) => api<{ ok: true }>('/api/addons', { op: 'workshop_cancel', id })
export const startZip = (name: string) => api<{ ok: true; token: string }>('/api/addons', { op: 'zip', name })
export const uploadCampaign = (file: File, onProgress?: (p: number) => void) =>
  upload<UploadResult>('/api/upload?name=' + encodeURIComponent(file.name), file, onProgress)
export const workshopSearch = (q: string, page: number) => api<WorkshopSearch>('/api/workshop_search?q=' + encodeURIComponent(q) + '&page=' + page)

export const getPlugins = () => api<PluginsResponse>('/api/plugins')
export const pluginAction = (op: string, file: string) => api<Out & PluginsResponse>('/api/plugins', { op, file })
export const uploadSmx = (file: File) => upload<{ ok: true; out: string } & PluginsResponse>('/api/plugin_upload?name=' + encodeURIComponent(file.name), file)
export const getPluginConfigs = (plugin: string) => api<{ plugin: string; files: PluginConfigFile[] }>('/api/plugin-configs?plugin=' + encodeURIComponent(plugin))
export const getPluginConfig = (plugin: string, file: string) => api<PluginConfigDocument>('/api/plugin-config?plugin=' + encodeURIComponent(plugin) + '&file=' + encodeURIComponent(file))
export const getPluginRuntime = (plugin: string, file: string, names: string[]) => api<{ values: PluginRuntimeValue[] }>('/api/plugin-config/runtime', { plugin, file, names })
export const updatePluginConfig = (plugin: string, file: string, revision: string, updates: Record<string, string>, mode: PluginConfigMode) =>
  api<PluginConfigResult>('/api/plugin-config', { plugin, file, revision, updates, mode })
export const restorePluginConfig = (plugin: string, file: string, revision: string, backup_id: string) =>
  api<Omit<PluginConfigResult, 'applied'>>('/api/plugin-config/restore', { plugin, file, revision, backup_id })

export const getLogs = (kind: string) => api<{ lines: string[] }>('/api/logs?' + kind)
export const getPerf = () => api<{ rows: PerfRow[] }>('/api/logs?perfjson')

export const getMe = () => api<Me>('/api/me')
export const changePassword = (current: string, password: string) => api<{ ok: true }>('/api/me', { op: 'password', current, password })
export const bindSteam = (steamid: string) => api<{ ok: true; steamid: string; out: string }>('/api/me', { op: 'steamid', steamid })
export const getAccounts = () => api<{ accounts: Account[]; me: string }>('/api/accounts')
export const createAccount = (o: { username: string; password: string; role: string; steamid: string; flags: string }) => api<{ ok: true; out: string }>('/api/accounts', { op: 'create', ...o })
export const updateAccount = (o: { id: number; steamid?: string; password?: string }) => api<{ ok: true; out: string }>('/api/accounts', { op: 'update', ...o })
export const deleteAccount = (id: number) => api<{ ok: true; out: string }>('/api/accounts', { op: 'delete', id })
