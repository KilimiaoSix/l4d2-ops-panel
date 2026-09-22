import { reactive } from 'vue'

export const toastState = reactive({ text: '', bad: false, show: false })
let timer: ReturnType<typeof setTimeout> | undefined

export function toast(text: string, bad = false) {
  toastState.text = text; toastState.bad = bad; toastState.show = true
  clearTimeout(timer); timer = setTimeout(() => { toastState.show = false }, 2800)
}

/** Trim command output to one toast-sized line. */
export function short(t: unknown) {
  const s = String(t ?? '').replace(/\s+/g, ' ').trim()
  return s.length > 140 ? s.slice(0, 140) + '…' : s
}

/** Run an API call and toast its outcome; rethrows so callers can stop on failure. */
export async function run<T extends object>(call: () => Promise<T>, okMessage?: string): Promise<T> {
  try {
    const j = await call(); toast(okMessage || short('out' in j ? (j as { out?: string }).out : '') || '完成'); return j
  } catch (e) {
    toast((e as Error).message, true); throw e
  }
}
