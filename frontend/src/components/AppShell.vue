<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../api/endpoints'
import { usePolling } from '../composables/usePolling'
import { toast } from '../composables/useToast'
import { VIEWS } from '../router'
import { session } from '../stores/session'
import Mark from './Mark.vue'

const route = useRoute(), router = useRouter()
const current = computed(() => VIEWS.find(v => v.name === route.name) ?? VIEWS[0]!)
const st = computed(() => session.status)
const pillText = computed(() => st.value?.online ? '在线' : (st.value?.srcds ? '进程在，游戏未响应' : '离线'))
const pillClass = computed(() => st.value ? (st.value.online ? 'on' : 'off') : '')
// page footer vitals (the 服务器 page shows the detailed version of the same numbers)
const load1 = computed(() => st.value?.sys.load?.split(' ')[0] || '-')
const memPct = computed(() => st.value?.sys.mem_total_mb ? Math.round(100 * (st.value.sys.mem_used_mb || 0) / st.value.sys.mem_total_mb) + '%' : '-')
const proc = computed(() => st.value ? (st.value.srcds ? '运行中' : '未运行') : '-')
const connect = computed(() => st.value?.display_host ? 'connect ' + st.value.display_host : '')

async function copyConnect() {
  const t = connect.value
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(t)
    else {   // plain http on a LAN: the clipboard API is unavailable, fall back to the legacy command
      const ta = document.createElement('textarea'); ta.value = t; ta.style.cssText = 'position:fixed;opacity:0'
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove()
    }
    toast('已复制：' + t)
  } catch { toast('复制失败，请手动选中文本复制', true) }
}

usePolling(() => session.refreshStatus(), 10000)
usePolling(() => session.refreshPlayers(), 30000)

async function doLogout() {
  try { await logout() } catch { /* the session is gone either way */ }
  session.phase = 'login'; session.status = null
}
</script>

<template>
  <div id="shell">
    <div class="tape" />
    <div id="app-body" class="app-body">
      <aside id="side">
        <div class="brand">
          <Mark /><div class="min"><div class="eyebrow">L4D2 Ops</div><div class="name">{{ st?.title || 'L4D2 面板' }}</div></div>
        </div>
        <div class="srv">
          <span class="pill" :class="pillClass"><i /><span>{{ st ? pillText : '连接中' }}</span></span>
          <div class="kv"><span class="k">地图</span><code>{{ st?.online ? st.map : '—' }}</code></div>
          <div class="kv"><span class="k">玩家</span><b>{{ st?.online ? `${st.players} / ${st.max}` : '—' }}</b></div>
        </div>
        <nav>
          <button v-for="v in VIEWS" :key="v.name" :class="{ on: v.name === current.name }" @click="router.push('/' + v.name)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <template v-if="v.name === 'overview'"><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></template>
              <template v-else-if="v.name === 'players'"><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><circle cx="17" cy="9" r="2.5" /><path d="M21 19c0-2.5-1.8-4.5-4-4.5" /></template>
              <template v-else-if="v.name === 'game'"><path d="M4 7h9M19 7h1M4 17h3M13 17h7" /><circle cx="16" cy="7" r="2.5" /><circle cx="10" cy="17" r="2.5" /></template>
              <template v-else-if="v.name === 'maps'"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" /><path d="M9 4v14M15 6v14" /></template>
              <template v-else-if="v.name === 'plugins'"><path d="M10 4a2 2 0 1 1 4 0v1h4a1 1 0 0 1 1 1v4h-1a2 2 0 1 0 0 4h1v4a1 1 0 0 1-1 1h-4v-1a2 2 0 1 0-4 0v1H6a1 1 0 0 1-1-1v-4h1a2 2 0 1 0 0-4H5V6a1 1 0 0 1 1-1h4z" /></template>
              <template v-else-if="v.name === 'console'"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></template>
              <template v-else-if="v.name === 'logs'"><path d="M5 4h10l4 4v12H5z" /><path d="M15 4v4h4M8 12h8M8 16h8" /></template>
              <template v-else-if="v.name === 'server'"><rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01" /></template>
              <template v-else><circle cx="8" cy="12" r="4" /><path d="M12 12h9M18 12v3M15 12v2" /></template>
            </svg>{{ v.title }}
          </button>
        </nav>
      </aside>
      <div id="main">
        <header>
          <div class="ttl"><div class="eyebrow">{{ current.eyebrow }}</div><h1>{{ current.title }}</h1></div>
          <span class="sp" />
          <div class="meta">
            <span>刷新于 <span>{{ session.refreshedAt || '—' }}</span></span>
            <button class="g sm" title="我的账号" @click="router.push('/accounts')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></svg>
              <span>{{ session.user }}{{ session.role === 'owner' ? ' · owner' : '' }}</span>
            </button>
            <button class="g sm" @click="doLogout">退出</button>
          </div>
        </header>
        <RouterView :key="String(route.name)" />
        <footer id="pfoot">
          <div v-if="connect" id="f-conn" class="fs"><span class="k">连接地址</span><code>{{ connect }}</code><button class="g sm" @click="copyConnect">复制</button></div>
          <span class="sp" />
          <div class="fs"><span class="k">负载</span><b>{{ load1 }}</b></div>
          <div class="fs"><span class="k">内存</span><b>{{ memPct }}</b></div>
          <div class="fs"><span class="k">游戏进程</span><b>{{ proc }}</b></div>
        </footer>
      </div>
    </div>
  </div>
</template>
