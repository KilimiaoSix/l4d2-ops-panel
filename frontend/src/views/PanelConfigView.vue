<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getPanelConfig, savePanelConfig } from '../api/panel'
import type { PanelConfiguration, PanelValue } from '../api/types'
import { toast } from '../composables/useToast'
import { panelRestart } from '../stores/restart'
import { session } from '../stores/session'

const info = ref<PanelConfiguration | null>(null), form = ref<Record<string, PanelValue>>({})
const secretChanged = ref<Record<string, boolean>>({}), error = ref(''), busy = ref(false), confirmRestart = ref(false)
let alive = true, requestRevision = 0
const basic = ['panel_title', 'display_host', 'max_upload_mb', 'steam_api_key']
const labels: Record<string, string> = {
  panel_title: '面板名称', display_host: '朋友连接地址', max_upload_mb: '上传上限（MB）', steam_api_key: 'Steam API Key',
  port: '面板端口', bind: '监听 IP', tls: '启用 HTTPS', cert: '证书路径', key: '私钥路径', session_days: '登录有效期（天）',
  game_dir: '游戏目录', install_dir: 'Docker 管理目录', rcon_host: 'RCON 地址', rcon_port: 'RCON 端口',
  rcon_password: 'RCON 密码', lgsm_script: 'LinuxGSM 脚本', console_log: '控制台日志路径', perf_csv: '性能日志路径', depotdownloader: 'DepotDownloader 路径',
}
const advanced = computed(() => Object.keys(info.value?.fields || {}).filter(key => !basic.includes(key)))
const groups = computed(() => [basic, advanced.value])
const updates = computed(() => Object.fromEntries(Object.entries(form.value).filter(([key, value]) => {
  const field = info.value?.fields[key]
  return field?.editable && ('set' in field ? secretChanged.value[key] : field.value !== value)
})))
const needsRestart = computed(() => Object.keys(updates.value).some(key => info.value?.fields[key]?.effect === 'restart'))
const reverseProxy = computed(() => !!info.value && (Number(location.port || (location.protocol === 'https:' ? 443 : 80)) !== info.value.fields.port?.value || (location.protocol === 'https:') !== info.value.fields.tls?.value))
const nextUrl = computed(() => {
  const url = new URL(location.href)
  if (!reverseProxy.value) {
    url.protocol = form.value.tls ? 'https:' : 'http:'
    url.port = String(form.value.port)
    const bind = String(form.value.bind)
    if (!['0.0.0.0', '::', '127.0.0.1', '::1'].includes(bind) && bind !== String(info.value?.fields.bind?.value)) url.hostname = bind
  }
  url.hash = '/panel?restarted=1'
  return url.href
})
async function load() {
  const rev = ++requestRevision
  busy.value = true; error.value = ''; confirmRestart.value = false
  try {
    const result = await getPanelConfig()
    if (!alive || rev !== requestRevision) return
    info.value = result; secretChanged.value = {}
    form.value = Object.fromEntries(Object.entries(result.fields).map(([key, field]) => [key, field.value ?? '']))
  } catch (e) { if (alive && rev === requestRevision) error.value = (e as Error).message }
  finally { if (alive && rev === requestRevision) busy.value = false }
}
async function save(confirmed = false) {
  if (!info.value || busy.value || !Object.keys(updates.value).length) return
  if (needsRestart.value && !confirmed) { confirmRestart.value = true; return }
  const destination = nextUrl.value, rev = ++requestRevision
  busy.value = true; error.value = ''
  try {
    const result = await savePanelConfig(info.value.revision, updates.value, confirmed)
    if (!alive || rev !== requestRevision) return
    if (result.restart_scheduled) { panelRestart.start(result, destination); return }
    toast(result.saved ? '面板设置已保存并生效' : '没有需要保存的变更')
    await session.refreshStatus(); await load()
  } catch (e) { if (alive && rev === requestRevision) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { alive = false; requestRevision++ })
</script>

<template>
  <section class="view on">
    <div v-if="session.role !== 'owner'" class="card">面板配置仅限 owner 修改。</div>
    <template v-else>
      <div class="card">
        <h2>面板设置<span class="sp" /><button class="g sm" :disabled="busy" @click="load">重新读取</button></h2>
        <p class="mu">名称、连接地址、上传上限和 Steam Key 保存后立即生效。</p>
        <p v-if="error" role="alert" class="hint">{{ error }}</p>
        <p v-if="!info">正在读取面板配置…</p>
        <template v-if="info">
          <component :is="index ? 'details' : 'div'" v-for="(group, index) in groups" :key="index" class="field-group">
            <summary v-if="index">高级设置 · 保存后重启面板</summary>
            <p v-if="index && !info.supervised" class="note">当前通过命令行运行。高级配置需要先使用 l4d2panel systemd 服务启动。</p>
            <div v-for="key in group" :key="key" class="config-field">
              <label :for="'panel-' + key">{{ labels[key] || key }}</label>
              <input v-if="key === 'tls'" :id="'panel-' + key" v-model="form[key]" type="checkbox" :disabled="busy || !info.fields[key]?.editable">
              <input v-else :id="'panel-' + key" v-model="form[key]" :type="'set' in (info.fields[key] || {}) ? 'password' : typeof info.fields[key]?.value === 'number' ? 'number' : 'text'"
                :disabled="busy || !info.fields[key]?.editable" :autocomplete="'set' in (info.fields[key] || {}) ? 'new-password' : 'off'"
                :placeholder="'set' in (info.fields[key] || {}) ? (info.fields[key]?.set ? '已设置；留空保持原值' : '尚未设置') : ''"
                @input="secretChanged[key] = true; confirmRestart = false">
              <button v-if="'set' in (info.fields[key] || {})" class="g sm" :disabled="busy || !info.fields[key]?.editable" @click="form[key] = ''; secretChanged[key] = true">清除</button>
              <small v-if="info.fields[key]?.locked_reason" class="mu">{{ info.fields[key]?.locked_reason }}</small>
              <small v-if="key === 'display_host'" class="mu">域名或 IP，可带游戏端口，例如 play.example.com:27015。</small>
            </div>
          </component>
          <div v-if="confirmRestart" class="hint" role="alert">
            <p>这次修改需要重启面板，约几秒到一分钟。游戏进程会继续运行。</p>
            <p>恢复后访问：<code>{{ nextUrl }}</code></p>
            <p v-if="reverseProxy">当前可能经过反向代理。请先确认代理上游端口、协议与新设置一致。</p>
            <p v-if="['127.0.0.1', '::1'].includes(String(form.bind))">监听本机地址时，远程访问需要反向代理或 SSH 隧道。</p>
            <button :disabled="busy || !info.supervised" @click="save(true)">确认保存并重启</button>
            <button class="g" :disabled="busy" @click="confirmRestart = false">返回修改</button>
          </div>
          <div v-else class="row"><button :disabled="busy || !Object.keys(updates).length || (needsRestart && !info.supervised)" @click="save()">{{ busy ? '正在保存…' : needsRestart ? '检查并重启' : '保存设置' }}</button></div>
          <details class="note"><summary>配置与恢复</summary><p>{{ info.config_path }}</p><p>修改前会保存私有备份。启动失败时自动尝试恢复；也可运行 <code>sudo l4d2panel-recover</code>。</p></details>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.field-group { margin: 18px 0; }
summary { cursor: pointer; padding: 6px 0; }
.config-field { display: grid; grid-template-columns: 170px minmax(130px, 1fr) auto; align-items: center; gap: 10px; margin: 14px 0; }
.config-field input { min-width: 0; width: 100%; }
.config-field input[type=checkbox] { width: auto; justify-self: start; }
.config-field small { grid-column: 2 / -1; }
code { overflow-wrap: anywhere; }
@media (max-width: 600px) { .config-field { grid-template-columns: 1fr auto; } .config-field label { grid-column: 1 / -1; } .config-field small { grid-column: 1 / -1; } }
</style>
