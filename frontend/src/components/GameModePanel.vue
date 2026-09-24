<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getGameMode, setGameMode } from '../api/game-mode'
import type { GameModeStatus } from '../api/game-mode'

const current = ref<GameModeStatus>({ mode: null, map: null, read_error: null, saved_mode: null, config_error: null, modes: [] })
const selected = ref(''), loading = ref(false), submitting = ref(false), verifying = ref(false)
const readError = ref(''), submitError = ref(''), notice = ref(''), verified = ref(false)
const target = computed(() => current.value.modes.find(item => item.id === selected.value))
const currentName = computed(() => current.value.modes.find(item => item.id === current.value.mode)?.name)
const savedName = computed(() => current.value.modes.find(item => item.id === current.value.saved_mode)?.name)
const modeGroups = computed(() => Array.from(new Set(current.value.modes.map(mode => mode.group || '基础模式'))).map(name => ({
  name,
  modes: current.value.modes.filter(mode => (mode.group || '基础模式') === name),
})))
const activeGroup = ref(''), modeQuery = ref('')
let filtersInitialized = false
const visibleGroups = computed(() => {
  const query = modeQuery.value.trim().toLocaleLowerCase()
  return modeGroups.value
    .filter(group => !activeGroup.value || group.name === activeGroup.value)
    .map(group => ({ ...group, modes: group.modes.filter(mode => !query || `${mode.name} ${mode.english || ''} ${mode.id}`.toLocaleLowerCase().includes(query)) }))
    .filter(group => group.modes.length)
})
const visibleCount = computed(() => visibleGroups.value.reduce((count, group) => count + group.modes.length, 0))
const selectedVisible = computed(() => visibleGroups.value.some(group => group.modes.some(mode => mode.id === selected.value)))
function selectGroup(name: string) {
  filtersInitialized = true
  activeGroup.value = name
}
function markSearchChanged() {
  filtersInitialized = true
}
function clearFilters() {
  selectGroup('')
  modeQuery.value = ''
}
const blocked = computed(() => loading.value || submitting.value || verifying.value || !!readError.value || !!current.value.config_error || !current.value.mode || !current.value.map || !target.value)
const refreshBlocked = computed(() => loading.value || submitting.value || (verifying.value && !readError.value))
let active = true
let pollTimer: ReturnType<typeof setTimeout> | undefined
let deadlineTimer: ReturnType<typeof setTimeout> | undefined
let expected: { mode: string; map: string } | null = null
let consecutiveMatches = 0

function stopVerification() {
  clearTimeout(pollTimer); clearTimeout(deadlineTimer)
  pollTimer = undefined; deadlineTimer = undefined
  verifying.value = false
}

async function readCurrent() {
  if (!active || loading.value) return
  loading.value = true
  try {
    const response = await getGameMode()
    if (!active) return
    current.value = response
    readError.value = response.read_error || (!response.mode || !response.map ? '服务器未返回完整的模式与地图，当前状态未知。' : '')
    if (readError.value) {
      current.value = { ...response, mode: null, map: null }
    }
    if (!selected.value) selected.value = response.modes.find(item => item.id === response.mode)?.id ?? response.modes[0]?.id ?? ''
    if (!filtersInitialized && response.modes.length) {
      const initialMode = response.modes.find(item => item.id === response.mode) ?? response.modes[0]
      activeGroup.value = initialMode?.group || '基础模式'
      filtersInitialized = true
    }
    if (verifying.value && expected) {
      const matches = !readError.value && response.mode === expected.mode && response.map === expected.map
      consecutiveMatches = matches ? consecutiveMatches + 1 : 0
      if (consecutiveMatches >= 2) {
        stopVerification()
        verified.value = true
        notice.value = '服务器模式与地图已连续两次核对一致。'
      }
    }
  } catch (error) {
    if (!active) return
    current.value = { ...current.value, mode: null, map: null }
    readError.value = error instanceof Error ? error.message : '读取服务器状态失败，请重试。'
    consecutiveMatches = 0
  } finally {
    if (active) {
      loading.value = false
      if (verifying.value) pollTimer = setTimeout(() => { void readCurrent() }, 3000)
    }
  }
}

async function refresh() {
  if (refreshBlocked.value) return
  clearTimeout(pollTimer)
  if (verified.value) notice.value = ''
  verified.value = false
  await readCurrent()
}

