<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { Onboarding, PluginPackStatus } from '../api/types'

const props = defineProps<{ persistDraft?: boolean }>()
const data = ref<PluginPackStatus>(), selected = ref<string[]>(['minimal']), error = ref(''), busy = ref(false)
const stop = ref(false), initialized = ref(false)
let alive = true, revision = 0, timer: ReturnType<typeof setTimeout> | undefined
let draftQueue = Promise.resolve()
function saveDraft() {
  if (!props.persistDraft || !initialized.value) return
  const packs = [...selected.value]
  // Draft-only saves never move a wizard step after navigation; preserve ordering.
  draftQueue = draftQueue.then(async () => {
    try { await api('/api/onboarding', { draft: { packs } }) }
    catch (e) { if (alive) error.value = '选项暂未保存：' + (e as Error).message }
  })
}
function selectProfile(full: boolean) { selected.value = full ? [...data.value!.profiles.full!] : ['minimal']; saveDraft() }
const running = computed(() => data.value?.job?.state === 'running')
const labels = { not_installed: '未安装', restart_required: '已安装，待启动确认', active: '运行中已确认', unknown: '运行状态未知', incomplete: '事务待恢复' }
const closure = computed(() => {
  const names = new Set<string>()
  function visit(id: string) { if (names.has(id)) return; names.add(id); data.value?.packs.find(p => p.id === id)?.requires.forEach(visit) }
  selected.value.forEach(visit)
  return [...names].map(id => data.value?.packs.find(p => p.id === id)).filter(p => p && !p.visible)
})
async function load(probe = false) {
  if (timer) clearTimeout(timer)
  const rev = ++revision
  try {
    const value = await api<PluginPackStatus>('/api/plugin-packs' + (probe ? '?probe=true' : ''))
    const draft = !initialized.value && props.persistDraft ? await api<Onboarding>('/api/onboarding') : null
    if (!alive || rev !== revision) return
    data.value = value
    if (!initialized.value) {
      const saved = draft?.draft.packs
      selected.value = Array.isArray(saved) && saved.every(p => typeof p === 'string' && value.packs.some(x => x.id === p && x.visible))
        ? ['minimal', ...saved.filter(p => p !== 'minimal') as string[]]
        : value.packs.filter(p => p.default || p.installed && p.visible).map(p => p.id)
      initialized.value = true
    }
  } catch (e) { if (alive && rev === revision) error.value = (e as Error).message }
  finally { if (alive && rev === revision && running.value) timer = setTimeout(() => load(), 1500) }
}
async function action(kind: 'install' | 'recover' | 'cancel') {
  if (busy.value) return
  busy.value = true; error.value = ''; revision++
  if (timer) clearTimeout(timer)
  try {
    await api('/api/plugin-packs/' + kind, kind === 'install' ? { packs: selected.value, stop_game: stop.value } : kind === 'recover' ? { stop_game: stop.value } : {})
    if (alive) await load()
  } catch (e) { if (alive) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
onMounted(() => load())
onBeforeUnmount(() => { alive = false; revision++; if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="card">
    <h2>插件包<span class="sp" /><button class="g sm" :disabled="busy || running" @click="load(true)">检查实际加载状态</button></h2>
    <p>默认最小包适合原生四人合作。多人、特感和积分可随时补装。</p>
    <p v-if="error" class="hint" role="alert">{{ error }}</p>
    <template v-if="data">
      <p v-if="!data.game_installed" class="hint">先完成游戏安装，再安装插件包。<RouterLink to="/server">安装游戏</RouterLink></p>
      <div class="row"><button class="g sm" :disabled="busy || running" @click="selectProfile(false)">只选最小包</button><button class="g sm" :disabled="busy || running" @click="selectProfile(true)">选择全套</button></div>
      <label v-for="pack in data.packs.filter(p => p.visible)" :key="pack.id" class="pack-option">
        <input v-model="selected" type="checkbox" :value="pack.id" :disabled="pack.required || busy || running" @change="saveDraft">
        <span><strong>{{ pack.name }}</strong> · {{ labels[pack.state] }}<br><span class="mu">{{ pack.summary }}</span><br><span v-if="!pack.available" class="hint">当前发布物尚无此包的完整载荷，暂不可安装。</span></span>
      </label>
      <p v-if="closure.length" class="mu">自动包含依赖：{{ closure.map(p => p!.name).join('、') }}。L4DToolZ 从官方固定版本下载并校验。</p>
      <p>安装会保留管理员、白名单和已有插件配置；非托管的同名二进制会报告冲突。文件安装成功后，仍需启动游戏检查实际加载。</p>
      <label class="row"><input v-model="stop" type="checkbox" :disabled="busy || running">如果游戏正在运行，允许停止游戏后安装或恢复（会断开所有玩家）</label>
      <div v-if="data.pending" class="hint"><p>存在未完成的事务：{{ data.pending.phase }}。先恢复，再开服或重试。</p><ul><li v-for="message in data.pending.errors" :key="message">{{ message }}</li></ul><button :disabled="busy || running" @click="action('recover')">恢复上次安装</button></div>
      <div class="row" style="margin-top:12px">
        <button :disabled="busy || running || !data.game_installed || !!data.pending || selected.some(id => !data!.packs.find(p => p.id === id)?.available)" @click="action('install')">{{ stop ? '停止并安装所选插件' : '安装所选插件' }}</button>
        <button v-if="running" class="d" :disabled="busy || data.job?.cancel" @click="action('cancel')">{{ data.job?.cancel ? '正在取消并回滚…' : '取消安装' }}</button>
        <RouterLink v-if="data.packs.some(p => p.installed) && !data.pending" to="/server">前往启动游戏</RouterLink>
      </div>
      <p v-if="data.job" :role="data.job.state === 'error' ? 'alert' : 'status'">{{ data.job.msg }}<span v-if="data.job.total"> · {{ data.job.done }}/{{ data.job.total }} 个文件</span></p>
    </template>
  </div>
</template>

<style scoped>
.pack-option { display: flex; align-items: flex-start; gap: 12px; margin: 18px 0; }
.pack-option input { margin-top: 5px; }
</style>
