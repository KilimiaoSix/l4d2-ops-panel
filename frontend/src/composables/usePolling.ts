import { onBeforeUnmount, onMounted } from 'vue'

/** Call fn now and every `ms` while the component is mounted. */
export function usePolling(fn: () => void | Promise<unknown>, ms: number) {
  let timer: ReturnType<typeof setInterval> | undefined
  onMounted(() => { void fn(); timer = setInterval(() => { void fn() }, ms) })
  onBeforeUnmount(() => clearInterval(timer))
}
