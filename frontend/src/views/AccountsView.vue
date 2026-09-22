<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { bindSteam, changePassword, createAccount, deleteAccount, getAccounts, getMe, updateAccount } from '../api/endpoints'
import type { Account, Me } from '../api/types'
import { run, toast } from '../composables/useToast'
import { session } from '../stores/session'

const me = ref<Me | null>(null), steam = ref(''), cur = ref(''), nw = ref(''), nw2 = ref('')
const accounts = ref<Account[]>([]), meName = ref('')
const na = ref({ username: '', password: '', role: 'admin', steamid: '', flags: '99:z' })

async function loadMe() { try { me.value = await getMe(); steam.value = me.value.steamid || '' } catch { /* toasted elsewhere */ } }
async function loadAccounts() { try { const d = await getAccounts(); accounts.value = d.accounts; meName.value = d.me } catch (e) { toast((e as Error).message, true) } }
onMounted(() => { void loadMe(); if (session.role === 'owner') void loadAccounts() })
watch(() => session.role, r => { if (r === 'owner') void loadAccounts() })

async function changePw() {
  if (!cur.value || !nw.value) { toast('填写当前密码和新密码', true); return }
  if (nw.value !== nw2.value) { toast('两次输入的新密码不一致', true); return }
  try { await run(() => changePassword(cur.value, nw.value), '密码已修改'); cur.value = nw.value = nw2.value = '' } catch { /* toasted */ }
}
async function bind() {
  const v = steam.value.trim()
  try { await run(() => bindSteam(v), v ? '已绑定 Steam' : '已解绑'); void loadMe(); if (session.role === 'owner') void loadAccounts() } catch { /* toasted */ }
}
async function create() {
  const o = { ...na.value, username: na.value.username.trim(), steamid: na.value.steamid.trim(), flags: na.value.flags.trim() }
  if (!o.username || !o.password) { toast('填写用户名和密码', true); return }
  try { await run(() => createAccount(o), '已创建账号 ' + o.username); na.value = { ...na.value, username: '', password: '', steamid: '' }; void loadAccounts() } catch { /* toasted */ }
}
async function edit(a: Account) {
  const steamid = prompt('绑定 Steam（留空 = 解绑；绑定后写入游戏管理员）\n支持 SteamID / 主页链接 / 17位好友码：', a.steamid || '')
  if (steamid === null) return
  const pw = prompt('设置新密码（留空 = 不改）：', '')
  if (pw === null) return
  const body: { id: number; steamid: string; password?: string } = { id: a.id, steamid: steamid.trim() }
  if (pw) body.password = pw
  try { await run(() => updateAccount(body), '已保存 ' + a.username); void loadAccounts() } catch { /* toasted */ }
}
async function del(a: Account) {
  if (!confirm('删除账号 ' + a.username + '？')) return
  try { await run(() => deleteAccount(a.id), '已删除 ' + a.username); void loadAccounts() } catch { /* toasted */ }
}
const when = (t: number | null) => t ? new Date(t * 1000).toLocaleString() : '—'
</script>

<template>
  <section class="view on">
    <div class="card"><h2>我的账号<span class="sp" /><span class="mu">{{ me ? me.username + ' · ' + me.role + (me.steamid ? ' · ' + me.steamid : '') : '' }}</span></h2>
      <div class="row"><input v-model="cur" type="password" placeholder="当前密码" autocomplete="current-password" style="width:140px"><input v-model="nw" type="password" placeholder="新密码" autocomplete="new-password" style="width:140px"><input v-model="nw2" type="password" placeholder="再输一次新密码" autocomplete="new-password" style="width:150px"><button @click="changePw">修改密码</button></div>
      <div class="row"><input v-model="steam" placeholder="绑定 Steam（留空 = 解绑）：SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:200px"><button @click="bind">保存绑定</button></div>
      <div class="hint">改密码后其他设备上的登录会失效；绑定 Steam 后会写入游戏管理员（admins_simple.ini 的面板托管块）并热重载。</div>
    </div>
    <template v-if="session.role === 'owner'">
      <div class="card"><h2>面板账号<span class="sp" /><button class="g sm" @click="loadAccounts">刷新</button></h2>
        <div class="hint" style="margin:0 0 10px">owner 可管理账号。绑定 SteamID 后，该账号会自动写入游戏管理员（admins_simple.ini 的面板托管块）并热重载，一处管两边。</div>
        <div class="tw"><table>
          <tr><th>用户名</th><th>角色</th><th>绑定 SteamID</th><th>权限</th><th>最近登录</th><th /></tr>
          <tr v-for="a in accounts" :key="a.id">
            <td><b>{{ a.username }}</b><span v-if="a.username === meName" class="mu"> (我)</span></td><td>{{ a.role }}</td>
            <td><code class="mu">{{ a.steamid || '—' }}</code></td><td class="mu">{{ a.flags || '' }}</td><td class="mu">{{ when(a.last_login) }}</td>
            <td class="act"><button class="g sm" @click="edit(a)">编辑</button> <button v-if="a.username !== meName" class="d sm" @click="del(a)">删除</button></td>
          </tr>
        </table></div>
      </div>
      <div class="card"><h2>新建账号</h2>
        <div class="row"><input v-model="na.username" placeholder="用户名" style="width:140px"><input v-model="na.password" type="password" placeholder="密码" style="width:140px"><select v-model="na.role" style="width:96px"><option value="admin">admin</option><option value="owner">owner</option></select></div>
        <div class="row"><input v-model="na.steamid" placeholder="绑定 Steam（可空）：SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:200px"><input v-model="na.flags" style="width:86px"><button @click="create">创建</button></div>
        <div class="hint">绑定 Steam 支持：<code>STEAM_1:1:xxx</code>、<code>[U:1:xxx]</code>、17 位好友码、<code>steamcommunity.com/profiles/…</code> 或 <code>/id/自定义名</code>（自定义名需服务器能连 steamcommunity）。权限位：<code>z</code>=全部管理员权限，前面的数字是免疫等级；留空默认 <code>99:z</code>。</div>
      </div>
    </template>
  </section>
</template>
