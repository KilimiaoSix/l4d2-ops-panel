<script setup lang="ts">
import type { Job } from '../api/types'

defineProps<{ label: string; job: Job }>()
</script>

<template>
  <div class="job" :class="job.state">
    <div class="jr"><i /><span>{{ label }}：{{ job.msg }}</span><slot /></div>
    <div v-if="job.state === 'running' && job.total" class="bar"><span :style="{ width: Math.min(100, Math.round(100 * (job.done || 0) / job.total)) + '%' }" /></div>
  </div>
</template>
