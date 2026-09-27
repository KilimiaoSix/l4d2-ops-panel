import { api } from './client'
import type { Onboarding, PanelConfiguration, PanelConfigResult, PanelValue, SetupStep } from './types'

export const getPanelConfig = () => api<PanelConfiguration>('/api/panel-config')
export const savePanelConfig = (revision: string, updates: Record<string, PanelValue>, restart: boolean) =>
  api<PanelConfigResult>('/api/panel-config', { revision, updates, restart })
export const getOnboarding = () => api<Onboarding>('/api/onboarding')
export const saveOnboarding = (step: SetupStep, draft: Record<string, unknown> = {}, complete = false, reopen = false) =>
  api<Onboarding>('/api/onboarding', { step, draft, complete, reopen })
