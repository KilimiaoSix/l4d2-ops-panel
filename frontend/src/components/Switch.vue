<script setup lang="ts">
defineProps<{ on: boolean | null; label: string }>()
defineEmits<{ toggle: [] }>()
</script>

<template>
  <button type="button" class="sw" :class="{ on: on === true, dis: on === null }" :aria-pressed="on ? 'true' : 'false'" :aria-label="label" @click="$emit('toggle')" />
</template>
