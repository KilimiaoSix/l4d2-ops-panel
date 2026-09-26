<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getOnboarding, saveOnboarding } from '../api/panel'
import type { Onboarding, SetupStep } from '../api/types'
import { session } from '../stores/session'
import PanelConfigView from './PanelConfigView.vue'
import ServerView from './ServerView.vue'
import PluginPackCard from '../components/PluginPackCard.vue'
import BasicSettingsView from './BasicSettingsView.vue'
import JoinServerCard from '../components/JoinServerCard.vue'
import { useRouter } from 'vue-router'

const router = useRouter(), state = ref<Onboarding | null>(null), error = ref(''), busy = ref(false)
const steps: { id: SetupStep; title: string }[] = [
  { id: 'panel', title: '面板与环境' }, { id: 'game', title: '安装游戏' }, { id: 'packs', title: '选择插件' },
  { id: 'settings', title: '基础设置' }, { id: 'join', title: '邀请朋友' },
]
let alive = true, revision = 0
async function load() {
  const rev = ++revision
  try { const value = await getOnboarding(); if (alive && rev === revision) state.value = value }
  catch (e) { if (alive && rev === revision) error.value = (e as Error).message }
}
async function move(step: SetupStep, complete = false, reopen = false) {
  if (busy.value) return
  busy.value = true; error.value = ''; const rev = ++revision
  try {
    const value = await saveOnboarding(step, {}, complete, reopen)
    if (!alive || rev !== revision) return
    state.value = value
    if (complete) { await session.refreshStatus(); await router.push('/overview') }
  } catch (e) { if (alive && rev === revision) error.value = (e as Error).message }
  finally { if (alive) busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { alive = false; revision++ })
</script>

<template>
  <section class="view on">
    <div class="card">
      <h2>开服向导<span class="sp" /><button class="g sm" :disabled="busy" @click="load">检查进度</button></h2>
      <p>按步骤准备一个朋友可以加入的服务器。进度自动保留，可随时离开后继续。</p>
      <p v-if="error" role="alert" class="hint">{{ error }}</p>
      <p v-if="session.role !== 'owner'">向导设置需要 owner 账号；日常管理功能仍可使用。</p>
      <template v-else-if="state">
        <p v-if="state.complete">这个面板已完成初始化。<button class="g sm" :disabled="busy" @click="move('panel', false, true)">重新检查开服配置</button></p>
        <nav class="setup-steps" aria-label="开服步骤">
          <button v-for="(step, index) in steps" :key="step.id" :class="state.step === step.id ? '' : 'g'" :disabled="busy" @click="move(step.id)">
            <span>{{ state.checks[step.id].ready ? '✓' : index + 1 }}</span> {{ step.title }}
          </button>
        </nav>
        <p class="mu">默认使用最小插件包；多人、特感和积分可以现在选装，也可以以后补装。</p>
      </template>
    </div>
    <template v-if="state && session.role === 'owner'">
      <PanelConfigView v-if="state.step === 'panel'" />
      <ServerView v-else-if="state.step === 'game'" persist-draft />
      <PluginPackCard v-else-if="state.step === 'packs'" persist-draft />
      <BasicSettingsView v-else-if="state.step === 'settings'" persist-draft @saved="load" />
      <template v-else>
        <JoinServerCard />
        <div class="card">
        <ul v-if="state.missing.length"><li v-for="key in state.missing" :key="key">{{ state.checks[key].reason }}</li></ul>
        <button :disabled="busy || !!state.missing.length" @click="move('join', true)">完成向导</button>
        </div>
      </template>
      <div v-if="state.step !== 'join'" class="card row"><button :disabled="busy" @click="move(steps[steps.findIndex(s => s.id === state!.step) + 1]!.id)">保存进度，下一步</button><span class="mu">所有必要项目完成后才能结束向导。</span></div>
    </template>
  </section>
</template>

<style scoped>
.setup-steps { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.setup-steps button { flex: 1 0 125px; }
.view .view { padding: 0; }
</style>
