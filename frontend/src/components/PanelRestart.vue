<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { PanelConfiguration } from '../api/types'
import { panelRestart } from '../stores/restart'
import { session } from '../stores/session'

const crossOrigin = computed(() => new URL(panelRestart.nextUrl).origin !== location.origin)
const message = ref('正在等待面板重新启动…'), expired = ref(false)
const started = Date.now()
let timer: ReturnType<typeof setTimeout> | undefined, controller: AbortController | undefined, alive = true
async function poll() {
  if (!alive || crossOrigin.value) return
  if (Date.now() - started > 90000) { expired.value = true; message.value = '90 秒内没有确认面板恢复。可以重新检查原地址，或在服务器运行恢复命令。'; return }
  controller = new AbortController()
  const timeout = setTimeout(() => controller?.abort(), 3500)
  try {
    const response = await fetch('/api/panel-config', { cache: 'no-store', signal: controller.signal })
    if (!alive) return
    if (response.status === 401) {
      session.loginNote = '面板已重新响应，请重新登录以确认配置。'
      session.phase = 'login'; panelRestart.active = false; return
    }
    if (response.ok) {
      const state = await response.json() as PanelConfiguration
      if (state.boot !== panelRestart.previousBoot) {
        if (state.applied_revision !== panelRestart.revision) {
          message.value = '面板已恢复，但当前配置与刚保存的版本不同，可能已自动回退。请返回设置检查。'
          expired.value = true; return
        }
        await session.boot()
        if (alive) panelRestart.active = false
        return
      }
    }
  } catch { /* The old listener disappearing is expected during restart. */ }
  finally { clearTimeout(timeout) }
  if (alive) timer = setTimeout(poll, 1500)
}
async function returnToPanel() { panelRestart.active = false; await session.boot() }
onMounted(poll)
onBeforeUnmount(() => { alive = false; clearTimeout(timer); controller?.abort() })
</script>

<template>
  <main class="restart-page">
    <div class="card">
      <div class="eyebrow">Panel restart</div><h1>面板正在重启</h1>
      <template v-if="crossOrigin">
        <p>访问地址已改变。请打开新地址，必要时重新登录；HTTPS 自签证书需要在浏览器确认。</p>
        <p><a :href="panelRestart.nextUrl">打开 {{ panelRestart.nextUrl }}</a></p>
        <p class="mu">新地址无法访问时，先核对防火墙和反向代理端口。启动失败后面板会尝试恢复原配置。</p>
      </template>
      <p v-else role="status">{{ message }}</p>
      <p v-if="expired || crossOrigin"><a :href="panelRestart.previousUrl" @click.prevent="returnToPanel">返回原地址检查</a></p>
      <p v-if="expired || crossOrigin">服务器恢复命令：<code>sudo l4d2panel-recover</code></p>
    </div>
  </main>
</template>

<style scoped>
.restart-page { max-width: 760px; margin: 12vh auto; padding: 24px; }
a { overflow-wrap: anywhere; }
</style>
