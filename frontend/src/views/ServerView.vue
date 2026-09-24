<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { cancelInstall, getInstall, serverAction, startInstall } from '../api/endpoints'
import type { InstallDefaults, InstallOverview } from '../api/types'
import { toast } from '../composables/useToast'
import { session } from '../stores/session'

const st = computed(() => session.status)
const NAMES: Record<string, string> = { restart: '重启', start: '启动', stop: '停止', monitor: '巡检' }
const load = computed(() => st.value?.sys.load?.split(' ') ?? [])
const memPct = computed(() => st.value?.sys.mem_total_mb ? Math.round(100 * (st.value.sys.mem_used_mb || 0) / st.value.sys.mem_total_mb) + '%' : '-')
const memLine = computed(() => st.value?.sys.mem_total_mb ? `${st.value.sys.mem_used_mb} / ${st.value.sys.mem_total_mb} MB` : '')
const uptime = computed(() => { const h = st.value?.sys.uptime_h; if (h == null) return '-'; const t = Math.round(h); return t >= 48 ? `${Math.floor(t / 24)} d ${t % 24} h` : `${h} h` })
const actMsg = computed(() => (st.value?.action.running ? '正在执行 ' + st.value.action.running + '… ' : '') + (st.value?.action.last || ''))
const actionPending = ref(false)
const info = ref<InstallOverview | null>(null), error = ref(''), submitting = ref(false), cancelling = ref(false)
const form = ref<InstallDefaults>({ game_port: 27015, tick: 30, vac: false, mirror_url: 'docker.cnb.cool' })
const running = computed(() => info.value?.job?.state === 'running')
const busy = computed(() => !!running.value || submitting.value || actionPending.value || !!st.value?.action.running)
const progress = computed(() => info.value?.job?.total ? Math.min(100, Math.round(100 * (info.value.job.done || 0) / info.value.job.total)) : null)
let timer: ReturnType<typeof setTimeout> | undefined, alive = true, loading = false, defaultsSet = false
let revision = 0

async function refresh() {
  if (loading || !alive) return
  loading = true
  const requestRevision = revision
  try {
    const result = await getInstall()
    if (!alive || requestRevision !== revision) return
    const wasRunning = running.value
    info.value = result; error.value = ''
    if (!defaultsSet) { form.value = { ...result.defaults }; defaultsSet = true }
    if (wasRunning && result.job?.state !== 'running') void session.refreshStatus()
  } catch (e) {
    if (alive && requestRevision === revision) error.value = (e as Error).message
  } finally {
    loading = false
    clearTimeout(timer)
    if (alive) timer = setTimeout(refresh, running.value || busy.value ? 2000 : 5000)
  }
}
async function act(name: string) {
  if (busy.value) return
  if (name !== 'monitor' && !confirm('确定' + NAMES[name] + '服务器？')) return
  actionPending.value = true
  try {
    const result = await serverAction(name)
    toast(result.ok ? '已开始' + NAMES[name] : '安装或服务器操作正在进行，请稍后重试', !result.ok)
    await session.refreshStatus()
  } catch (e) { toast((e as Error).message, true) }
  finally { actionPending.value = false }
}
async function beginInstall() {
  if (busy.value || !info.value?.available || info.value.installed || error.value) return
  if (!Number.isInteger(form.value.game_port) || form.value.game_port < 1 || form.value.game_port > 65535) {
    toast('端口必须是 1 到 65535 的整数', true); return
  }
  if (!confirm('将下载 L4D2 游戏镜像，安装到显示的游戏目录并启动。完成后由当前面板管理，继续？')) return
  submitting.value = true; revision++
  try {
    await startInstall({ ...form.value, mirror_url: form.value.mirror_url.trim() })
    toast('安装任务已提交，可离开页面后回来查看')
    revision++
    // Show the accepted job promptly; backend still prevents duplicate requests.
    if (info.value) info.value.job = { state: 'running', msg: '正在准备安装…' }
  } catch (e) { toast((e as Error).message, true) }
  finally { submitting.value = false; void refresh() }
}
async function stopInstall() {
  if (!running.value || cancelling.value || info.value?.job?.cancel) return
  cancelling.value = true; revision++
  try {
    await cancelInstall()
    if (info.value?.job) info.value.job.cancel = true
    toast('正在取消，已安装的文件会保留')
  } catch (e) { toast((e as Error).message, true) }
  finally { cancelling.value = false; void refresh() }
}
onMounted(refresh)
onBeforeUnmount(() => { alive = false; revision++; clearTimeout(timer) })
</script>

