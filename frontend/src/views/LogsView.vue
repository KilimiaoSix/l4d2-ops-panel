<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { getLogs } from '../api/endpoints'

const TABS: [string, string][] = [['console', '控制台'], ['errors', '插件报错'], ['perf', '采样']]
const kind = ref('console'), text = ref(''), pre = ref<HTMLPreElement>()

async function load(k = kind.value) {
  kind.value = k
  try { text.value = (await getLogs(k)).lines.join('\n') || '(空)' } catch { return }
  await nextTick(); if (pre.value) pre.value.scrollTop = pre.value.scrollHeight
}
onMounted(() => load())
</script>

<template>
  <section class="view on">
    <div class="card"><h2>日志<span class="sp" /><span class="tabs"><button v-for="[k, name] in TABS" :key="k" :class="{ on: kind === k }" @click="load(k)">{{ name }}</button></span><button class="g sm" @click="load()">刷新</button></h2>
      <pre ref="pre" style="max-height:70vh">{{ text }}</pre>
    </div>
  </section>
</template>
