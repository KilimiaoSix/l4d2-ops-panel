import { createRouter, createWebHashHistory } from 'vue-router'
import AccountsView from './views/AccountsView.vue'
import ConsoleView from './views/ConsoleView.vue'
import GameView from './views/GameView.vue'
import LogsView from './views/LogsView.vue'
import MapsView from './views/MapsView.vue'
import OverviewView from './views/OverviewView.vue'
import PlayersView from './views/PlayersView.vue'
import PluginsView from './views/PluginsView.vue'
import ServerView from './views/ServerView.vue'
import PanelConfigView from './views/PanelConfigView.vue'
import PanelSetupView from './views/PanelSetupView.vue'

export interface ViewMeta { title: string; eyebrow: string }

export const VIEWS: { name: string; title: string; eyebrow: string; component: unknown }[] = [
  { name: 'overview', title: '概览', eyebrow: 'Overview', component: OverviewView },
  { name: 'players', title: '玩家 / 白名单', eyebrow: 'Players · Whitelist', component: PlayersView },
  { name: 'game', title: '游戏设置', eyebrow: 'Game settings', component: GameView },
  { name: 'maps', title: '地图 / 战役', eyebrow: 'Maps · Campaigns', component: MapsView },
  { name: 'plugins', title: '插件', eyebrow: 'SourceMod plugins', component: PluginsView },
  { name: 'console', title: '控制台', eyebrow: 'RCON console', component: ConsoleView },
  { name: 'logs', title: '日志 / 性能', eyebrow: 'Logs · Perf', component: LogsView },
  { name: 'server', title: '服务器', eyebrow: 'Server', component: ServerView },
  { name: 'accounts', title: '账号', eyebrow: 'Accounts', component: AccountsView },
  { name: 'panel', title: '面板设置', eyebrow: 'Panel settings', component: PanelConfigView },
  { name: 'setup', title: '开服向导', eyebrow: 'Getting started', component: PanelSetupView },
]

// Setup stays addressable, but belongs to panel settings rather than daily navigation.
export const NAV_VIEWS = VIEWS.filter(v => v.name !== 'setup')

const LAST_VIEW_KEY = 'l4d2view'

function lastView(): string {
  try { const v = localStorage.getItem(LAST_VIEW_KEY); if (v && NAV_VIEWS.some(x => x.name === v)) return v } catch { /* storage may be unavailable */ }
  return 'overview'
}

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    ...VIEWS.map(v => ({ path: '/' + v.name, name: v.name, component: v.component as never, meta: { title: v.title, eyebrow: v.eyebrow } })),
    { path: '/:pathMatch(.*)*', redirect: () => '/' + lastView() },
  ],
})

router.afterEach((to) => {
  if (typeof to.name === 'string' && NAV_VIEWS.some(v => v.name === to.name)) { try { localStorage.setItem(LAST_VIEW_KEY, to.name) } catch { /* ignore */ } }
})

/** The single-file panel deep-linked as #players; keep those links working (#players -> #/players). */
export function upgradeLegacyHash() {
  const m = /^#([a-z]+)$/.exec(location.hash)
  if (m && VIEWS.some(v => v.name === m[1])) history.replaceState(null, '', '#/' + m[1])
}
