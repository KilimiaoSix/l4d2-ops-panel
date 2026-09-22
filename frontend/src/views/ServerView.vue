<script setup lang="ts">
import { computed } from 'vue'
import { serverAction } from '../api/endpoints'
import { run } from '../composables/useToast'
import { session } from '../stores/session'

const st = computed(() => session.status)
const NAMES: Record<string, string> = { restart: '重启', start: '启动', stop: '停止', monitor: '巡检' }
const sysLine = computed(() => {
  const s = st.value; if (!s?.sys.load) return '-'
  return `负载 ${s.sys.load} ｜ 内存 ${s.sys.mem_used_mb}/${s.sys.mem_total_mb} MB ｜ 系统已运行 ${s.sys.uptime_h} h ｜ 游戏进程 ${s.srcds ? '运行中' : '未运行'}`
})
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
      <div class="hint">重启约 1 分钟；有玩家在线时会断开所有人。</div>
    </div>
    <div class="card"><h2>系统</h2><div class="mu">{{ sysLine }}</div></div>
    <div v-if="st?.display_host" class="card"><h2>连接信息</h2><div class="mu">游戏：<code>connect {{ st.display_host }}</code></div></div>
  </section>
</template>
