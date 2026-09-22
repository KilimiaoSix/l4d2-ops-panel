<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { cancelWorkshop, changeMap, deleteAddon, getAddons, startWorkshop, startZip, uploadCampaign, workshopSearch } from '../api/endpoints'
import type { AddonsResponse, WorkshopItem } from '../api/types'
import JobRow from '../components/JobRow.vue'
import { run, toast } from '../composables/useToast'
import { CAMPAIGNS } from '../data/campaigns'
import { session } from '../stores/session'

const data = ref<AddonsResponse>({ addons: [], jobs: {}, zips: {} })
const map = ref(CAMPAIGNS[0]![0]), wsId = ref(''), upMsg = ref(''), fileEl = ref<HTMLInputElement>()
const tab = ref<'ws' | 'up' | 'search'>('ws')   // 安装新战役: which install method is showing
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
  if (!f) { toast('先选择一个 .vpk 或 .zip 文件', true); return }
  upMsg.value = `上传中 ${f.name} (${(f.size / 1048576).toFixed(1)} MB)…`
  try {
    const r = await uploadCampaign(f, p => { upMsg.value = p < 100 ? `上传中 ${p}% · ${f.name}` : `已上传，正在检查并安装 ${f.name}…` })
    upMsg.value = '已安装 ' + r.installed.map(a => `${a.name}（${a.maps.length} 张地图）`).join('、') + (r.skipped.length ? '；跳过：' + r.skipped.map(s => s.reason).join('；') : '')
    toast('上传完成' + (r.skipped.length ? `，有 ${r.skipped.length} 个文件被拒收` : ''), !!r.skipped.length); void load()
  } catch (e) { upMsg.value = '失败: ' + (e as Error).message; toast((e as Error).message, true) }
}

// ---- Workshop search: campaigns only, paged; "安装" hands the id to the download job above ----
const wsQuery = ref(''), wsItems = ref<WorkshopItem[]>([]), wsTotal = ref(0), wsPage = ref(1), wsMsg = ref(''), wsStarted = ref(new Set<string>())
let wsTerm = ''
async function search(more = false) {
  if (more) wsPage.value++
  else { wsTerm = wsQuery.value.trim(); wsPage.value = 1; wsItems.value = []; wsMsg.value = '搜索中…' }
  try {
    const d = await workshopSearch(wsTerm, wsPage.value)
    wsItems.value = wsItems.value.concat(d.items); wsTotal.value = d.total; wsMsg.value = wsItems.value.length ? '' : '没有找到相关战役'
  } catch (e) { if (!more) wsMsg.value = (e as Error).message; toast((e as Error).message, true) }
}
async function installFromSearch(id: string) {
  wsStarted.value.add(id)
  try { await run(() => startWorkshop(id), '开始下载，完成后自动安装'); setTimeout(load, 1500) } catch { wsStarted.value.delete(id) }
}
const day = (t: number) => t ? new Date(t * 1000).toLocaleDateString() : '—'
</script>

<template>
  <section class="view on">
    <div class="card tool"><h2>切换地图</h2>
      <select v-model="map">
        <option v-for="m in CAMPAIGNS" :key="m[0]" :value="m[0]">{{ m[1] }} · {{ m[0] }}</option>
        <optgroup v-for="a in customCampaigns" :key="a.name" :label="a.name"><option v-for="m in a.maps" :key="m" :value="m">{{ m }}</option></optgroup>
      </select>
      <button @click="go(map)">切换</button>
      <span class="mu">官方 14 个战役 + 已安装的自定义战役；切换会丢失当前进度</span>
    </div>
    <div class="card"><h2>安装新战役<span class="sp" />
      <span class="tabs">
        <button v-if="session.features?.workshop" :class="{ on: tab === 'ws' }" @click="tab = 'ws'">工坊 ID / 链接</button>
        <button :class="{ on: tab === 'up' }" @click="tab = 'up'">上传 vpk / zip</button>
        <button v-if="session.features?.workshop_search" :class="{ on: tab === 'search' }" @click="tab = 'search'">搜索创意工坊</button>
      </span></h2>
      <div class="mt" :class="{ on: tab === 'ws' }">
        <div class="row"><input v-model="wsId" placeholder="创意工坊 ID 或链接" style="flex:1;min-width:0" @keydown.enter="workshop"><button @click="workshop">下载安装</button></div>
        <div class="note">直连 Steam CDN 分块下载，完成后自动安装、热加载，不用重启；玩家客户端也要订阅同一个创意工坊物品，否则进不了自定义战役。</div>
      </div>
      <div class="mt" :class="{ on: tab === 'up' }">
        <div class="row"><input ref="fileEl" type="file" accept=".vpk,.zip" style="flex:1;min-width:0"><button @click="uploadFile">上传</button></div>
        <div class="mu">{{ upMsg }}</div>
        <div class="note">zip（例如 gamemaps.com 下载的压缩包）会自动解压出里面的 vpk；不含地图（maps/*.bsp）的 vpk 一律拒收。</div>
      </div>
      <div class="mt" :class="{ on: tab === 'search' }">
        <div class="row"><input v-model="wsQuery" placeholder="战役名或关键字，留空 = 订阅最多的战役" style="flex:1;min-width:0" @keydown.enter="search()"><button @click="search()">搜索</button></div>
        <div style="margin-top:8px">
          <div v-if="wsMsg" class="mu">{{ wsMsg }}</div>
          <div v-if="wsItems.length" class="tw"><table>
            <tr><th /><th>战役</th><th>大小</th><th>订阅</th><th>更新</th><th /></tr>
            <tr v-for="i in wsItems" :key="i.id">
              <td><img v-if="i.preview" class="thumb" :src="i.preview" alt="" loading="lazy" @error="($event.target as HTMLImageElement).style.display = 'none'"></td>
              <td><b>{{ i.title }}</b><div class="mu">{{ i.tags.join(' · ') }}{{ i.desc ? (i.tags.length ? ' — ' : '') + i.desc : '' }}</div><code class="mu">{{ i.id }}</code></td>
              <td class="mu">{{ i.size_mb }} MB</td><td class="mu">{{ i.subs.toLocaleString() }}</td><td class="mu">{{ day(i.updated) }}</td>
              <td class="act"><button class="sm" :disabled="wsStarted.has(i.id)" @click="installFromSearch(i.id)">{{ wsStarted.has(i.id) ? '已开始下载' : '安装' }}</button></td>
            </tr>
          </table></div>
          <div v-if="wsItems.length && wsItems.length < wsTotal" class="row"><button class="g sm" @click="search(true)">加载更多</button><span class="mu">已显示 {{ wsItems.length }} / {{ wsTotal }}</span></div>
        </div>
        <div class="note">只列出带 Campaigns 标签的物品；点“安装”走工坊下载通道，装前同样检查 vpk 里有没有地图。</div>
      </div>
    </div>
    <div class="card"><h2>已安装的自定义战役<span class="sp" /><button class="g sm" @click="load">刷新</button></h2>
      <div>
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
      <div class="note">切到第一章会丢失当前进度；打包下载 = 把 vpk 压成 zip 给玩家手动安装；受保护的 vpk 不提供删除。</div>
    </div>
  </section>
</template>
