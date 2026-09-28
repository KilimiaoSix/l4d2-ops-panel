<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { givePoints, setDamage, setDifficulty, setPreset } from '../api/endpoints'
import { run, toast } from '../composables/useToast'
import { DIFFICULTY_NAMES, PRESETS } from '../data/campaigns'
import { session } from '../stores/session'
import AppOverlay from '../components/AppOverlay.vue'
import GameModePanel from '../components/GameModePanel.vue'
import BasicSettingsView from './BasicSettingsView.vue'
import JoinServerCard from '../components/JoinServerCard.vue'

const showJoin = ref(false), showBasic = ref(false), basicSettings = ref<InstanceType<typeof BasicSettingsView>>()
const active = ref<'damage' | 'points' | null>(null), busy = ref(false)
const st = computed(() => session.status)
const ff = ref(''), burn = ref(''), ffEl = ref<HTMLInputElement>(), burnEl = ref<HTMLInputElement>()
// keep the fields in step with the game unless the admin is typing in them
watch(() => st.value?.ff, v => { if (v != null && active.value !== 'damage' && document.activeElement !== ffEl.value) ff.value = String(v) }, { immediate: true })
watch(() => st.value?.burn, v => { if (v != null && active.value !== 'damage' && document.activeElement !== burnEl.value) burn.value = String(v) }, { immediate: true })

const target = ref('@all'), custom = ref(''), amount = ref(300)

async function preset(n: string) { await run(() => setPreset(n), '特感预设已切换为 ' + n).catch(() => {}); void session.refreshStatus() }
async function difficulty(l: string) { await run(() => setDifficulty(l), '难度已设为 ' + DIFFICULTY_NAMES[l] + '，即时生效').catch(() => {}); void session.refreshStatus() }
async function damage() {
  if (busy.value) return
  const o: { ff?: number; burn?: number } = {}
  if (ff.value !== '') o.ff = +ff.value
  if (burn.value !== '') o.burn = +burn.value
  if (!Object.keys(o).length) { toast('请填写至少一项', true); return }
  busy.value = true
  try {
    const j = await run(() => setDamage(o), '伤害已更新' + (o.ff != null ? '：友伤 ' + o.ff : '') + (o.burn != null ? '，火焰 ' + o.burn : ''))
    if (j.persisted === false) toast('已生效，但 server.cfg 未写入（看控制台输出）', true)
    active.value = null
  } catch { /* toasted */ } finally { busy.value = false }
  void session.refreshStatus()
}
async function points() {
  if (busy.value) return
  let t = target.value, label = t === '@all' ? '全体在线玩家' : (session.players.find(p => '#' + p.userid === t)?.name ?? t)
  if (t === '__custom') { t = custom.value.trim(); label = t; if (!t) { toast('请输入玩家名或 #userid', true); return } }
  const a = +amount.value
  if (!a) { toast('请输入分数', true); return }
  busy.value = true
  try { await run(() => givePoints(t, a), `已给 ${label} 发 ${a} 分`); active.value = null } catch { /* toasted */ } finally { busy.value = false }
}
</script>

<template>
  <section class="view on">
    <div class="page-actions"><span class="mu">管理游戏规则、服务器名称与加入方式</span><button class="g" @click="showJoin = true">加入说明</button><button class="g" @click="showBasic = true">基础设置</button></div>
    <AppOverlay :open="showJoin" title="邀请朋友加入" description="连接命令、进服步骤与连接排查" kind="drawer" @close="showJoin = false"><JoinServerCard /></AppOverlay>
    <AppOverlay :open="showBasic" title="服务器基础设置" description="名称、进服密码、地区与合作人数" kind="drawer" wide keep-mounted :busy="basicSettings?.busy" @close="showBasic = false"><BasicSettingsView ref="basicSettings" /></AppOverlay>
    <GameModePanel v-if="session.features?.sourcemod" />
    <div class="card settings-list">
      <div v-if="session.features?.preset" class="setting-row">
        <div><h3>特感强度</h3><p>auto 按存活人数缩放；固定预设即时生效，换图和重启保持。</p></div>
        <div class="row"><span class="seg"><button v-for="p in PRESETS" :key="p" :class="{ on: st?.preset === p }" @click="preset(p)">{{ p }}</button></span></div>
      </div>
      <div class="setting-row">
        <div><h3>游戏难度</h3><p>即时生效；跨换图锁定需要 Force Difficulty 插件。</p></div>
        <div class="row"><span class="seg"><button v-for="(name, l) in DIFFICULTY_NAMES" :key="l" :class="{ on: st?.difficulty === l }" @click="difficulty(String(l))">{{ name }}</button></span></div>
      </div>
      <div v-if="session.features?.sourcemod" class="setting-row">
        <div><h3>伤害系数</h3><p>友伤 {{ st?.ff ?? '—' }} · 火焰 {{ st?.burn ?? '—' }}，保存后重启保持。</p></div><button class="g" @click="active = 'damage'">调整伤害</button>
      </div>
      <div v-if="session.features?.points" class="setting-row">
        <div><h3>玩家积分</h3><p>向指定玩家或全体在线玩家发放积分。</p></div><button class="g" @click="active = 'points'">发放积分</button>
      </div>
    </div>
    <AppOverlay :open="!!active" :title="active === 'damage' ? '调整伤害' : '发放积分'" :busy="busy" @close="active = null">
      <form id="game-setting-form" class="form-stack" @submit.prevent="active === 'damage' ? damage() : points()">
        <template v-if="active === 'damage'">
          <div class="form-fields"><label>友伤系数<input ref="ffEl" v-model="ff" type="number" min="0" max="1" step="0.05" :disabled="busy"></label><label>火焰伤害系数<input ref="burnEl" v-model="burn" type="number" min="0" max="1" step="0.05" :disabled="busy"></label></div>
          <p class="hint">0 为无伤害，1 为全额伤害。四个难度档位统一设置，立即生效并写入 server.cfg。</p>
        </template>
        <template v-else>
          <label>发放对象<select v-model="target" :disabled="busy"><option value="@all">全体在线玩家（{{ session.players.length }} 人）</option><option v-for="p in session.players" :key="p.userid" :value="'#' + p.userid">{{ p.name }}</option><option value="__custom">手动输入…</option></select></label>
          <label v-if="target === '__custom'">玩家名或 #userid<input v-model="custom" required :disabled="busy"></label>
          <label>积分数量<input v-model="amount" type="number" required :disabled="busy"></label>
          <p class="hint">通过 Points System 的 sm_givepoints 发放。</p>
        </template>
      </form>
      <template #footer><button class="g" :disabled="busy" @click="active = null">取消</button><button type="submit" form="game-setting-form" :disabled="busy">{{ busy ? '提交中…' : active === 'damage' ? '保存并应用' : '确认发放' }}</button></template>
    </AppOverlay>
  </section>
</template>
