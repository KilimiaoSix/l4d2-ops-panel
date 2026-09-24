<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import { getPluginConfig, getPluginConfigs, getPluginRuntime, restorePluginConfig, updatePluginConfig } from '../api/endpoints'
import type { PluginApplyResult, PluginConfigDocument, PluginConfigFile, PluginConfigMode, PluginRuntimeValue } from '../api/types'

const props = defineProps<{ plugin: string; disabled: boolean }>()
const emit = defineEmits<{ close: [] }>()
const files = ref<PluginConfigFile[]>([])
const document = ref<PluginConfigDocument | null>(null)
const file = ref(''), loading = ref(false), busy = ref(false), error = ref(''), notice = ref(''), conflict = ref(false)
const drafts = ref<Record<string, string>>({}), selected = ref<Record<string, boolean>>({})
const runtime = ref<Record<string, PluginRuntimeValue>>({}), results = ref<Record<string, PluginApplyResult>>({})
const backup = ref('')
let sequence = 0
const changed = computed(() => document.value?.parameters.some(p => p.editable && drafts.value[p.name] !== p.value) ?? false)
const selectedParameters = computed(() => document.value?.parameters.filter(p => p.editable && selected.value[p.name]) ?? [])
const count = computed(() => selectedParameters.value.length)
const blocked = computed(() => busy.value || loading.value || conflict.value || !count.value || count.value > 20)
const editable = computed(() => document.value?.parameters.filter(p => p.editable) ?? [])

