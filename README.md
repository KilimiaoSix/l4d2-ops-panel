# L4D2 Ops Panel

Left 4 Dead 2 专用服务器的轻量 Web 运维面板。**单文件 Python 3，零依赖**，通过 RCON / A2S 控制游戏，可选接入 LinuxGSM 做开关服，手机浏览器也能用。

> A single-file, dependency-free web panel for Left 4 Dead 2 dedicated servers (RCON/A2S based, optional LinuxGSM integration, Chinese UI).

## 功能

| 页面 | 内容 |
|---|---|
| 概览 | 在线/离线、地图、玩家数、当前预设/难度/白名单状态、Server FPS、出流量、系统负载；FPS 与出流量曲线 |
| 玩家 / 白名单 | 在线玩家（踢出 / 发分 / 加白名单）；白名单开关（带状态、重启保持）与名单增删，SteamID 可填 `STEAM_1:x:y`、`[U:1:x]`、17 位好友码或个人主页链接 |
| 游戏设置 | 特感强度预设（auto / te8 / te12 / te16）、难度（即时生效并高亮）、友伤 / 火焰伤害系数（写入 server.cfg，重启保持）、发放积分（下拉选在线玩家或 @all） |
| 地图 / 战役 | 切图（官方 14 战役 + 已安装自定义战役）；按创意工坊 ID 下载安装、上传 vpk、列出 / 切到第一章 / 打包下载 / 删除，装完热加载不用重启 |
| 插件 | SourceMod 插件列表，启用 / 禁用 / 重载 / 删除，上传 .smx 即时加载；核心插件受保护，不能禁用或删除 |
| 控制台 | 任意 RCON 命令，命令历史 |
| 日志 / 性能 | 控制台日志、SourceMod 报错、性能采样 |
| 服务器 | 启动 / 停止 / 重启 / 巡检（LinuxGSM）、系统信息 |
| 账号 | （仅 owner 可见）面板多账号管理；账号绑定 SteamID 后自动写入 `admins_simple.ini` 的面板托管块并热重载游戏管理员 |

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

装完在云防火墙放行面板端口（默认 TCP 8443），浏览器打开 `https://<服务器IP或域名>:8443/`。登录用户名是 `admin`（`bootstrap_user`），密码是安装脚本打印的那个：首次启动会用它建出 owner 账号，之后改密码、加账号都在“账号”页，`panel.json` 里的 `password` 只在建库时用一次。自签名证书首次会有一次警告；换成正式证书只需替换 `cert.pem` / `key.pem` 后 `systemctl restart l4d2panel`。

想放在 nginx 后面：安装时选“方式 2”，参考 `panel/nginx.example.conf`。反代必须把 `X-Real-IP` 传给面板（示例里已有），登录失败限速按这个头识别来源 IP。

## 配置 `panel/panel.json`

| 键 | 说明 |
|---|---|
| `password` | 首次启动建库时给 `bootstrap_user` 账号用的初始密码（安装脚本自动生成），之后改密码在“账号”页 |
| `db` / `bootstrap_user` | SQLite 文件（账号 / 会话 / 审计，默认 `panel.db`，相对路径相对于 panel.py 所在目录）、首次启动建出的 owner 账号名（默认 `admin`） |
| `port` / `bind` / `tls` / `cert` / `key` | 监听端口、地址、是否自带 HTTPS、证书路径 |
| `rcon_host` / `rcon_port` / `rcon_password` | RCON 地址。`rcon_password` 留空则自动读 `game_dir/cfg/server.cfg`。**注意 L4D2 不回应发到 127.0.0.1 的查询，填服务器网卡 IP** |
| `game_dir` | `…/serverfiles/left4dead2` |
| `lgsm_script` | LinuxGSM 实例脚本，留空则隐藏开关服按钮 |
| `console_log` / `perf_csv` | 控制台日志、性能采样文件，不存在则隐藏对应功能 |
| `depotdownloader` | [DepotDownloader](https://github.com/SteamRE/DepotDownloader) 路径，用于创意工坊下载 |
| `panel_title` / `display_host` | 标题、对外显示的连接地址 |
| `max_upload_mb` / `protected_addons` | 上传上限、不允许删除的 vpk |
| `protected_plugins` | 插件页里不允许禁用 / 删除的插件名（不带 `.smx`） |

## 配套内容

- `sourcemod/scripting/sipreset.sp` — 特感强度预设 `!preset auto|te8|te12|te16`，基于 [Infected Bots](https://github.com/fbef0102/L4D1_2-Plugins/tree/master/l4dinfectedbots) 的 `l4d_infectedbots_read_data` 切换数据文件；数据文件用 `tools/gen_ib_presets.py` 生成
- `sourcemod/scripting/sm_whitelist.sp` — 无密码私人服白名单：`!wl_add` `!wl_addid` `!wl_del` `!wl_list`，管理员自动放行，名单为空 = 对所有人开放，开关状态持久化
- `tools/perf-sampler.sh` — 有人在线时每 15 秒记录 `stats`（fps / 流量），面板画曲线
- `tools/check_log_message.py` — 面板日志过滤的回归检查（http.server 自身的 send_error / 超时日志不再触发 TypeError）：`python3 tools/check_log_message.py`，退出码 0 即通过
- 难度切换会额外执行 `l4d2_force_difficulty <难度>`，供本地的 Force Difficulty 插件跨换图锁定难度（该插件暂未收录进本仓库）；没装时这条命令的报错被忽略，不影响 `z_difficulty` 的设置
- `docs/l4d2-server-notes.md` — L4D2 开服踩坑笔记（cfg 不能有非 ASCII、SteamCMD 匿名下载 bug、SourceMod 在 L4D2 上的几个不触发……）

编译插件：把 `.sp` 放到 `addons/sourcemod/scripting/` 后 `./spcomp64 xxx.sp -o ../plugins/xxx.smx`。

## 安全说明

- 账号分 owner / admin：owner 多一个“账号”页（建 / 删账号、改密码、绑 SteamID），其余功能两者一样，登录即拥有服务器全部操作权限，别给不该给的人；密码以 PBKDF2-SHA256 存在 `panel.db`，同 IP 连续 6 次失败锁 1 分钟，会话 7 天；登录、账号和插件操作记入 `panel.db` 的 audit 表
- 请用 HTTPS（自带自签名或 nginx + 正式证书）；HTTP 明文在公共网络会泄露密码
- 面板只在你自己的服务器上运行，不上报任何东西；对外的网络请求只有两类：创意工坊下载（DepotDownloader 连 Steam）和把 `steamcommunity.com/id/自定义名` 解析成 SteamID（只在你填了这种链接时发生）

## 许可

MIT
