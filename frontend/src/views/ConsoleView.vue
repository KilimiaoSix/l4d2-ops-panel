<script setup lang="ts">
import { ref } from 'vue'
import { rcon } from '../api/endpoints'

const cmd = ref(''), out = ref('(输出显示在这里)')
const history: string[] = []

async function send() {
  const c = cmd.value.trim(); if (!c) return
  history.push(c); cmd.value = ''
  try { out.value = '> ' + c + '\n' + ((await rcon(c)).out || '(无输出)') } catch (e) { out.value = '错误: ' + (e as Error).message }
}
function recall() { if (history.length) cmd.value = history[history.length - 1]! }
</script>

<template>
  <section class="view on">
    <div class="card"><h2>RCON 控制台</h2>
      <div class="row"><input v-model="cmd" placeholder="status · sm plugins list · sm_cvar z_difficulty · sm_wl_list …" style="flex:1;font-family:var(--fm)" @keydown.enter="send" @keydown.up.prevent="recall"><button @click="send">发送</button></div>
      <pre style="max-height:60vh">{{ out }}</pre>
      <div class="hint">隐藏 cvar（z_common_limit、nb_update_frequency、sv_airaccelerate 等）要写 <code>sm_cvar 名字 [值]</code>。↑ 取回上一条命令。</div>
    </div>
  </section>
</template>