async function switchMode() {
  if (blocked.value || !target.value) return
  const choice = target.value
  if (!confirm(`将「${choice.name}」保存为默认模式并载入「${choice.map_name}」（${choice.map}）？\n重载和重启后继续使用；保存前自动备份 server.cfg。\n服务器将重载地图，当前进度会被重置，在线玩家将受影响。`)) return
  submitting.value = true
  submitError.value = ''; notice.value = ''; verified.value = false
  consecutiveMatches = 0
  try {
    const response = await setGameMode(choice.id)
    if (!active) return
    current.value = { ...current.value, saved_mode: response.mode, config_error: null }
    expected = { mode: response.mode, map: response.map }
    verifying.value = true
    notice.value = response.state === 'uncertain'
      ? `${response.message} 请求结果尚不确定，正在读取服务器状态核对；不会自动再次切换。`
      : `${response.message} 正在等待服务器重载并核对实际模式与地图。`
    pollTimer = setTimeout(() => { void readCurrent() }, 3000)
    deadlineTimer = setTimeout(() => {
      stopVerification()
      notice.value = '30 秒内未能连续两次核对到目标模式与地图，切换结果尚未确认。请刷新实际状态后再判断；不会自动再次切换。'
    }, 30000)
  } catch (error) {
    if (active) {
      submitError.value = error instanceof Error ? error.message : '发送切换请求失败，请检查实际状态。'
      await readCurrent()
    }
  } finally {
    if (active) submitting.value = false
  }
}

onMounted(() => { void readCurrent() })
onBeforeUnmount(() => { active = false; stopVerification() })
</script>

<template>
  <div class="card game-mode-panel" :aria-busy="loading || submitting || verifying">
    <h2>游戏模式<span class="sp" /><button class="g sm" :disabled="refreshBlocked" @click="refresh">{{ loading ? '读取中…' : '刷新状态' }}</button></h2>
    <div class="mode-status">
      <div class="status-lead"><span class="status-kicker">运行配置</span><strong>{{ current.modes.length || '—' }}</strong><span>个模式选项</span></div>
      <div class="status-item"><span class="status-label"><i class="status-dot live" />当前实际</span><span class="status-value"><template v-if="current.mode"><b>{{ currentName || current.mode }}</b><code>{{ current.mode }}</code></template><span v-else class="mu">未知</span></span></div>
      <div class="status-item"><span class="status-label"><i class="status-dot saved" />默认配置</span><span class="status-value"><template v-if="current.saved_mode"><b>{{ savedName || current.saved_mode }}</b><code>{{ current.saved_mode }}</code></template><span v-else class="mu">{{ current.config_error ? '未知' : '未配置' }}</span></span></div>
      <div class="status-item map-state"><span class="status-label">当前地图</span><span class="status-value"><code v-if="current.map">{{ current.map }}</code><span v-else class="mu">未知</span></span></div>
    </div>
    <div v-if="readError" class="mode-error" role="alert">读取失败：{{ readError }}<span v-if="verifying"> 重载期间会自动重试读取，也可刷新状态。</span></div>
    <div v-if="current.config_error" class="mode-error" role="alert">默认模式配置异常：{{ current.config_error }} 请修复配置后刷新状态再切换。</div>
    <div class="mode-picker" aria-label="选择目标游戏模式">
      <div class="picker-head"><span class="picker-label">选择运行模式</span><span class="mu">点击卡片查看目标地图与规则</span></div>
      <div v-if="current.modes.length" class="mode-filters">
        <div class="group-options" aria-label="筛选模式分组">
          <button type="button" class="g sm" :class="{ on: !activeGroup }" :aria-pressed="!activeGroup" @click="selectGroup('')">全部 <span>{{ current.modes.length }}</span></button>
          <button v-for="group in modeGroups" :key="group.name" type="button" class="g sm" :class="{ on: activeGroup === group.name }" :aria-pressed="activeGroup === group.name" @click="selectGroup(group.name)">{{ group.name }} <span>{{ group.modes.length }}</span></button>
        </div>
        <label class="mode-search"><span class="sr-only">搜索模式名称或 ID</span><input v-model="modeQuery" type="search" placeholder="搜索名称或 ID" @input="markSearchChanged"></label>
      </div>
      <p v-if="activeGroup === '突变模式' || target?.group === '突变模式'" class="mutation-hint">突变模式使用游戏内置规则；已有多特、人数插件可能覆盖这些规则，仍需真人联机验收。</p>
      <div v-if="!current.modes.length" class="mode-empty">正在读取模式列表…</div>
      <div v-else-if="!visibleCount" class="mode-empty"><span>没有符合筛选条件的模式。</span><button type="button" class="g sm" @click="clearFilters">清除筛选</button></div>
      <div v-else class="mode-groups">
        <section v-for="group in visibleGroups" :key="group.name" class="mode-group" :aria-label="group.name">
          <h3>{{ group.name }}<span>{{ group.modes.length }}</span></h3>
          <div class="mode-grid">
            <button
              v-for="mode in group.modes"
              :key="mode.id"
              type="button"
              class="mode-tile"
              :class="{ selected: selected === mode.id, live: current.mode === mode.id, saved: current.saved_mode === mode.id }"
              :aria-pressed="selected === mode.id"
              :disabled="submitting || verifying"
              @click="selected = mode.id"
            >
              <span class="tile-top"><span class="tile-name">{{ mode.name }}</span><span v-if="current.mode === mode.id" class="mode-flag live-flag">运行中</span><span v-else-if="current.saved_mode === mode.id" class="mode-flag saved-flag">默认</span></span>
              <span v-if="mode.english" class="tile-english">{{ mode.english }}</span>
              <span class="tile-meta"><span class="tile-id">{{ mode.id }}</span><span v-if="mode.native_players === 1" class="native-rule">原生单人</span></span>
              <span class="tile-rule">{{ mode.description }}</span>
              <span class="tile-map">起始地图 · {{ mode.map_name }}</span>
            </button>
          </div>
        </section>
      </div>
      <div class="mode-controls">
        <div v-if="target" id="game-mode-description" class="mode-description"><span class="selected-mark">已选择</span><b>{{ target.name }}</b><span>{{ target.description }}</span><code>{{ target.map }}</code><span v-if="!selectedVisible" class="selection-hidden">所选模式已被筛选隐藏，切换目标不变。</span></div>
        <button class="mode-apply" :disabled="blocked" @click="switchMode">{{ submitting ? '正在保存…' : verifying ? '正在核对…' : '保存并切换模式' }}</button>
      </div>
    </div>
    <p v-if="submitError" class="mode-error" role="alert">切换请求失败：{{ submitError }}</p>
    <p v-if="notice" class="mode-notice" :class="{ verified }" role="status">{{ notice }}</p>
    <div id="game-mode-warning" class="note"><p><b>切换会重载地图并重置当前进度，在线玩家会受影响。</b></p><p>保存前自动备份 server.cfg，并将所选模式保存为默认模式，重载和重启后继续使用。配置已保存不代表当前已生效；其他配置命令或插件仍可能覆盖模式，可刷新实际状态核对。</p></div>
  </div>
