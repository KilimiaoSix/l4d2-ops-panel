<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { editWhitelist, enableWhitelist, getWhitelist, givePoints, kick } from '../api/endpoints'
import type { Player } from '../api/types'
import AppOverlay from '../components/AppOverlay.vue'
import Switch from '../components/Switch.vue'
import { run } from '../composables/useToast'
import { session } from '../stores/session'

const wl = ref<string[]>([])
const showWhitelist = ref(false), pointPlayer = ref<Player | null>(null), pointAmount = ref(200), pointBusy = ref(false), pointError = ref(''), wlBusy = ref(false)
function openPoints(player: Player) { pointPlayer.value = player; pointAmount.value = 200; pointError.value = '' }
const wlId = ref(''), wlNote = ref('')
const wlOn = computed(() => session.status?.whitelist ?? null)
const wlState = computed(() => wlOn.value === null ? '未知（服务器离线）' : wlOn.value ? '已开启：仅名单内可进' : '已关闭：所有人可进')
const entries = computed(() => wl.value.map(x => { const [id = '', ...rest] = x.split(/\s+/); return { id, note: rest.join(' ').replace(/^\/\/\s*/, '') } }))

async function loadWl() { try { wl.value = (await getWhitelist()).list } catch { /* offline */ } }
onMounted(loadWl)

async function toggle() {
  if (wlOn.value === null) return
  if (wlBusy.value) return
  const v = !wlOn.value
  if (!v && !confirm('关闭白名单后任何人都能进服，确定？')) return
  wlBusy.value = true
  try {
    await run(() => enableWhitelist(v), v ? '白名单已开启' : '白名单已关闭，现在所有人可进')
    if (session.status) session.status.whitelist = v
  } catch { /* toasted */ } finally { wlBusy.value = false }
}
async function add(id = wlId.value.trim(), note = wlNote.value) {
  if (!id || wlBusy.value) return
  wlBusy.value = true
  try { const d = await run(() => editWhitelist('add', id, note), '已加入白名单：' + (note || id)); wl.value = d.list; wlId.value = ''; wlNote.value = '' } catch { /* toasted */ } finally { wlBusy.value = false }
}
async function del(id: string) {
  if (wlBusy.value) return
  if (!confirm('从白名单删除 ' + id + '？')) return
  wlBusy.value = true
  try { wl.value = (await run(() => editWhitelist('del', id))).list } catch { /* toasted */ } finally { wlBusy.value = false }
}
async function give() {
  if (pointBusy.value || !pointPlayer.value) return
  if (!Number.isFinite(pointAmount.value) || !pointAmount.value) { pointError.value = '请输入有效分数'; return }
  pointBusy.value = true; pointError.value = ''
  try { await run(() => givePoints('#' + pointPlayer.value!.userid, pointAmount.value), '已发放'); pointPlayer.value = null }
  catch (e) { pointError.value = (e as Error).message }
  finally { pointBusy.value = false }
}
async function kickPlayer(p: Player) {
  if (!confirm('踢出 ' + p.name + '？')) return
  await run(() => kick(p.userid), '已踢出').catch(() => {})
  setTimeout(() => session.refreshPlayers(), 1500)
}
</script>

<template>
  <section class="view on">
    <div v-if="session.features?.whitelist" class="page-actions"><span class="mu">白名单{{ wlOn === null ? '状态未知' : wlOn ? '已开启' : '已关闭' }} · {{ wl.length }} 人</span><button class="g" @click="showWhitelist = true">管理白名单</button></div>
    <div class="card"><h2>在线玩家 <span class="mu">{{ session.players.length }} 人</span><span class="sp" /><button class="g sm" @click="session.refreshPlayers()">刷新</button></h2>
      <div class="tw"><table>
        <tr><th>名字</th><th>在线</th><th>延迟</th><th /></tr>
        <tr v-for="p in session.players" :key="p.userid">
          <td><b>{{ p.name }}</b><div><code class="mu">{{ p.steamid }}</code></div></td><td class="mu">{{ p.time }}</td><td class="mu">{{ p.ping }} ms</td>
          <td class="act">
            <button v-if="session.features?.points" class="g sm" @click="openPoints(p)">发分</button>
            <button v-if="session.features?.whitelist" class="g sm" :disabled="wlBusy" @click="add(p.steamid, p.name)">加白</button>
            <button class="d sm" @click="kickPlayer(p)">踢</button>
          </td>
        </tr>
        <tr v-if="!session.players.length"><td colspan="4" class="mu">当前没有玩家</td></tr>
      </table></div>
    </div>
    <AppOverlay :open="showWhitelist" title="管理白名单" :description="wl.length + ' 人在名单中'" kind="drawer" :busy="wlBusy" @close="showWhitelist = false">
      <div class="row" style="margin-bottom:6px"><Switch :on="wlOn" :disabled="wlBusy" label="白名单开关" @toggle="toggle" /><span class="mu">{{ wlState }}</span></div>
      <div class="hint" style="margin:0 0 12px">开启 = 只有名单里的人和管理员能进；关闭 = 任何人都能进（临时给朋友开门时用，加完人记得开回来）。</div>
      <form class="form-stack" @submit.prevent="add()"><label>SteamID 或个人主页链接<input v-model="wlId" placeholder="SteamID / 主页链接 / 17 位好友码" required :disabled="wlBusy"></label><label>备注（可选）<input v-model="wlNote" placeholder="方便辨认的玩家名" :disabled="wlBusy"></label><div><button type="submit" :disabled="wlBusy">{{ wlBusy ? '处理中…' : '添加到白名单' }}</button></div></form>
      <div class="drawer-section"><h3>白名单成员</h3><p v-if="!entries.length" class="mu">名单为空，当前对所有人开放。</p></div>
      <div>
        <div v-for="e in entries" :key="e.id" class="wl"><span><code>{{ e.id }}</code> <span class="mu">{{ e.note }}</span></span><button class="g sm" :disabled="wlBusy" @click="del(e.id)">删除</button></div>
      </div>
    </AppOverlay>
    <AppOverlay :open="!!pointPlayer" title="发放积分" :description="pointPlayer?.name" :busy="pointBusy" @close="pointPlayer = null">
      <form id="player-points" class="form-stack" @submit.prevent="give"><label>积分数量<input v-model.number="pointAmount" type="number" required :disabled="pointBusy"></label><p v-if="pointError" role="alert" class="form-error">{{ pointError }}</p></form>
      <template #footer><button class="g" :disabled="pointBusy" @click="pointPlayer = null">取消</button><button type="submit" form="player-points" :disabled="pointBusy">{{ pointBusy ? '发放中…' : '确认发放' }}</button></template>
    </AppOverlay>
  </section>
</template>
