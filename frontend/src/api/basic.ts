import { api } from './client'
import type { BasicOverview, BasicResult, BasicFieldResult } from './types'

export const getBasicSettings = () => api<BasicOverview>('/api/basic-settings')
export const saveBasicSettings = (revision: string, mode: 'save' | 'apply' | 'save_apply', values: Record<string, string | number>) =>
  api<BasicResult>('/api/basic-settings', { revision, mode, ...values })
export const getBasicRuntime = (names: string[]) => api<{ fields: Record<string, BasicFieldResult> }>('/api/basic-settings/runtime', { names })
export const recoverBasicSettings = () => api<{ recovered: boolean }>('/api/basic-settings/recover', {})