<template>
  <section class="view on">
    <div v-if="session.features?.server_control || session.features?.lgsm" class="card">
      <h2>服务器控制 <span class="mu">{{ st?.backend === 'docker' ? 'Docker' : 'LinuxGSM' }}</span></h2>
      <div class="row"><button v-for="name in ['restart', 'start', 'stop', 'monitor']" :key="name" :class="name === 'stop' ? 'd' : name === 'restart' ? '' : 'g'" :disabled="busy" @click="act(name)">{{ NAMES[name] }}</button></div>
      <div role="status" class="mu">{{ actMsg }}</div>
      <div class="note">重启会断开所有玩家；Docker 巡检只查询容器状态。容器运行后，游戏仍需时间加载地图。</div>
    </div>
    <div v-if="st?.server_error" role="alert" class="card">{{ st.server_error }}</div>
    <div class="card">
      <h2>一键安装游戏<span class="sp" /><span class="mu">{{ !info ? '检测环境中…' : running ? '安装中' : info.installed ? '已安装' : '待安装' }}</span></h2>
      <div v-if="error" role="alert" class="hint">状态读取失败：{{ error }}（正在重试）</div>
      <div v-if="info && !info.available" role="alert" class="hint">{{ info.reason }}</div>
      <template v-if="!info?.installed">
        <div class="row">
          <label>游戏端口 <input v-model.number="form.game_port" type="number" min="1" max="65535" style="width:100px" :disabled="busy || !info"></label>
          <label>Tick <select v-model.number="form.tick" :disabled="busy || !info"><option v-for="n in [30, 60, 100, 128]" :key="n" :value="n">{{ n }}</option></select></label>
          <label><input v-model="form.vac" type="checkbox" :disabled="busy || !info"> 启用 VAC</label>
        </div>
        <div class="row"><label for="docker-mirror">镜像源</label><input id="docker-mirror" v-model="form.mirror_url" placeholder="留空使用 Docker Hub" :disabled="busy || !info" style="flex:1"></div>
        <div class="row">
          <button v-if="!running" :disabled="busy || !info?.available || !!error" @click="beginInstall">{{ submitting ? '正在提交…' : info?.job?.state === 'error' ? '重试安装' : '开始安装' }}</button>
          <button v-else class="d" :disabled="cancelling || info?.job?.cancel" @click="stopInstall">{{ cancelling || info?.job?.cancel ? '正在取消…' : '取消安装' }}</button>
        </div>
      </template>
      <p v-if="info?.job" role="status">{{ info.job.msg }}</p>
      <div v-if="running && progress != null" class="bar" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100" aria-label="安装阶段"><span :style="{ width: progress + '%' }" /></div>
      <pre v-if="info?.job?.logs?.length" aria-label="安装日志">{{ info.job.logs.join('\n') }}</pre>
      <p v-if="info" class="hint">游戏目录：{{ info.game_dir }}<br>Compose：{{ info.compose_file }}</p>
      <div class="note">只安装游戏，由当前面板管理。默认 30 Tick；更高 Tick 需要对应扩展支持。SourceMod、白名单、特感预设和积分插件需另行安装；面板按实际插件显示功能。请放行游戏端口 TCP/UDP。安装在后台执行，取消不会删除游戏数据。</div>
    </div>
    <div class="band sys">
      <div class="tile"><div class="k">系统负载</div><div class="v">{{ load[0] || '-' }}</div><div class="s">{{ load.length > 2 ? `5 分钟 ${load[1]} · 15 分钟 ${load[2]}` : '' }}</div></div>
      <div class="tile"><div class="k">内存</div><div class="v">{{ memPct }}</div><div class="s">{{ memLine }}</div></div>
      <div class="tile"><div class="k">系统已运行</div><div class="v">{{ uptime }}</div><div class="s">面板所在主机</div></div>
      <div class="tile"><div class="k">{{ st?.backend === 'docker' ? '游戏容器' : '游戏进程' }}</div><div class="v cn">{{ st ? (st.srcds ? '运行中' : '未运行') : '-' }}</div><div class="s">{{ st?.backend === 'docker' ? 'Docker · l4d2' : 'srcds_linux' }}</div></div>
    </div>
  </section>
</template>
