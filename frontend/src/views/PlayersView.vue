<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { editWhitelist, enableWhitelist, getWhitelist, givePoints, kick } from '../api/endpoints'
import type { Player } from '../api/types'
import Switch from '../components/Switch.vue'
import { run } from '../composables/useToast'
import { session } from '../stores/session'

const wl = ref<string[]>([])
const wlId = ref(''), wlNote = ref('')
const wlOn = computed(() => session.status?.whitelist ?? null)
const wlState = computed(() => wlOn.value === null ? '未知（服务器离线）' : wlOn.value ? '已开启：仅名单内可进' : '已关闭：所有人可进')
const entries = computed(() => wl.value.map(x => { const [id = '', ...rest] = x.split(/\s+/); return { id, note: rest.join(' ').replace(/^\/\/\s*/, '') } }))

async function loadWl() { try { wl.value = (await getWhitelist()).list } catch { /* offline */ } }
onMounted(loadWl)

async function toggle() {
  if (wlOn.value === null) return
  const v = !wlOn.value
  if (!v && !confirm('关闭白名单后任何人都能进服，确定？')) return
  await run(() => enableWhitelist(v), v ? '白名单已开启' : '白名单已关闭，现在所有人可进')
  if (session.status) session.status.whitelist = v
}
async function add(id = wlId.value.trim(), note = wlNote.value) {
  try { const d = await run(() => editWhitelist('add', id, note), '已加入白名单：' + (note || id)); wl.value = d.list; wlId.value = '' } catch { /* toasted */ }
}
async function del(id: string) {
  if (!confirm('从白名单删除 ' + id + '？')) return
  try { wl.value = (await run(() => editWhitelist('del', id))).list } catch { /* toasted */ }
}
async function give(p: Player) {
  const a = prompt('给 ' + p.name + ' 发多少分？', '200')
  if (a) await run(() => givePoints(p.name, +a), '已发放').catch(() => {})
}
async function kickPlayer(p: Player) {
  if (!confirm('踢出 ' + p.name + '？')) return
  await run(() => kick(p.userid), '已踢出').catch(() => {})
  setTimeout(() => session.refreshPlayers(), 1500)
}
</script>

<template>
  <section class="view on"><div class="grid pl" :class="{ nowl: !session.features?.whitelist }">
    <div class="card"><h2>在线玩家<span class="sp" /><button class="g sm" @click="session.refreshPlayers()">刷新</button></h2>
      <div class="tw"><table>
        <tr><th>名字</th><th>在线</th><th>延迟</th><th /></tr>
        <tr v-for="p in session.players" :key="p.userid">
          <td><b>{{ p.name }}</b><div><code class="mu">{{ p.steamid }}</code></div></td><td class="mu">{{ p.time }}</td><td class="mu">{{ p.ping }} ms</td>
          <td class="act">
            <button class="g sm" @click="give(p)">发分</button>
            <button class="g sm" @click="add(p.steamid, p.name)">加白</button>
            <button class="d sm" @click="kickPlayer(p)">踢</button>
          </td>
        </tr>
        <tr v-if="!session.players.length"><td colspan="4" class="mu">当前没有玩家</td></tr>
      </table></div>
    </div>
    <div v-if="session.features?.whitelist" class="card"><h2>白名单<span class="sp" /><span class="mu">{{ wl.length ? wl.length + ' 人' : '空 = 对所有人开放' }}</span></h2>
      <div class="row" style="margin-bottom:6px"><Switch :on="wlOn" label="白名单开关" @toggle="toggle" /><span class="mu">{{ wlState }}</span></div>
      <div class="hint" style="margin:0 0 12px">开启 = 只有名单里的人和管理员能进；关闭 = 任何人都能进（临时给朋友开门时用，加完人记得开回来）。</div>
      <div class="row"><input v-model="wlId" placeholder="SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:150px" @keydown.enter="add()"><input v-model="wlNote" placeholder="备注" style="width:90px"><button @click="add()">添加</button></div>
      <div>
        <div v-for="e in entries" :key="e.id" class="wl"><span><code>{{ e.id }}</code> <span class="mu">{{ e.note }}</span></span><button class="g sm" @click="del(e.id)">删除</button></div>
      </div>
    </div>
  </div></section>
</template>
