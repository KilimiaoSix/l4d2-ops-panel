/** Preserve a usable manual path when browser clipboard permission is unavailable. */
export async function copyText(value: string): Promise<boolean> {
  if (!value) return false
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch { /* try plain HTTP fallback */ }
  const previous = document.activeElement as HTMLElement | null
  const area = document.createElement('textarea')
  area.value = value; area.style.cssText = 'position:fixed;left:-9999px;top:0'
  area.setAttribute('readonly', '')
  document.body.appendChild(area); area.select()
  try { return document.execCommand('copy') }
  catch { return false }
  finally { area.remove(); previous?.focus({ preventScroll: true }) }
}
