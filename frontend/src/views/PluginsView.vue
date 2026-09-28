<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import AppOverlay from '../components/AppOverlay.vue'
import PluginConfigPanel from '../components/PluginConfigPanel.vue'
import PluginPackCard from '../components/PluginPackCard.vue'
import { getPlugins, pluginAction, uploadSmx } from '../api/endpoints'
import type { PluginsResponse } from '../api/types'
import { short, toast } from '../composables/useToast'

const data = ref<PluginsResponse>({ enabled: [], disabled: [], raw: '' })
const packCard = ref<InstanceType<typeof PluginPackCard>>()
const overlay = ref<'upload' | 'raw' | 'packs' | null>(null), uploading = ref(false)
const msg = ref(''), fileEl = ref<HTMLInputElement>()
const selectedPlugin = ref(''), configPanel = ref<InstanceType<typeof PluginConfigPanel>>()
const pluginDisabled = computed(() => data.value.disabled.some(p => p.file === selectedPlugin.value))
function selectPlugin(file: string) {
  if (file === selectedPlugin.value) return
  if (configPanel.value && !configPanel.value.canLeave()) return
  selectedPlugin.value = file
}
onBeforeRouteLeave(() => configPanel.value?.canLeave() ?? true)
const NAMES: Record<string, string> = { reload: '重载', disable: '禁用', enable: '启用', delete: '删除' }

async function load() { try { data.value = await getPlugins() } catch { /* offline */ } }
onMounted(load)

async function act(op: string, file: string) {
  if (file === selectedPlugin.value && configPanel.value && !configPanel.value.canLeave()) return
  if ((op === 'disable' || op === 'delete') && !confirm(NAMES[op] + '插件 ' + file + '？')) return
  try { const d = await pluginAction(op, file); toast(short(d.out) || NAMES[op] + '完成'); data.value = d; if (file === selectedPlugin.value) selectedPlugin.value = '' } catch (e) { toast((e as Error).message, true) }
}
async function uploadFile() {
  if (uploading.value) return
  const f = fileEl.value?.files?.[0]
  if (!f) { toast('先选择一个 .smx 文件', true); return }
  if (f.name === selectedPlugin.value && configPanel.value && !configPanel.value.canLeave()) return
  uploading.value = true
  msg.value = '上传中 ' + f.name + '…'
  try { const r = await uploadSmx(f); msg.value = ''; toast('已上传并加载：' + short(r.out)); data.value = r; overlay.value = null; if (fileEl.value) fileEl.value.value = ''; if (f.name === selectedPlugin.value) selectedPlugin.value = '' } catch (e) { msg.value = '失败: ' + (e as Error).message }
  finally { uploading.value = false }
}
</script>

<template>
  <section class="view on">
    <div class="page-actions"><span class="mu">{{ data.enabled.length }} 个启用 · {{ data.disabled.length }} 个禁用</span><button class="g" @click="overlay = 'packs'">{{ packCard?.running ? '插件包安装中…' : '管理插件包' }}</button><button class="g" @click="overlay = 'raw'">运行信息</button><button @click="msg = ''; overlay = 'upload'">上传插件</button></div>
    <div class="card"><h2>插件列表<span class="sp" /><button class="g sm" @click="load">刷新</button></h2>
      <div>
        <div class="tw"><table>
          <tr><th>启用中（plugins/）</th><th /></tr>
          <tr v-for="p in data.enabled" :key="p.file">
            <td><code>{{ p.file }}</code><span v-if="p.protected" class="mu"> 受保护</span></td>
            <td class="act"><button class="g sm" @click="selectPlugin(p.file)">参数</button> <button class="g sm" @click="act('reload', p.file)">重载</button> <button v-if="!p.protected" class="d sm" @click="act('disable', p.file)">禁用</button></td>
          </tr>
          <tr v-if="!data.enabled.length"><td colspan="2" class="mu">没有启用的插件</td></tr>
        </table></div>
        <template v-if="data.disabled.length">
          <div class="k" style="margin:16px 0 6px">已禁用（disabled/）</div>
          <div class="tw"><table>
            <tr v-for="p in data.disabled" :key="p.file">
              <td><code class="mu">{{ p.file }}</code></td>
              <td class="act"><button class="g sm" @click="selectPlugin(p.file)">参数</button> <button class="sm" @click="act('enable', p.file)">启用</button> <button class="d sm" @click="act('delete', p.file)">删除</button></td>
            </tr>
          </table></div>
        </template>
      </div>
      <div class="note">启用 / 禁用 = 移动 disabled/ 目录 + 热加载，立即生效；受保护的核心插件不可禁用、删除。删除只能删已禁用的。</div>
    </div>
    <AppOverlay :open="overlay === 'packs'" title="管理插件包" description="选择最小安装或补充多人、特感与积分功能" kind="drawer" wide keep-mounted :busy="packCard?.busy" @close="overlay = null"><PluginPackCard ref="packCard" /></AppOverlay>
    <AppOverlay :open="overlay === 'upload'" title="上传插件" description="上传 .smx 文件后立即加载" :busy="uploading" @close="overlay = null">
      <form id="plugin-upload" class="form-stack" @submit.prevent="uploadFile"><label>插件文件<input ref="fileEl" type="file" accept=".smx" required :disabled="uploading"></label><p class="hint">单个文件不超过 20 MB；同名插件会被覆盖。</p><p v-if="msg" role="status" class="mu">{{ msg }}</p></form>
      <template #footer><button class="g" :disabled="uploading" @click="overlay = null">取消</button><button type="submit" form="plugin-upload" :disabled="uploading">{{ uploading ? '上传中…' : '上传并加载' }}</button></template>
    </AppOverlay>
    <AppOverlay :open="overlay === 'raw'" title="SourceMod 运行信息" description="sm plugins list 原始输出" kind="drawer" @close="overlay = null"><pre style="max-height:none">{{ data.raw || '(服务器离线或无输出)' }}</pre></AppOverlay>
    <AppOverlay :open="!!selectedPlugin" title="插件参数" :description="selectedPlugin" kind="drawer" wide :before-close="() => configPanel?.canLeave() ?? true" @close="selectedPlugin = ''">
      <PluginConfigPanel v-if="selectedPlugin" :key="selectedPlugin" ref="configPanel" :plugin="selectedPlugin" :disabled="pluginDisabled" />
    </AppOverlay>
  </section>
</template>
