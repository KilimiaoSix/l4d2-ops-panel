<script setup lang="ts">
import { toastState } from '../composables/useToast'
</script>

<template>
  <div class="toast" role="status" :aria-hidden="!toastState.show" :class="{ show: toastState.show, bad: toastState.bad }">{{ toastState.text }}</div>
</template>
