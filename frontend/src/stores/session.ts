/** App-wide state: which screen is showing, the latest /api/status, the online players, who is logged in. */
import { reactive } from 'vue'
import { getPlayers, getSetup, getStatus } from '../api/endpoints'
import type { Player, Status } from '../api/types'

export type Phase = 'loading' | 'setup' | 'login' | 'app'

export const session = reactive({
  phase: 'loading' as Phase,
  setupUsername: 'admin',
  status: null as Status | null,
  players: [] as Player[],
  refreshedAt: '' as string,
  loginNote: '' as string,

  get role() { return this.status?.account?.role ?? 'admin' },
  get user() { return this.status?.account?.user ?? '' },
  get features() { return this.status?.features },
  get online() { return !!this.status?.online },

  loggedOut() {
    if (this.phase !== 'app') return
    this.phase = 'login'; this.status = null; this.players = []
  },

  async refreshStatus() {
    try {
      const s = await getStatus()
      this.status = s; this.refreshedAt = new Date().toLocaleTimeString()
      if (s.title) document.title = s.title
    } catch { /* the pill keeps its last state; 401 already switched the phase */ }
  },

  async refreshPlayers() {
    try { this.players = (await getPlayers()).players } catch { /* keep the last list */ }
  },

  /** First paint: a live session goes straight in, an uninitialised panel shows the setup page, otherwise login. */
  async boot() {
    try {
      this.status = await getStatus(); this.phase = 'app'; return
    } catch { /* not logged in (or the panel is unreachable) */ }
    try {
      const s = await getSetup()
      if (s.needed) { this.setupUsername = s.username; this.phase = 'setup'; return }
    } catch { /* fall through to the login page */ }
    this.phase = 'login'
  },
})
