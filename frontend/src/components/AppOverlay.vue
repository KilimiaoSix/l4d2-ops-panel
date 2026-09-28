<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import Toast from './Toast.vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description?: string
  kind?: 'modal' | 'drawer'
  keepMounted?: boolean
  wide?: boolean
  busy?: boolean
  beforeClose?: () => boolean
}>(), { kind: 'modal' })
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const titleId = useId(), descriptionId = useId()
let returnFocus: HTMLElement | null = null
let previousOverflow = '', locked = false

function restore() {
  if (!locked) return
  document.body.style.overflow = previousOverflow
  locked = false
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
}
function sync() {
  if (!dialog.value) return
  if (props.open && !dialog.value.open) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    locked = true
    dialog.value.showModal()
    const first = Array.from(dialog.value.querySelectorAll<HTMLElement>('[data-autofocus], .overlay-body input:not([type=file]):not([disabled]), .overlay-body select:not([disabled])'))
      .find(element => element.getClientRects().length > 0)
    first?.focus({ preventScroll: true })
  } else if (!props.open && dialog.value.open) {
    dialog.value.close()
    restore()
  }
}
function close() {
  if (props.busy || (props.beforeClose && !props.beforeClose())) return
  emit('close')
}
function backdrop(event: PointerEvent) {
  if (event.target !== dialog.value || !dialog.value) return
  const box = dialog.value.getBoundingClientRect()
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close()
}
watch(() => props.open, sync, { flush: 'post' })
onMounted(sync)
onBeforeUnmount(() => { dialog.value?.close(); restore() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="app-overlay" :class="[kind, { wide }]" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="description ? descriptionId : undefined" :aria-busy="busy" @cancel.prevent="close" @pointerdown="backdrop">
      <div v-if="open || keepMounted" class="overlay-layout">
        <div class="overlay-heading">
          <div><h2 :id="titleId">{{ title }}</h2><p v-if="description" :id="descriptionId">{{ description }}</p></div>
          <button class="g overlay-close" type="button" :disabled="busy" :aria-label="'关闭' + title" @click="close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
        </div>
        <div class="overlay-body"><slot /></div>
        <div v-if="$slots.footer" class="overlay-footer"><slot name="footer" /></div>
        <Toast />
      </div>
    </dialog>
  </Teleport>
</template>
