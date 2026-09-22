<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getPerf } from '../api/endpoints'
import type { PerfRow } from '../api/types'
import Sparkline from '../components/Sparkline.vue'
import { usePolling } from '../composables/usePolling'
import { DIFFICULTY_NAMES } from '../data/campaigns'
import { session } from '../stores/session'

const router = useRouter()
const st = computed(() => session.status)
const sys = computed(() => st.value?.sys ?? {})
const perfRows = ref<PerfRow[]>([])
const diffLine = computed(() => `难度 ${DIFFICULTY_NAMES[st.value?.difficulty ?? ''] ?? '-'} · 白名单${st.value?.whitelist === null || st.value?.whitelist === undefined ? '?' : st.value.whitelist ? '开' : '关'}`)

usePolling(async () => { try { perfRows.value = (await getPerf()).rows } catch { /* keep the last curve */ } }, 60000)
</script>

<template>
  <section class="view on">
    <div class="band">
      <div class="tile"><div class="k">玩家</div><div class="v">{{ st?.online ? `${st.players} / ${st.max}` : '-' }}</div><div class="s">{{ st?.online ? `bot ${st.bots}` : '' }}</div></div>
      <div class="tile"><div class="k">地图</div><div class="v mono">{{ st?.online ? st.map : '-' }}</div><div class="s">{{ st?.online ? st.name : '' }}</div></div>
      <div class="tile"><div class="k">特感预设</div><div class="v">{{ st?.preset || '-' }}</div><div class="s">{{ diffLine }}</div></div>
      <div class="tile"><div class="k">Server FPS</div><div class="v">{{ st?.perf ? st.perf.fps : '-' }}</div><div class="s">≥ 29 正常（有人时采样）</div></div>
      <div class="tile"><div class="k">出流量</div><div class="v">{{ st?.perf ? st.perf.out_kb + ' KB/s' : '-' }}</div><div class="s">5M 带宽上限 ≈ 625 KB/s</div></div>
      <div class="tile"><div class="k">系统负载</div><div class="v">{{ sys.load ? sys.load.split(' ')[0] : '-' }}</div><div class="s">{{ sys.mem_used_mb ? `内存 ${sys.mem_used_mb}/${sys.mem_total_mb} MB · 已运行 ${sys.uptime_h} h` : '' }}</div></div>
    </div>
    <div class="grid">
      <div class="card"><h2>性能<span class="sp" /><span class="mu">最近 120 次采样</span></h2>
        <div class="sl"><span class="k">Server FPS</span><Sparkline :values="perfRows.map(r => r.fps)" color="#5ed389" :min="0" :max="32" /></div>
        <div class="sl"><span class="k">出流量 KB/s</span><Sparkline :values="perfRows.map(r => r.out_kb)" color="#f0a13a" :min="0" /></div>
      </div>
      <div class="card"><h2>在线玩家<span class="sp" /><button class="g sm" @click="router.push('/players')">管理</button></h2>
        <div class="tw"><table>
          <tr><th>名字</th><th>在线</th><th>延迟</th></tr>
          <tr v-for="p in session.players" :key="p.userid"><td>{{ p.name }}</td><td class="mu">{{ p.time }}</td><td class="mu">{{ p.ping }} ms</td></tr>
          <tr v-if="!session.players.length"><td colspan="3" class="mu">当前没有玩家</td></tr>
        </table></div>
      </div>
    </div>
  </section>
</template>
