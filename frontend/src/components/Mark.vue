<script setup lang="ts">
// the panel's crosshair mark; colour comes from currentColor
</script>

<template>
  <svg class="mark" viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="2.6" />
    <path d="M16 2.5v6M16 23.5v6M2.5 16h6M23.5 16h6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" />
    <circle cx="16" cy="16" r="2.6" fill="currentColor" />
  </svg>
</template>
