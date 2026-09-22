<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { cancelWorkshop, changeMap, deleteAddon, getAddons, startWorkshop, startZip, uploadVpk } from '../api/endpoints'
import type { AddonsResponse } from '../api/types'
import JobRow from '../components/JobRow.vue'
import { run, toast } from '../composables/useToast'
import { CAMPAIGNS } from '../data/campaigns'
import { session } from '../stores/session'

const data = ref<AddonsResponse>({ addons: [], jobs: {}, zips: {} })
const map = ref(CAMPAIGNS[0]![0]), wsId = ref(''), upMsg = ref(''), fileEl = ref<HTMLInputElement>()
const customCampaigns = computed(() => data.value.addons.filter(a => a.maps.length))
let timer: ReturnType<typeof setTimeout> | undefined, alive = true

async function load() {
  try { data.value = await getAddons() } catch { return }
  clearTimeout(timer)
  const busy = [...Object.values(data.value.jobs), ...Object.values(data.value.zips)].some(j => j.state === 'running')
  if (busy && alive) timer = setTimeout(load, 3000)    // progress bars while something runs
}
onMounted(load)
onBeforeUnmount(() => { alive = false; clearTimeout(timer) })

async function go(m: string) {
  if (!confirm('切换到 ' + m + '？当前进度会丢失')) return
  await run(() => changeMap(m), '切换中…').catch(() => {})
  setTimeout(() => session.refreshStatus(), 8000)
}
async function workshop() {
  const id = wsId.value.trim(); if (!id) return
  await run(() => startWorkshop(id), '开始下载，完成后自动安装').catch(() => {})
  wsId.value = ''; setTimeout(load, 1500)
}
async function cancel(id: string) { await run(() => cancelWorkshop(id), '正在取消…').catch(() => {}); setTimeout(load, 1500) }
async function del(name: string) {
  if (!confirm('删除 ' + name + '？')) return
  await run(() => deleteAddon(name), '已删除 ' + name).catch(() => {}); void load()
}
async function zip(name: string) {
  let token: string
  try { token = (await startZip(name)).token; toast('开始打包 ' + name + '…'); void load() } catch (e) { toast((e as Error).message, true); return }
  for (let i = 0; i < 200 && alive; i++) {
    await new Promise(r => setTimeout(r, 1500))
    let d: AddonsResponse
    try { d = await getAddons() } catch { return }
    const j = d.zips[token]
    if (!j || j.state === 'running') continue
    void load()
    if (j.state === 'done') { toast('打包完成，开始下载'); window.location.href = '/api/download?token=' + token } else toast('打包失败: ' + j.msg, true)
    return
  }
}
async function uploadFile() {
  const f = fileEl.value?.files?.[0]
  if (!f) { toast('先选择一个 .vpk 文件', true); return }
  upMsg.value = `上传中 ${f.name} (${(f.size / 1048576).toFixed(1)} MB)…`
  try {
    const r = await uploadVpk(f, p => { upMsg.value = `上传中 ${p}% · ${f.name}` })
    upMsg.value = `已安装 ${r.addon.name}（${r.addon.maps.length} 张地图）`; toast('上传完成'); void load()
  } catch (e) { upMsg.value = '失败: ' + (e as Error).message; toast((e as Error).message, true) }
}
</script>

<template>
  <section class="view on">
    <div class="card"><h2>切换地图</h2>
      <div class="row">
        <select v-model="map" style="flex:1;min-width:0">
          <option v-for="m in CAMPAIGNS" :key="m[0]" :value="m[0]">{{ m[1] }} · {{ m[0] }}</option>
          <optgroup v-for="a in customCampaigns" :key="a.name" :label="a.name"><option v-for="m in a.maps" :key="m" :value="m">{{ m }}</option></optgroup>
        </select>
        <button @click="go(map)">切换</button>
      </div>
      <div class="hint">官方 14 个战役 + 已安装的自定义战役。切换会丢失当前进度。</div>
    </div>
    <div class="card"><h2>自定义战役<span class="sp" /><button class="g sm" @click="load">刷新</button></h2>
      <div v-if="session.features?.workshop" class="row"><span class="lbl">工坊</span><input v-model="wsId" placeholder="创意工坊 ID 或链接" style="flex:1;min-width:0" @keydown.enter="workshop"><button @click="workshop">下载安装</button></div>
      <div class="row"><span class="lbl">上传</span><input ref="fileEl" type="file" accept=".vpk" style="flex:1;min-width:0"><button @click="uploadFile">上传</button></div>
      <div class="mu">{{ upMsg }}</div>
      <div style="margin-top:8px">
        <JobRow v-for="(j, id) in data.jobs" :key="'ws' + id" :label="'工坊 ' + id" :job="j"><button v-if="j.state === 'running'" class="g sm" @click="cancel(String(id))">取消</button></JobRow>
        <JobRow v-for="(j, t) in data.zips" :key="'zip' + t" label="打包" :job="j"><a v-if="j.state === 'done'" :href="'/api/download?token=' + t"> — 下载 {{ j.name }}（{{ j.size_mb }} MB）</a></JobRow>
        <div v-if="data.addons.length" class="tw"><table>
          <tr><th>文件</th><th>地图</th><th>大小</th><th /></tr>
          <tr v-for="a in data.addons" :key="a.name">
            <td><b>{{ a.name }}</b><div v-if="a.mission" class="mu">{{ a.mission }}</div></td>
            <td class="mu">{{ a.maps.length ? `${a.maps.length} 张：${a.maps.slice(0, 3).join(', ')}${a.maps.length > 3 ? '…' : ''}` : '—' }}</td>
            <td class="mu">{{ a.size_mb }} MB</td>
            <td class="act">
              <button v-if="a.maps.length" class="sm" @click="go(a.maps[0]!)">切到第一章</button>
              <button class="g sm" @click="zip(a.name)">打包下载</button>
              <button v-if="!a.protected" class="d sm" @click="del(a.name)">删除</button>
            </td>
          </tr>
        </table></div>
        <div v-else class="mu">还没有自定义战役</div>
      </div>
      <div class="hint">装完自动热加载，不用重启。玩家客户端也要订阅同一个创意工坊物品，否则进不了自定义战役。</div>
    </div>
  </section>
</template>
