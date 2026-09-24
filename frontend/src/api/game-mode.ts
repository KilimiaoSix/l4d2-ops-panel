import { api } from './client'

export interface GameModeOption {
  group?: string
  english?: string
  base?: string
  native_players?: number
  id: string
  name: string
  description: string
  map: string
  map_name: string
}

export interface GameModeStatus {
  mode: string | null
  map: string | null
  read_error: string | null
  saved_mode: string | null
  config_error: string | null
  modes: GameModeOption[]
}

export interface GameModeSwitchResult {
  state: 'switching' | 'uncertain'
  mode: string
  map: string
  message: string
  persisted: true
  backup: string | null
}

export const getGameMode = () => api<GameModeStatus>('/api/game-mode')
export const setGameMode = (mode: string) => api<GameModeSwitchResult>('/api/game-mode', { mode })