</template>

<style scoped>
.game-mode-panel{min-width:0;overflow:hidden}
.mode-status{display:grid;grid-template-columns:minmax(150px,.9fr) repeat(3,minmax(0,1fr));gap:1px;margin:0 -18px 18px;background:var(--bd);border-top:1px solid var(--bd);border-bottom:1px solid var(--bd)}
.mode-status>div{min-width:0;background:var(--sur);padding:11px 14px}
.status-lead{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px;color:var(--mu);font-size:12px}.status-lead strong{font-family:var(--fd);font-size:23px;color:var(--tx);line-height:1}.status-kicker{font-size:11px;color:var(--ac)}
.status-item{display:flex;flex-direction:column;gap:5px}.status-label{display:flex;align-items:center;gap:6px;color:var(--mu);font-size:12px}.status-value{display:flex;align-items:center;gap:7px;min-width:0;flex-wrap:wrap;overflow-wrap:anywhere}.status-value b{font-size:13px;font-weight:600}.status-value code{font-size:11px;padding:1px 4px;color:var(--mu)}.status-dot{width:6px;height:6px;border-radius:50%;background:var(--mu)}.status-dot.live{background:var(--ok)}.status-dot.saved{background:var(--ac)}
.mode-picker{min-width:0}.picker-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:14px}.picker-label{font-size:13px;color:var(--tx);font-weight:600}.picker-head .mu{font-size:12px}
.mode-filters{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:16px;flex-wrap:wrap}.group-options{display:flex;gap:6px;flex-wrap:wrap}.group-options button.on{border-color:var(--ac);color:var(--ac2);background:var(--inp)}.group-options button span{font-family:var(--fm);font-size:11px;color:var(--mu)}.mode-search{margin-left:auto;min-width:0;flex:0 1 210px}.mode-search input{width:100%;height:34px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.selection-hidden{flex-basis:100%;color:var(--warn)}
.mutation-hint{margin:-4px 0 14px;color:var(--mu);font-size:12px;line-height:1.6}
.tile-english{margin-top:3px;font-size:12px;font-weight:400;color:var(--mu);line-height:1.5;overflow-wrap:anywhere}.tile-meta{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px}.native-rule{font-size:11px;font-weight:400;color:var(--warn)}
.mode-groups{display:flex;flex-direction:column;gap:18px}.mode-group{min-width:0}.mode-group h3{display:flex;align-items:center;gap:8px;margin:0 0 8px;color:var(--mu);font-size:12px;font-weight:500}.mode-group h3 span{font-family:var(--fm);font-size:11px}
.mode-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.mode-tile{display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;gap:0;min-width:0;height:auto;min-height:155px;padding:14px;background:var(--inp);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r2);text-align:left;white-space:normal;transition:border-color .15s,background .15s,transform .15s,box-shadow .15s}.mode-tile:hover:not(:disabled){background:var(--sur2);border-color:var(--bd2);transform:translateY(-1px)}.mode-tile:focus-visible{outline:2px solid var(--ac2);outline-offset:2px}.mode-tile.selected{border-color:var(--ac);background:#282019;box-shadow:inset 0 2px 0 var(--ac)}.mode-tile.live{border-left-color:var(--ok)}.mode-tile.saved:not(.selected){border-top-color:var(--ac2)}
.tile-top{display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px}.tile-name{font-size:15px;font-weight:700;line-height:1.4}.mode-flag{flex:none;font-size:11px;line-height:1.3;padding:2px 5px;border-radius:3px;font-weight:500}.live-flag{color:var(--ok);background:rgba(94,211,137,.12)}.saved-flag{color:var(--ac2);background:rgba(240,161,58,.12)}.tile-id{font-family:var(--fm);font-size:11px;color:var(--mu);margin-top:3px;overflow-wrap:anywhere}.tile-rule{font-size:12px;font-weight:400;color:var(--mu);line-height:1.6;margin:10px 0 12px;overflow-wrap:anywhere}.tile-map{width:100%;margin-top:auto;padding-top:9px;border-top:1px solid var(--bd);font-size:12px;font-weight:400;color:var(--ac2);overflow-wrap:anywhere;line-height:1.5}
.mode-empty{display:flex;justify-content:center;align-items:center;flex-wrap:wrap;gap:12px;padding:25px 14px;color:var(--mu);background:var(--inp);border:1px dashed var(--bd2);border-radius:var(--r2);text-align:center}
.mode-controls{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:16px;padding-top:14px;border-top:1px solid var(--bd)}.mode-description{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap;color:var(--mu);font-size:12px;line-height:1.5}.mode-description b{color:var(--tx);font-size:13px}.mode-description span:not(.selected-mark){overflow-wrap:anywhere}.selected-mark{font-size:11px;color:var(--ac);border:1px solid var(--bd2);padding:2px 5px;border-radius:3px}.mode-description code{font-size:11px}.mode-apply{flex-shrink:0}
.mode-error,.mode-notice{margin:8px 0;line-height:1.6;overflow-wrap:anywhere}
.mode-error{color:var(--bad2)}
.mode-notice{color:var(--warn)}
.mode-notice.verified{color:var(--ok)}
code{overflow-wrap:anywhere}
@container shell (max-width:1050px){.mode-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.mode-status{grid-template-columns:repeat(3,minmax(0,1fr))}.status-lead{grid-column:span 3}}
@container shell (max-width:860px){.mode-status{margin-left:-14px;margin-right:-14px}}
@container shell (max-width:560px){.mode-grid{grid-template-columns:minmax(0,1fr)}.mode-status{grid-template-columns:repeat(2,minmax(0,1fr))}.status-lead{grid-column:span 2}.map-state{grid-column:span 2}.mode-controls{align-items:stretch;flex-direction:column}.mode-apply{width:100%}.picker-head{align-items:flex-start;flex-direction:column;gap:3px}.mode-tile{min-height:0}.mode-search{flex-basis:100%}}
</style>
