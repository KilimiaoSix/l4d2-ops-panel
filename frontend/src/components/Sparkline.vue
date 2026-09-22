<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ values: number[]; color: string; min?: number; max?: number }>()
const el = ref<SVGSVGElement>()
const width = ref(600)
const H = 64, L = 44, R = 50
let ro: ResizeObserver | undefined

onMounted(() => {
  width.value = el.value?.clientWidth || 600
  ro = new ResizeObserver(() => { width.value = el.value?.clientWidth || 600 })   // sparklines are sized to the card: redraw when the layout changes
  if (el.value) ro.observe(el.value)
})
onBeforeUnmount(() => ro?.disconnect())

const chart = computed(() => {
  const vals = props.values, w = width.value
  if (!vals.length) return null
  const lo = props.min ?? Math.min(...vals), hi = props.max ?? Math.max(...vals), rng = (hi - lo) || 1
  const px = (i: number) => L + i / (vals.length - 1 || 1) * (w - L - R)
  const py = (v: number) => H - 8 - (v - lo) / rng * (H - 18)
  const pts = vals.map((v, i) => px(i).toFixed(1) + ',' + py(v).toFixed(1)).join(' ')
  const last = vals[vals.length - 1]!
  return { lo, hi, last, pts, area: `${px(0).toFixed(1)},${H - 8} ${pts} ${px(vals.length - 1).toFixed(1)},${H - 8}`, lastX: w - R + 6, lastY: (py(last) + 4).toFixed(1) }
})
</script>

<template>
  <svg ref="el" class="spark" :viewBox="`0 0 ${width} ${H}`">
    <text v-if="!chart" x="6" y="36">暂无采样（有玩家在线时每 15 秒记录一次）</text>
    <template v-else>
      <polygon class="ar" :fill="color" :points="chart.area" />
      <polyline class="ln" :stroke="color" :points="chart.pts" />
      <text :x="L - 6" y="12" text-anchor="end">{{ chart.hi.toFixed(1) }}</text>
      <text :x="L - 6" :y="H - 4" text-anchor="end">{{ chart.lo.toFixed(1) }}</text>
      <text class="last" :x="chart.lastX" :y="chart.lastY" :style="{ fill: color }">{{ chart.last.toFixed(1) }}</text>
    </template>
  </svg>
</template>
