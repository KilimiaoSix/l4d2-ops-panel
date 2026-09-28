<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../api/endpoints'
import { usePolling } from '../composables/usePolling'
import { NAV_VIEWS, VIEWS } from '../router'
import { session } from '../stores/session'
import Mark from './Mark.vue'
import JoinServerCard from './JoinServerCard.vue'

const route = useRoute(), router = useRouter()
const current = computed(() => VIEWS.find(v => v.name === route.name) ?? VIEWS[0]!)
const activeNav = computed(() => current.value.name === 'setup' ? 'panel' : current.value.name)
const st = computed(() => session.status)
const gameMissing = computed(() => st.value?.game_installed === false && !['accounts', 'panel', 'server', 'setup'].includes(String(route.name)))
onMounted(() => { if (session.role === 'owner' && st.value?.onboarding_complete === false) void router.replace('/setup') })
const pillText = computed(() => st.value?.online ? '在线' : (st.value?.srcds ? '进程在，游戏未响应' : '离线'))
const pillClass = computed(() => st.value ? (st.value.online ? 'on' : 'off') : '')
// page footer vitals (the 服务器 page shows the detailed version of the same numbers)
const load1 = computed(() => st.value?.sys.load?.split(' ')[0] || '-')
const memPct = computed(() => st.value?.sys.mem_total_mb ? Math.round(100 * (st.value.sys.mem_used_mb || 0) / st.value.sys.mem_total_mb) + '%' : '-')
const proc = computed(() => st.value ? (st.value.srcds ? '运行中' : '未运行') : '-')

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
        <nav aria-label="主导航">
          <button v-for="v in NAV_VIEWS" :key="v.name" :class="{ on: v.name === activeNav }" :aria-current="v.name === activeNav ? 'page' : undefined" @click="router.push('/' + v.name)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
              <template v-if="v.name === 'overview'"><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></template>
              <template v-else-if="v.name === 'players'"><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><circle cx="17" cy="9" r="2.5" /><path d="M21 19c0-2.5-1.8-4.5-4-4.5" /></template>
              <template v-else-if="v.name === 'game'"><path d="M4 7h9M19 7h1M4 17h3M13 17h7" /><circle cx="16" cy="7" r="2.5" /><circle cx="10" cy="17" r="2.5" /></template>
              <template v-else-if="v.name === 'maps'"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" /><path d="M9 4v14M15 6v14" /></template>
              <template v-else-if="v.name === 'plugins'"><path d="M10 4a2 2 0 1 1 4 0v1h4a1 1 0 0 1 1 1v4h-1a2 2 0 1 0 0 4h1v4a1 1 0 0 1-1 1h-4v-1a2 2 0 1 0-4 0v1H6a1 1 0 0 1-1-1v-4h1a2 2 0 1 0 0-4H5V6a1 1 0 0 1 1-1h4z" /></template>
              <template v-else-if="v.name === 'console'"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></template>
              <template v-else-if="v.name === 'logs'"><path d="M5 3h9l5 5v13H5zM14 3v5h5" /><path d="M8 15h2l1-3 2 6 1-3h2" /></template>
              <template v-else-if="v.name === 'server'"><rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01" /></template>
              <template v-else-if="v.name === 'accounts'"><circle cx="12" cy="7" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></template>
              <template v-else-if="v.name === 'panel'"><path d="M10 3h4l.6 2.6 1.6.9 2.5-.8 2 3.5-1.9 1.8v2l1.9 1.8-2 3.5-2.5-.8-1.6.9L14 21h-4l-.6-2.6-1.6-.9-2.5.8-2-3.5L5.2 13v-2L3.3 9.2l2-3.5 2.5.8 1.6-.9Z" /><circle cx="12" cy="12" r="3" /></template>
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
        <section v-if="gameMissing" class="view on"><div class="card">
          <h2>先安装游戏</h2><p>当前还没有游戏文件。安装完成后，这里会显示{{ current.title }}。</p>
          <button @click="router.push('/server')">前往安装游戏</button><button class="g" @click="router.push('/setup')">继续开服向导</button>
        </div></section>
        <RouterView v-else :key="String(route.name)" />
        <footer id="pfoot">
          <JoinServerCard compact />
          <span class="sp" />
          <div class="fs"><span class="k">负载</span><b>{{ load1 }}</b></div>
          <div class="fs"><span class="k">内存</span><b>{{ memPct }}</b></div>
          <div class="fs"><span class="k">游戏进程</span><b>{{ proc }}</b></div>
        </footer>
      </div>
    </div>
  </div>
</template>
