<script setup lang="ts">
import { toastState } from '../composables/useToast'
</script>

<template>
  <div id="toast" :class="{ show: toastState.show, bad: toastState.bad }">{{ toastState.text }}</div>
</template>
