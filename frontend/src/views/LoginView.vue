<script setup lang="ts">
import { ref } from 'vue'
import { login } from '../api/endpoints'
import Mark from '../components/Mark.vue'
import { session } from '../stores/session'

const username = ref(''), password = ref(''), msg = ref('')

async function submit() {
  msg.value = ''
  try {
    await login(username.value.trim(), password.value)
    try { await session.refreshStatus(); if (!session.status) throw new Error() } catch {
      msg.value = '登录成功，但浏览器没有保存登录状态：请清除本站 cookie 后重试'; return
    }
    session.phase = 'app'
  } catch (e) { msg.value = (e as Error).message }
}
</script>

<template>
  <div id="login"><div class="box"><div class="tape" /><div class="in">
    <Mark />
    <div class="eyebrow">L4D2 Ops Panel</div><h2>登录面板</h2><div class="mu">Left 4 Dead 2 服务器运维面板</div>
    <label for="user">用户名</label><input id="user" v-model="username" placeholder="用户名" autocomplete="username" @keydown.enter="submit">
    <label for="pw">密码</label><input id="pw" v-model="password" type="password" placeholder="密码" autocomplete="current-password" @keydown.enter="submit">
    <button @click="submit">登录</button><div id="lmsg">{{ msg }}</div>
  </div></div></div>
</template>