function canLeave() {
  if (busy.value) { notice.value = '正在处理请求，请等待结果后再离开。'; return false }
  return !changed.value || confirm('有尚未保存到配置文件的修改，放弃这些修改？')
}
defineExpose({ canLeave })
function close() { if (canLeave()) emit('close') }
function acceptDocument(value: PluginConfigDocument) {
  document.value = value
  drafts.value = Object.fromEntries(value.parameters.map(p => [p.name, p.value]))
  selected.value = {}
  backup.value = value.backups[0]?.id ?? ''
}
function handleError(e: unknown) {
  conflict.value = e instanceof ApiError && e.status === 409
  error.value = conflict.value
    ? '配置已被其他操作修改。本次草稿仍保留；请先记录需要的值，再重新载入最新配置。'
    : (e as Error).message
}
async function loadFile(name: string) {
  const token = ++sequence
  file.value = name; document.value = null; loading.value = true
  error.value = ''; notice.value = ''; conflict.value = false; runtime.value = {}; results.value = {}
  try {
    const value = await getPluginConfig(props.plugin, name)
    if (token === sequence) acceptDocument(value)
  } catch (e) { if (token === sequence) handleError(e) }
  finally { if (token === sequence) loading.value = false }
}
async function loadFiles() {
  const token = ++sequence
  files.value = []; document.value = null; file.value = ''; loading.value = true; error.value = ''; notice.value = ''
  try {
    const response = await getPluginConfigs(props.plugin)
    if (token !== sequence) return
    files.value = response.files
    const first = response.files[0]
    if (first) await loadFile(first.name)
  } catch (e) { if (token === sequence) handleError(e) }
  finally { if (token === sequence) loading.value = false }
}
function chooseFile(event: Event) {
  const element = event.target as HTMLSelectElement
  if (canLeave()) void loadFile(element.value)
  else element.value = file.value
}
function reload() { if (canLeave()) void (file.value ? loadFile(file.value) : loadFiles()) }
function edit(name: string, event: Event) {
  drafts.value[name] = (event.target as HTMLInputElement).value
  selected.value[name] = true
  delete results.value[name]
}
async function readRuntime() {
  if (busy.value || loading.value || conflict.value || !document.value) return
  const token = sequence
  busy.value = true; error.value = ''; notice.value = '正在读取运行值…'
  const names = editable.value.map(p => p.name)
  try {
    for (let index = 0; index < names.length; index += 20) {
      const response = await getPluginRuntime(props.plugin, file.value, names.slice(index, index + 20))
      if (token !== sequence) return
      for (const item of response.values) runtime.value[item.name] = item
    }
    notice.value = '运行值已读取。读取结果为此刻快照，后续可能被插件、预设或换图覆盖。'
  } catch (e) { if (token === sequence) { handleError(e); notice.value = '读取中断，已显示的值为上次成功读取的快照。' } }
  finally { if (token === sequence) busy.value = false }
}
async function submit(mode: PluginConfigMode) {
  if (blocked.value || !document.value) return
  const token = sequence
  const updates = Object.fromEntries(selectedParameters.value.map(p => [p.name, drafts.value[p.name] ?? p.value]))
  const previousDrafts = { ...drafts.value }, previousSelected = { ...selected.value }
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const response = await updatePluginConfig(props.plugin, file.value, document.value.revision, updates, mode)
    if (token !== sequence) return
    acceptDocument(response.document)
    // Preserve unsubmitted drafts and failed applications even after a successful save.
    for (const p of response.document.parameters) {
      if (!(p.name in updates) || !response.saved) drafts.value[p.name] = previousDrafts[p.name] ?? p.value
      if (!(p.name in updates)) selected.value[p.name] = previousSelected[p.name] ?? false
    }
    for (const name of Object.keys(updates)) delete results.value[name]
    for (const item of response.applied) {
      results.value[item.name] = item
      runtime.value[item.name] = item
      if (item.status !== 'applied') {
        drafts.value[item.name] = updates[item.name] ?? item.requested
        selected.value[item.name] = true
      } else if (!response.saved && drafts.value[item.name] !== response.document.parameters.find(p => p.name === item.name)?.value) {
        selected.value[item.name] = true
      }
    }
    const failed = response.applied.filter(item => item.status === 'error').length
    const adjusted = response.applied.filter(item => item.status === 'adjusted').length
    const applied = response.applied.filter(item => item.status === 'applied').length
    notice.value = response.saved ? '配置已保存。' : '配置文件未修改。'
    if (mode === 'save') notice.value += '运行值未应用，将按插件自身的加载时机生效。'
    else notice.value += `应用结果：${applied} 项一致、${adjusted} 项被调整、${failed} 项失败。${failed || adjusted ? '请检查下方结果，未达到预期的项已保留，可重试。' : ''}`
  } catch (e) { if (token === sequence) handleError(e) }
  finally { if (token === sequence) busy.value = false }
}
async function restore() {
  if (busy.value || loading.value || conflict.value || !document.value || !backup.value) return
  const entry = document.value.backups.find(item => item.id === backup.value)
  if (!entry || !confirm(`恢复 ${formatTime(entry.created)} 的文件备份？当前草稿将被替换；游戏运行值不会改变。`)) return
  const token = sequence
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const response = await restorePluginConfig(props.plugin, file.value, document.value.revision, backup.value)
    if (token !== sequence) return
    acceptDocument(response.document); results.value = {}
    notice.value = '配置文件已恢复，游戏运行值未改变。如需立即生效，请勾选参数后临时应用。'
  } catch (e) { if (token === sequence) handleError(e) }
  finally { if (token === sequence) busy.value = false }
}
function formatTime(value: number) { return new Date(value * 1000).toLocaleString() }
function beforeUnload(event: BeforeUnloadEvent) { if (changed.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
watch(() => props.plugin, loadFiles, { immediate: true })
onBeforeUnmount(() => { sequence++; window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <div class="card config-panel" :aria-busy="busy || loading">
    <h2>插件参数 <code>{{ plugin }}</code><span class="sp" /><button class="g sm" :disabled="busy" @click="close">关闭</button></h2>
    <p class="mu intro">编辑会自动勾选参数，也可勾选已保存的参数进行临时应用。每次最多处理 20 项。</p>
    <div v-if="files.length" class="row config-picker">
      <label for="plugin-config-file">配置文件</label>
      <select id="plugin-config-file" :value="file" :disabled="busy || loading" @change="chooseFile"><option v-for="item in files" :key="item.name" :value="item.name">{{ item.name }}{{ item.source === 'filename' ? '（按文件名匹配）' : '' }}</option></select>
      <button class="g sm" :disabled="busy || loading" @click="reload">重新载入</button>
    </div>
    <p v-if="disabled" class="warning">此插件已禁用；仍可保存配置，运行值读取和临时应用不可用。</p>
    <p v-if="loading" role="status">正在读取配置…</p>
    <div v-if="error" class="error" role="alert">{{ error }} <button v-if="!files.length" class="g sm" :disabled="busy || loading" @click="reload">重试</button></div>
    <p v-if="!loading && !error && !files.length" class="mu">没有找到可关联的配置文件。通用编辑器支持 cfg/sourcemod/ 中带 SourceMod 标准参数注释的配置；自定义数据文件需要插件专用适配。</p>
    <template v-if="document">
      <p v-for="warning in document.warnings" :key="warning" class="warning">{{ warning }}</p>
      <div class="row">
        <span class="mu">{{ document.parameters.length }} 个参数 · {{ editable.length }} 个可编辑 · {{ document.encoding }}</span>
        <span class="sp" /><button class="g sm" :disabled="busy || loading || conflict || disabled || !editable.length" @click="readRuntime">读取运行值</button>
      </div>
      <p v-if="!editable.length" class="mu">没有可安全编辑的标准参数。未标注默认值、重复声明或复杂配置暂时只读。</p>
      <div class="parameter-list">
        <div v-for="(parameter, index) in document.parameters" :key="index + ':' + parameter.name" class="parameter">
          <div class="parameter-heading">
            <label><input v-model="selected[parameter.name]" type="checkbox" :disabled="busy || !parameter.editable" :aria-label="'选择 ' + parameter.name"><code>{{ parameter.name }}</code></label>
            <span v-if="!parameter.editable" class="mu">只读</span>
            <span v-else-if="drafts[parameter.name] !== parameter.value" class="warning">未保存</span>
          </div>
          <p v-if="parameter.description" class="description">{{ parameter.description }}</p>
          <div class="values">
            <div><span class="mu">文件保存值</span><code>{{ parameter.value === '' ? '（空字符串）' : parameter.value }}</code></div>
            <div><span class="mu">运行值</span><span v-if="!runtime[parameter.name]" class="mu">未读取</span><span v-else-if="runtime[parameter.name]?.error" class="error">读取 / 应用失败：{{ runtime[parameter.name]?.error }}</span><code v-else>{{ runtime[parameter.name]?.value === '' ? '（空字符串）' : runtime[parameter.name]?.value ?? '无法确认' }}</code></div>
            <div><span class="mu">默认值</span><code>{{ parameter.default ?? '未声明' }}</code><span class="mu">范围：{{ parameter.min ?? '不限' }} ～ {{ parameter.max ?? '不限' }}</span></div>
          </div>
          <label class="edit-value" :for="'config-value-' + index"><span>设置值</span><input :id="'config-value-' + index" :value="drafts[parameter.name]" :disabled="busy || !parameter.editable" :type="parameter.type === 'number' ? 'number' : 'text'" step="any" :min="parameter.min ?? undefined" :max="parameter.max ?? undefined" @input="edit(parameter.name, $event)"></label>
          <p v-if="parameter.reason" class="mu">{{ parameter.reason }}</p>
          <p v-if="results[parameter.name]" :class="results[parameter.name]?.status === 'applied' ? 'success' : 'warning'" role="status">{{ results[parameter.name]?.status === 'applied' ? '已应用并确认' : results[parameter.name]?.status === 'adjusted' ? '运行值与请求值不同，请检查插件约束或覆盖规则' : '应用失败，草稿已保留' }}</p>
        </div>
      </div>
      <div class="row commands">
        <span class="mu">已选 {{ count }} 项</span>
        <button class="g" :disabled="blocked || disabled" @click="submit('apply')">仅临时应用</button>
        <button class="g" :disabled="blocked" @click="submit('save')">仅保存</button>
        <button :disabled="blocked || disabled" @click="submit('save_apply')">保存并应用</button>
      </div>
      <p v-if="count > 20" class="warning">每次最多处理 20 项，请取消部分勾选，分批提交；未提交的草稿会保留。</p>
      <div v-if="document.backups.length" class="row backups">
        <label for="plugin-config-backup">文件备份</label>
        <select id="plugin-config-backup" v-model="backup" :disabled="busy || loading"><option v-for="entry in document.backups" :key="entry.id" :value="entry.id">{{ formatTime(entry.created) }} · {{ entry.id }}</option></select>
        <button class="g sm" :disabled="busy || loading || conflict || !backup" @click="restore">恢复文件</button>
      </div>
    </template>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    <div class="note">仅临时应用不写文件；仅保存不改变运行值。保存并应用会逐项回读验证，插件、预设或换图仍可能覆盖运行值。恢复备份只恢复文件。</div>
  </div>
</template>

<style scoped>
.config-panel{min-width:0}.intro{margin:0 0 12px}.config-picker select,.backups select{flex:1;min-width:140px;max-width:100%}.parameter-list{display:flex;flex-direction:column;gap:12px;margin:12px 0}.parameter{border:1px solid var(--bd);border-radius:var(--r2);padding:14px;background:var(--inp);min-width:0}.parameter-heading{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.parameter-heading label{min-width:0;color:var(--tx)}.parameter-heading input{width:16px;height:16px;flex:none;accent-color:var(--ac)}.parameter code{white-space:pre-wrap;overflow-wrap:anywhere}.description{white-space:pre-wrap;margin:10px 0;color:var(--mu);font-size:12px}.values{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0}.values>div{display:flex;flex-direction:column;align-items:flex-start;gap:5px;min-width:0}.edit-value{display:flex;gap:12px}.edit-value input{flex:1;max-width:440px;width:100%}.commands{margin-top:12px}.backups{border-top:1px solid var(--bd);padding-top:14px;margin-top:14px}.warning{color:var(--warn);font-size:12px}.error{color:var(--bad2);font-size:12px;overflow-wrap:anywhere}.success{color:var(--ok);font-size:12px}.notice{font-size:13px;line-height:1.6;margin:12px 0 0}.parameter p:last-child{margin-bottom:0}@media(max-width:650px){.values{grid-template-columns:1fr}.commands button{flex:1}.parameter-heading code{font-size:11px}}
</style>
