# L4D2 Ops Panel

Left 4 Dead 2 专用服务器的轻量 Web 运维面板。**单文件 Python 3，零依赖**，通过 RCON / A2S 控制游戏，可选接入 LinuxGSM 做开关服，手机浏览器也能用。

> A single-file, dependency-free web panel for Left 4 Dead 2 dedicated servers (RCON/A2S based, optional LinuxGSM integration, Chinese UI).

## 功能

| 页面 | 内容 |
|---|---|
| 概览 | 在线/离线、地图、玩家数、当前预设/难度/白名单状态、Server FPS、出流量、系统负载；FPS 与出流量曲线 |
| 玩家 / 白名单 | 在线玩家（踢出 / 发分 / 加白名单）；白名单开关（带状态、重启保持）与名单增删 |
| 游戏设置 | 特感强度预设（auto / te8 / te12 / te16）、难度（即时生效并高亮）、发放积分（下拉选在线玩家或 @all） |
| 地图 / 战役 | 切图（官方 14 战役 + 已安装自定义战役）；按创意工坊 ID 下载安装、上传 vpk、列出 / 切到第一章 / 删除，装完热加载不用重启 |
| 控制台 | 任意 RCON 命令，命令历史 |
| 日志 / 性能 | 控制台日志、SourceMod 报错、性能采样 |
| 服务器 | 启动 / 停止 / 重启 / 巡检（LinuxGSM）、系统信息 |

没装的组件对应功能会**自动隐藏**（面板启动时通过 `sm plugins list` 探测）。

## 要求

- Linux + Python 3.8+（服务器自带即可，不装任何库）
- 游戏开启 RCON（`server.cfg` 里有 `rcon_password`）
- 可选：LinuxGSM（开关服）、DepotDownloader（工坊下载）、本仓库的 SourceMod 插件（预设 / 白名单）、Points System（发分）

## 安装

```bash
git clone https://github.com/KilimiaoSix/l4d2-ops-panel.git
cd l4d2-ops-panel/panel
./install.sh          # 以运行游戏的用户执行；交互式填路径，自动生成密码、证书和 systemd 服务
```

装完在云防火墙放行面板端口（默认 TCP 8443），浏览器打开 `https://<服务器IP或域名>:8443/`。自签名证书首次会有一次警告；换成正式证书只需替换 `cert.pem` / `key.pem` 后 `systemctl restart l4d2panel`。

想放在 nginx 后面：安装时选“方式 2”，参考 `panel/nginx.example.conf`。

## 配置 `panel/panel.json`

| 键 | 说明 |
|---|---|
| `password` | 登录密码（安装脚本自动生成） |
| `port` / `bind` / `tls` / `cert` / `key` | 监听端口、地址、是否自带 HTTPS、证书路径 |
| `rcon_host` / `rcon_port` / `rcon_password` | RCON 地址。`rcon_password` 留空则自动读 `game_dir/cfg/server.cfg`。**注意 L4D2 不回应发到 127.0.0.1 的查询，填服务器网卡 IP** |
| `game_dir` | `…/serverfiles/left4dead2` |
| `lgsm_script` | LinuxGSM 实例脚本，留空则隐藏开关服按钮 |
| `console_log` / `perf_csv` | 控制台日志、性能采样文件，不存在则隐藏对应功能 |
| `depotdownloader` | [DepotDownloader](https://github.com/SteamRE/DepotDownloader) 路径，用于创意工坊下载 |
| `panel_title` / `display_host` | 标题、对外显示的连接地址 |
| `max_upload_mb` / `protected_addons` | 上传上限、不允许删除的 vpk |

## 配套内容

- `sourcemod/scripting/sipreset.sp` — 特感强度预设 `!preset auto|te8|te12|te16`，基于 [Infected Bots](https://github.com/fbef0102/L4D1_2-Plugins/tree/master/l4dinfectedbots) 的 `l4d_infectedbots_read_data` 切换数据文件；数据文件用 `tools/gen_ib_presets.py` 生成
- `sourcemod/scripting/sm_whitelist.sp` — 无密码私人服白名单：`!wl_add` `!wl_addid` `!wl_del` `!wl_list`，管理员自动放行，名单为空 = 对所有人开放，开关状态持久化
- `tools/perf-sampler.sh` — 有人在线时每 15 秒记录 `stats`（fps / 流量），面板画曲线
- `docs/l4d2-server-notes.md` — L4D2 开服踩坑笔记（cfg 不能有非 ASCII、SteamCMD 匿名下载 bug、SourceMod 在 L4D2 上的几个不触发……）

编译插件：把 `.sp` 放到 `addons/sourcemod/scripting/` 后 `./spcomp64 xxx.sp -o ../plugins/xxx.smx`。

## 安全说明

- 密码 = 全部权限（没有分级），别给不该给的人；同 IP 连续 5 次失败锁 1 分钟，会话 7 天
- 请用 HTTPS（自带自签名或 nginx + 正式证书）；HTTP 明文在公共网络会泄露密码
- 面板只在你自己的服务器上运行，不联网上报任何东西

## 许可

MIT
