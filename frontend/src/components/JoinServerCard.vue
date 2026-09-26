<script setup lang="ts">
import { computed } from 'vue'
import { session } from '../stores/session'
import { copyText } from '../composables/copyText'
import { toast } from '../composables/useToast'

defineProps<{ compact?: boolean }>()
const st = computed(() => session.status)
const join = computed(() => st.value?.join)
const instructions = computed(() => join.value?.command ? [
  '一起玩 Left 4 Dead 2',
  '1. 在游戏「选项 → 键盘/鼠标」中启用开发者控制台，按 ~ 打开。',
  '2. 如果服务器有进服密码，先输入 password "朋友单独告知的进服密码"；没有密码则输入 password "" 清除客户端旧密码。',
  '3. 输入：' + join.value.command,
  '4. 自定义地图请按作品要求，在每位玩家的客户端安装对应内容。',
  '公网连接尚未验证；连接失败请联系服主检查地址、端口和防火墙。',
].join('\n') : '')
async function copy(value: string) {
  const copied = await copyText(value)
  toast(copied ? '已复制' : '复制失败，请选中下方文本手动复制', !copied)
}
</script>

<template>
  <div v-if="compact" class="join-compact fs">
    <template v-if="join?.command"><span class="k">连接地址</span><code>{{ join.command }}</code><button class="g sm" @click="copy(join.command)">复制</button><RouterLink to="/game">加入说明</RouterLink></template>
    <RouterLink v-else to="/panel">填写朋友连接地址</RouterLink>
  </div>
  <div v-else class="card join-card">
    <h2>邀请朋友加入</h2>
    <div class="join-states" aria-label="连接检查">
      <span>游戏文件：{{ st?.game_installed ? '已安装' : '尚未安装' }}</span>
      <span>本机游戏响应：{{ st?.online ? '正常' : '未确认' }}</span>
      <span>朋友公网连接：尚未验证</span>
    </div>
    <p v-if="!join?.command" class="hint">{{ join?.error || '正在读取游戏地址…' }}。<RouterLink to="/panel">前往面板设置</RouterLink>填写朋友可用的游戏地址。</p>
    <template v-else>
      <p>这是游戏连接地址：<code>{{ join.address }}</code>。进服密码请单独告知朋友。</p>
      <div class="row"><button @click="copy(instructions)">复制完整加入说明</button><button class="g" @click="copy(join.command)">只复制连接命令</button></div>
      <pre tabindex="0" aria-label="可复制的加入说明">{{ instructions }}</pre>
      <details>
        <summary>朋友无法加入时检查什么</summary>
        <ol>
          <li>确认上方游戏已安装并有本机响应；刚保存人数配置时，请先完整重启游戏。</li>
          <li>确认这个域名或 IP 指向游戏服务器；面板网页端口不能作为游戏连接端口。</li>
          <li>云服务器安全组和主机防火墙都要放行游戏端口 <strong>{{ join.port }} / TCP 和 UDP</strong>。<template v-if="join.port !== join.engine_port">如果使用端口映射，外部 {{ join.port }} 需要转发到游戏主机 {{ join.engine_port }}。</template></li>
          <li>家庭网络还需设置路由器端口转发；公网地址、运营商 NAT 和 IPv6 支持需要按实际网络确认。</li>
          <li>核对进服密码、服务器白名单和自定义地图依赖。TCP 检测成功也不能证明 UDP 和真实客户端可用。</li>
        </ol>
      </details>
    </template>
  </div>
</template>

<style scoped>
.join-states { display: flex; flex-wrap: wrap; gap: 12px 24px; color: var(--mu); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; border: 1px solid var(--bd); border-radius: 8px; line-height: 1.8; user-select: text; }
details { margin-top: 14px; } summary { cursor: pointer; } li { margin: 10px 0; }
.join-compact { min-width: 0; flex-wrap: wrap; } .join-compact code { overflow-wrap: anywhere; }
</style>
