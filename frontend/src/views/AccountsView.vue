<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { bindSteam, changePassword, createAccount, deleteAccount, getAccounts, getMe, updateAccount } from '../api/endpoints'
import type { Account, Me } from '../api/types'
import AppOverlay from '../components/AppOverlay.vue'
import { run, toast } from '../composables/useToast'
import { session } from '../stores/session'

const me = ref<Me | null>(null), steam = ref(''), cur = ref(''), nw = ref(''), nw2 = ref('')
const accounts = ref<Account[]>([]), meName = ref('')
const blankAccount = () => ({ username: '', password: '', role: 'admin', steamid: '', flags: '99:z' })
const na = ref(blankAccount())
const active = ref<'password' | 'steam' | 'create' | 'edit' | null>(null), busy = ref(false), error = ref('')
const editing = ref<Account | null>(null), editSteam = ref(''), editPassword = ref('')
const titles = { password: '修改密码', steam: '绑定 Steam', create: '新建账号', edit: '编辑账号' }
function open(kind: NonNullable<typeof active.value>, account?: Account) {
  error.value = ''; active.value = kind
  if (kind === 'password') cur.value = nw.value = nw2.value = ''
  if (kind === 'steam') steam.value = me.value?.steamid || ''
  if (kind === 'create') na.value = blankAccount()
  if (account) { editing.value = account; editSteam.value = account.steamid || ''; editPassword.value = '' }
}
async function loadMe() { try { me.value = await getMe() } catch (e) { toast((e as Error).message, true) } }
async function loadAccounts() { try { const d = await getAccounts(); accounts.value = d.accounts; meName.value = d.me } catch (e) { toast((e as Error).message, true) } }
onMounted(() => { void loadMe(); if (session.role === 'owner') void loadAccounts() })
watch(() => session.role, r => { if (r === 'owner') void loadAccounts() })

async function submit() {
  if (busy.value) return
  error.value = ''
  if (active.value === 'password' && nw.value !== nw2.value) { error.value = '两次输入的新密码不一致'; return }
  busy.value = true
  try {
    if (active.value === 'password') {
      await changePassword(cur.value, nw.value); toast('密码已修改'); cur.value = nw.value = nw2.value = ''
    } else if (active.value === 'steam') {
      const value = steam.value.trim(); await bindSteam(value); toast(value ? '已绑定 Steam' : '已解绑')
    } else if (active.value === 'create') {
      const value = { ...na.value, username: na.value.username.trim(), steamid: na.value.steamid.trim(), flags: na.value.flags.trim() }
      if (!value.username) { error.value = '请填写用户名'; return }
      await createAccount(value); toast('已创建账号 ' + value.username); na.value = blankAccount()
    } else if (active.value === 'edit' && editing.value) {
      const body: { id: number; steamid: string; password?: string } = { id: editing.value.id, steamid: editSteam.value.trim() }
      if (editPassword.value) body.password = editPassword.value
      await updateAccount(body); toast('已保存 ' + editing.value.username); editPassword.value = ''
    }
    active.value = null
    void loadMe(); if (session.role === 'owner') void loadAccounts()
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
async function del(a: Account) {
  if (!confirm('删除账号 ' + a.username + '？')) return
  try { await run(() => deleteAccount(a.id), '已删除 ' + a.username); void loadAccounts() } catch { /* toasted */ }
}
const when = (t: number | null) => t ? new Date(t * 1000).toLocaleString() : '—'
</script>

<template>
  <section class="view on">
    <div class="card">
      <div class="summary-row">
        <div class="summary-copy"><h2>我的账号 <span class="mu">{{ me?.role }}</span></h2><p><b>{{ me?.username || session.user }}</b> <span class="mu"> · {{ me?.steamid || '尚未绑定 Steam' }}</span></p></div>
        <div class="summary-actions"><button class="g" @click="open('password')">修改密码</button><button class="g" @click="open('steam')">{{ me?.steamid ? '管理 Steam 绑定' : '绑定 Steam' }}</button></div>
      </div>
    </div>
    <div v-if="session.role === 'owner'" class="card"><h2>面板账号 <span class="mu">{{ accounts.length }} 个账号</span><span class="sp" /><button class="g sm" @click="loadAccounts">刷新</button><button class="sm" @click="open('create')">新建账号</button></h2>
      <div class="tw"><table>
        <tr><th>用户名</th><th>角色</th><th>绑定 SteamID</th><th>权限</th><th>最近登录</th><th>操作</th></tr>
        <tr v-for="a in accounts" :key="a.id">
          <td><b>{{ a.username }}</b><span v-if="a.username === meName" class="mu"> (我)</span></td><td>{{ a.role }}</td>
          <td><code class="mu">{{ a.steamid || '—' }}</code></td><td class="mu">{{ a.flags || '' }}</td><td class="mu">{{ when(a.last_login) }}</td>
          <td class="act"><button class="g sm" @click="open('edit', a)">编辑</button> <button v-if="a.username !== meName" class="d sm" @click="del(a)">删除</button></td>
        </tr>
      </table></div>
      <div class="note">owner 可管理所有账号。绑定 Steam 后自动同步游戏管理员权限。</div>
    </div>
    <AppOverlay :open="!!active" :title="active ? titles[active] : ''" :description="active === 'edit' ? editing?.username : undefined" :busy="busy" @close="active = null">
      <form id="account-form" class="form-stack" @submit.prevent="submit">
        <template v-if="active === 'password'">
          <label>当前密码<input v-model="cur" type="password" autocomplete="current-password" required :disabled="busy"></label>
          <label>新密码<input v-model="nw" type="password" autocomplete="new-password" required :disabled="busy"></label>
          <label>确认新密码<input v-model="nw2" type="password" autocomplete="new-password" required :disabled="busy"></label>
          <p class="hint">修改后，其他设备上的登录会失效。</p>
        </template>
        <template v-else-if="active === 'steam'">
          <label>SteamID 或个人主页链接<input v-model="steam" placeholder="SteamID / 主页链接 / 17 位好友码" :disabled="busy"></label>
          <p class="hint">留空保存即可解绑。绑定后会写入游戏管理员并热重载。</p>
        </template>
        <template v-else-if="active === 'create'">
          <label>用户名<input v-model="na.username" autocomplete="off" required :disabled="busy"></label>
          <label>密码<input v-model="na.password" type="password" autocomplete="new-password" required :disabled="busy"></label>
          <div class="form-fields"><label>面板角色<select v-model="na.role" :disabled="busy"><option value="admin">admin</option><option value="owner">owner</option></select></label><label>游戏权限<input v-model="na.flags" placeholder="99:z" :disabled="busy"></label></div>
          <label>绑定 Steam（可选）<input v-model="na.steamid" placeholder="SteamID / 主页链接 / 17 位好友码" :disabled="busy"></label>
          <p class="hint">权限位 z 表示全部管理员权限，数字为免疫等级；留空默认 99:z。</p>
        </template>
        <template v-else-if="active === 'edit'">
          <label>绑定 Steam<input v-model="editSteam" placeholder="留空保存即可解绑" :disabled="busy"></label>
          <label>新密码<input v-model="editPassword" type="password" autocomplete="new-password" placeholder="留空保持原密码" :disabled="busy"></label>
          <p class="hint">Steam 绑定修改后会自动同步游戏管理员。</p>
        </template>
        <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      </form>
      <template #footer><button class="g" :disabled="busy" @click="active = null">取消</button><button type="submit" form="account-form" :disabled="busy">{{ busy ? '保存中…' : active === 'create' ? '创建账号' : '保存' }}</button></template>
    </AppOverlay>
  </section>
</template>
