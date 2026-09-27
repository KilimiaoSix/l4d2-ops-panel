<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { getBasicRuntime, getBasicSettings, recoverBasicSettings, saveBasicSettings } from '../api/basic'
import { api } from '../api/client'
import { getOnboarding } from '../api/panel'
import type { BasicFieldResult, BasicOverview } from '../api/types'

const props = defineProps<{ persistDraft?: boolean }>()
const emit = defineEmits<{ saved: [] }>()
const doc = ref<BasicOverview | null>(null), busy = ref(false), error = ref('')
const form = reactive({ server_name: '', ascii_fallback: 'L4D2 Server', region: 255, coop_players: 4 })
const passwordMode = ref('keep'), password = ref(''), results = ref<Record<string, BasicFieldResult>>({})
const draftState = ref('')
const bytes = computed(() => new TextEncoder().encode(form.server_name.trim().normalize('NFC')).length)
const labels: Record<string, string> = { server_name: '服务器名称', ascii_fallback: '备用名称', password: '进服密码', region: '地区', coop_players: '合作人数' }
const states: Record<string, string> = { saved: '已保存', applied: '已确认生效', verified: '已读取运行值', unverified: '运行未确认', error: '应用失败', restart_required: '需要重启游戏' }
const regions: Record<number, string> = { 0: '美国东部', 1: '美国西部', 2: '南美洲', 3: '欧洲', 4: '亚洲', 5: '澳大利亚', 6: '中东', 7: '非洲', 255: '其他 / 未指定' }
let alive = true, generation = 0, draftQueue: Promise<unknown> = Promise.resolve()
async function load(useDraft = false) {
  const rev = ++generation
  try {
    const value = await getBasicSettings()
    if (!alive || rev !== generation) return
    doc.value = value
    if (value.fields) {
      for (const key of ['server_name', 'ascii_fallback', 'region', 'coop_players'] as const) Object.assign(form, { [key]: value.fields[key] })
      password.value = ''; passwordMode.value = 'keep'
    }
    if (useDraft && props.persistDraft) {
        const { draft } = await getOnboarding()
        if (!alive || rev !== generation) return
        if (typeof draft.server_name === 'string') form.server_name = draft.server_name
        if (typeof draft.region === 'number') form.region = draft.region
        if (typeof draft.coop_players === 'number') form.coop_players = draft.coop_players
    }
  } catch (e) { if (alive && rev === generation) error.value = (e as Error).message }
}
function draft() {
  if (!props.persistDraft || !form.server_name.trim() || bytes.value > 96) return
  const value = { server_name: form.server_name.trim().normalize('NFC'), region: Number(form.region), coop_players: Number(form.coop_players) }
  draftState.value = '正在保存非秘密草稿…'
  draftQueue = draftQueue.catch(() => {}).then(() => api('/api/onboarding', { draft: value }))
    .then(() => { if (alive) draftState.value = '非秘密草稿已保存，刷新后可继续' })
    .catch(e => { if (alive) { draftState.value = ''; error.value = '草稿未保存：' + (e as Error).message } })
}
async function save(mode: 'save' | 'save_apply') {
  if (!doc.value?.fields || busy.value) return
  busy.value = true; error.value = ''; const rev = ++generation
  const values: Record<string, string | number> = { server_name: form.server_name.trim().normalize('NFC'), ascii_fallback: form.ascii_fallback, region: Number(form.region) }
  if (doc.value.fields.game_mode === 'coop' && (doc.value.multiplayer_available || form.coop_players !== 4)) values.coop_players = Number(form.coop_players)
  if (passwordMode.value !== 'keep') values.password = passwordMode.value === 'clear' ? '' : password.value
  try {
    await draftQueue
    const response = await saveBasicSettings(doc.value.fields.revision, mode, values)
    if (!alive || rev !== generation) return
    results.value = response.fields
    await load(); emit('saved')
  } catch (e) { if (alive && rev === generation) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
async function applySaved() {
  if (!doc.value?.fields || busy.value) return
  busy.value = true; error.value = ''; const rev = ++generation
  const values: Record<string, string | number> = { server_name: doc.value.fields.server_name, region: doc.value.fields.region }
  if (doc.value.multiplayer_available && doc.value.fields.game_mode === 'coop') values.coop_players = doc.value.fields.coop_players
  try {
    const response = await saveBasicSettings(doc.value.fields.revision, 'apply', values)
    if (!alive || rev !== generation) return
    results.value = response.fields
    const latest = await getBasicSettings()
    if (!alive || rev !== generation) return
    if (doc.value) doc.value.restart_required = latest.restart_required
    emit('saved')
  } catch (e) { if (alive && rev === generation) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
async function probe() {
  if (busy.value) return
  busy.value = true; error.value = ''; const rev = ++generation
  try {
    const response = await getBasicRuntime(['server_name', 'region', ...(doc.value?.multiplayer_available ? ['coop_players'] : [])])
    if (!alive || rev !== generation) return
    results.value = response.fields
    const latest = await getBasicSettings()
    if (!alive || rev !== generation) return
    if (doc.value) doc.value.restart_required = latest.restart_required
    emit('saved')
  } catch (e) { if (alive && rev === generation) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
async function recover() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await recoverBasicSettings(); if (alive) await load() }
  catch (e) { if (alive) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
onMounted(() => load(true))
onBeforeUnmount(() => { alive = false; generation++ })
</script>

<template>
  <div class="card basic-settings">
    <h2>服务器基础设置<span class="sp" /><button class="g sm" :disabled="busy" @click="load()">重新读取</button></h2>
    <p>保存会保留设置；应用会检查当前游戏。调整人数需要完整重启游戏。</p>
    <p v-if="error || doc?.config_error" role="alert" class="hint">{{ error || doc?.config_error }}</p>
    <p v-if="!doc">正在读取基础设置…</p>
    <template v-else-if="!doc.game_installed">
      <p>先<RouterLink to="/server">安装游戏</RouterLink>，再应用基础设置。</p>
      <fieldset v-if="persistDraft">
        <label>计划使用的服务器名称<input v-model="form.server_name" @input="draft" autocomplete="off"><span class="mu">{{ bytes }} / 96 UTF-8 字节</span></label>
        <label>计划使用的地区<select v-model="form.region" @change="draft"><option v-for="(name, id) in regions" :key="id" :value="Number(id)">{{ name }}</option></select></label>
        <p class="mu">这里仅保存向导草稿，不会创建游戏目录。游戏安装后再设置进服密码。</p>
      </fieldset>
      <p v-if="draftState" class="mu" role="status">{{ draftState }}</p>
    </template>
    <template v-else-if="doc.fields">
      <div v-if="doc.fields.pending" role="alert" class="hint">上次保存没有完成。请在服务器页停止游戏，然后恢复配置。<button class="g sm" :disabled="busy" @click="recover">恢复未完成的保存</button></div>
      <fieldset :disabled="busy || doc.fields.pending">
        <label>服务器名称<input v-model="form.server_name" @input="draft" autocomplete="off"><span class="mu">{{ bytes }} / 96 UTF-8 字节，中文通常占 3 字节。</span></label>
        <label>ASCII 备用名称<input v-model="form.ascii_fallback" maxlength="96"><span class="mu">中文名称插件未加载时，游戏使用这个名称。</span></label>
        <label>进服密码<select v-model="passwordMode"><option value="keep">保持现状{{ doc.fields.password_set ? '（已设置）' : '（未设置）' }}</option><option value="set">设置新密码</option><option value="clear">清除密码</option></select></label>
        <label v-if="passwordMode === 'set'">新的进服密码<input v-model="password" type="password" autocomplete="new-password" maxlength="64"><span class="mu">需要更新后的最小插件包。朋友使用加入说明中的 setinfo 命令；密码不会保存在向导草稿或分享文本中。</span></label>
        <label>服务器地区<select v-model="form.region" @change="draft"><option v-for="(name, id) in regions" :key="id" :value="Number(id)">{{ name }}</option></select></label>
        <label>合作人数<input v-model.number="form.coop_players" type="number" min="4" max="12" step="1" :disabled="!doc.multiplayer_available || doc.fields.game_mode !== 'coop'" @change="draft"><span class="mu">普通合作支持 4–12 人；额外槽位也为特感和 Tank 留出空间。</span></label>
        <p v-if="!doc.multiplayer_available" class="mu">当前使用原生四人配置。<RouterLink to="/plugins">安装多人合作包</RouterLink>后可调整人数。</p>
        <p v-if="doc.fields.game_mode !== 'coop'" class="hint">当前保存模式为 {{ doc.fields.game_mode }}。合作人数仅用于普通 coop 模式。</p>
        <div class="row"><button :disabled="!bytes || bytes > 96" @click="save('save_apply')">保存并应用</button><button class="g" :disabled="!bytes || bytes > 96" @click="save('save')">仅保存</button><button class="g" @click="applySaved">应用已保存值</button><button class="g" @click="probe">检查运行值</button></div>
      </fieldset>
      <p v-if="draftState" class="mu" role="status">{{ draftState }}</p>
      <p v-if="doc.restart_required" role="status" class="hint">人数设置已保存，仍需完整重启游戏。<RouterLink to="/server">前往服务器页</RouterLink>，重启后返回检查运行值。</p>
      <ul v-if="Object.keys(results).length" aria-live="polite"><li v-for="(field, key) in results" :key="key"><strong>{{ labels[key] || key }}</strong>：{{ states[field.state] }}{{ field.saved ? '（文件已保存）' : '' }}。{{ field.message }}<span v-if="field.value != null"> 当前：{{ field.value }}</span><span v-if="field.actual != null"> 当前：{{ field.actual }}</span><span v-if="field.values"> 玩家上限 {{ field.values.sv_maxplayers ?? '未知' }}，生还者上限 {{ field.values.l4d_multislots_max_survivors ?? '未知' }}，引擎槽位 {{ field.values.sv_setmax ?? '未知' }}。</span></li></ul>
      <p class="mu">密码被游戏隐藏时只能确认保存及命令发送，需用客户端验证。面板能读取游戏状态不代表朋友已能从公网加入。</p>
    </template>
  </div>
</template>

<style scoped>
fieldset { border: 0; padding: 0; margin: 18px 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
label { display: flex; flex-direction: column; gap: 8px; }
label input, label select { width: 100%; box-sizing: border-box; }
fieldset p, fieldset .row { grid-column: 1 / -1; }
li { margin: 8px 0; }
@media (max-width: 700px) { fieldset { grid-template-columns: 1fr; } }
</style>
