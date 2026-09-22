<script setup lang="ts">
import { onMounted } from 'vue'
import AppShell from './components/AppShell.vue'
import Toast from './components/Toast.vue'
import { session } from './stores/session'
import LoginView from './views/LoginView.vue'
import SetupView from './views/SetupView.vue'

onMounted(() => { void session.boot() })
</script>

<template>
  <SetupView v-if="session.phase === 'setup'" />
  <LoginView v-else-if="session.phase === 'login'" />
  <AppShell v-else-if="session.phase === 'app'" />
  <Toast />
</template>
