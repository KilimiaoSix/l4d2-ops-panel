import { reactive } from 'vue'
import type { PanelConfigResult } from '../api/types'

export const panelRestart = reactive({
  active: false,
  previousBoot: '',
  revision: '',
  nextUrl: '',
  previousUrl: '',
  start(result: PanelConfigResult, nextUrl: string) {
    this.previousBoot = result.boot; this.revision = result.revision
    this.previousUrl = location.href; this.nextUrl = nextUrl; this.active = true
  },
})
