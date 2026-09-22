<script setup lang="ts">
import { ref } from 'vue'
import { postSetup } from '../api/endpoints'
import Mark from '../components/Mark.vue'
import { session } from '../stores/session'

const pw = ref(''), pw2 = ref(''), msg = ref('')

async function submit() {
  if (pw.value.length < 4) { msg.value = '密码至少 4 位'; return }
  if (pw.value !== pw2.value) { msg.value = '两次输入不一致'; return }
  try { await postSetup(pw.value); await session.refreshStatus(); session.phase = 'app' } catch (e) { msg.value = (e as Error).message }
}
</script>

<template>
  <div id="setup"><div class="box"><div class="tape" /><div class="in">
    <Mark />
    <div class="eyebrow">L4D2 Ops Panel</div><h2>首次使用：设置管理员密码</h2>
    <div class="mu">账号 <code>{{ session.setupUsername }}</code> 是 owner，之后可以在“账号”页改密码、加其他账号。</div>
    <label for="su-pw">密码（至少 4 位）</label><input id="su-pw" v-model="pw" type="password" placeholder="设置密码" autocomplete="new-password" @keydown.enter="submit">
    <label for="su-pw2">再输一次</label><input id="su-pw2" v-model="pw2" type="password" placeholder="再输一次" autocomplete="new-password" @keydown.enter="submit">
    <button @click="submit">设置并进入面板</button><div id="sumsg">{{ msg }}</div>
  </div></div></div>
</template>
