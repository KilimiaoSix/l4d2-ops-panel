<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { givePoints, setDamage, setDifficulty, setPreset } from '../api/endpoints'
import { run, toast } from '../composables/useToast'
import { DIFFICULTY_NAMES, PRESETS } from '../data/campaigns'
import { session } from '../stores/session'
import GameModePanel from '../components/GameModePanel.vue'

const st = computed(() => session.status)
const ff = ref(''), burn = ref(''), ffEl = ref<HTMLInputElement>(), burnEl = ref<HTMLInputElement>()
// keep the fields in step with the game unless the admin is typing in them
watch(() => st.value?.ff, v => { if (v != null && document.activeElement !== ffEl.value) ff.value = String(v) }, { immediate: true })
watch(() => st.value?.burn, v => { if (v != null && document.activeElement !== burnEl.value) burn.value = String(v) }, { immediate: true })

const target = ref('@all'), custom = ref(''), amount = ref(300)

async function preset(n: string) { await run(() => setPreset(n), '特感预设已切换为 ' + n).catch(() => {}); void session.refreshStatus() }
async function difficulty(l: string) { await run(() => setDifficulty(l), '难度已设为 ' + DIFFICULTY_NAMES[l] + '，即时生效').catch(() => {}); void session.refreshStatus() }
async function damage() {
  const o: { ff?: number; burn?: number } = {}
  if (ff.value !== '') o.ff = +ff.value
  if (burn.value !== '') o.burn = +burn.value
  if (!Object.keys(o).length) { toast('请填写至少一项', true); return }
  try {
    const j = await run(() => setDamage(o), '伤害已更新' + (o.ff != null ? '：友伤 ' + o.ff : '') + (o.burn != null ? '，火焰 ' + o.burn : ''))
    if (j.persisted === false) toast('已生效，但 server.cfg 未写入（看控制台输出）', true)
  } catch { /* toasted */ }
  void session.refreshStatus()
}
async function points() {
  let t = target.value, label = t === '@all' ? '全体在线玩家' : (session.players.find(p => '#' + p.userid === t)?.name ?? t)
  if (t === '__custom') { t = custom.value.trim(); label = t; if (!t) { toast('请输入玩家名或 #userid', true); return } }
  const a = +amount.value
  if (!a) { toast('请输入分数', true); return }
  await run(() => givePoints(t, a), `已给 ${label} 发 ${a} 分`).catch(() => {})
}
</script>

<template>
  <section class="view on"><GameModePanel v-if="session.features?.sourcemod" /><div class="grid">
    <div v-if="session.features?.preset" class="card"><h2>特感强度</h2>
      <div class="row"><span class="seg"><button v-for="p in PRESETS" :key="p" :class="{ on: st?.preset === p }" @click="preset(p)">{{ p }}</button></span></div>
      <div class="note">auto = 按存活人数 4→16 只自动缩放；te8 / te12 / te16 = 固定数量。切换立即生效并保存，换图、重启都保持。</div>
    </div>
    <div class="card"><h2>难度</h2>
      <div class="row"><span class="seg"><button v-for="(name, l) in DIFFICULTY_NAMES" :key="l" :class="{ on: st?.difficulty === l }" @click="difficulty(String(l))">{{ name }}</button></span></div>
      <div class="note">即时生效；跨换图锁定难度需 Force Difficulty 插件。已刷出的 Tank 血量不变。</div>
    </div>
    <div v-if="session.features?.sourcemod" class="card"><h2>伤害</h2>
      <div class="row">
        <label>友伤 <input ref="ffEl" v-model="ff" type="number" min="0" max="1" step="0.05" style="width:86px"></label>
        <label>火焰伤害 <input ref="burnEl" v-model="burn" type="number" min="0" max="1" step="0.05" style="width:86px"></label>
        <button @click="damage">应用</button>
      </div>
      <div class="note"><p>0 = 无伤害，1 = 全额；即时生效并写入 server.cfg，重启保持。</p><p>四个难度档位统一设为同一值，投票换难度后也不变；游戏默认友伤 0.1 / 0.3 / 0.5，火焰 0.2 / 0.2 / 0.4 / 1。</p></div>
    </div>
    <div v-if="session.features?.points" class="card"><h2>发放积分</h2>
      <div class="row">
        <select v-model="target" style="flex:1;min-width:0">
          <option value="@all">全体在线玩家{{ session.players.length ? `（${session.players.length} 人）` : '' }}</option>
          <option v-for="p in session.players" :key="p.userid" :value="'#' + p.userid">{{ p.name }}</option>
          <option value="__custom">手动输入…</option>
        </select>
        <input v-if="target === '__custom'" v-model="custom" placeholder="玩家名 / #userid" style="width:140px">
        <input v-model="amount" type="number" style="width:96px"><button @click="points">发放</button>
      </div>
      <div class="note">通过 Points System 的 <code>sm_givepoints</code> 发放。</div>
    </div>
  </div></section>
</template>
