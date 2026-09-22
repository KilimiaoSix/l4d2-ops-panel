<script setup lang="ts">
import { computed } from 'vue'
import { serverAction } from '../api/endpoints'
import { run } from '../composables/useToast'
import { session } from '../stores/session'

const st = computed(() => session.status)
const NAMES: Record<string, string> = { restart: '重启', start: '启动', stop: '停止', monitor: '巡检' }
const load = computed(() => st.value?.sys.load?.split(' ') ?? [])
const memPct = computed(() => st.value?.sys.mem_total_mb ? Math.round(100 * (st.value.sys.mem_used_mb || 0) / st.value.sys.mem_total_mb) + '%' : '-')
const memLine = computed(() => st.value?.sys.mem_total_mb ? `${st.value.sys.mem_used_mb} / ${st.value.sys.mem_total_mb} MB` : '')
const uptime = computed(() => { const h = st.value?.sys.uptime_h; if (h == null) return '-'; const t = Math.round(h); return t >= 48 ? `${Math.floor(t / 24)} d ${t % 24} h` : `${h} h` })
const actMsg = computed(() => (st.value?.action.running ? '正在执行 ' + st.value.action.running + '… ' : '') + (st.value?.action.last || ''))

async function act(n: string) {
  if (n !== 'monitor' && !confirm('确定' + NAMES[n] + '服务器？')) return
  await run(() => serverAction(n), '已开始' + NAMES[n]).catch(() => {})
  setTimeout(() => session.refreshStatus(), 2000); setTimeout(() => session.refreshStatus(), 20000)
}
</script>

<template>
  <section class="view on">
    <div v-if="session.features?.lgsm" class="card"><h2>服务器控制<span class="sp" /><span class="mu">{{ actMsg }}</span></h2>
      <div class="row"><button @click="act('restart')">重启</button><button class="g" @click="act('start')">启动</button><button class="d" @click="act('stop')">停止</button><button class="g" @click="act('monitor')">巡检</button></div>
      <div class="note">重启约 1 分钟；有玩家在线时会断开所有人。</div>
    </div>
    <div class="band sys">
      <div class="tile"><div class="k">系统负载</div><div class="v">{{ load[0] || '-' }}</div><div class="s">{{ load.length > 2 ? `5 分钟 ${load[1]} · 15 分钟 ${load[2]}` : '' }}</div></div>
      <div class="tile"><div class="k">内存</div><div class="v">{{ memPct }}</div><div class="s">{{ memLine }}</div></div>
      <div class="tile"><div class="k">系统已运行</div><div class="v">{{ uptime }}</div><div class="s">自上次开机</div></div>
      <div class="tile"><div class="k">游戏进程</div><div class="v cn">{{ st ? (st.srcds ? '运行中' : '未运行') : '-' }}</div><div class="s">srcds_linux</div></div>
    </div>
  </section>
</template>
