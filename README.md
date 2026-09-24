# L4D2 Ops Panel

Left 4 Dead 2 专用服务器的 Web 运维面板。**FastAPI 后端 + Vue 3 前端**，通过 RCON / A2S 控制游戏，可选接入 LinuxGSM 做开关服，手机浏览器也能用。

> A web panel for Left 4 Dead 2 dedicated servers: FastAPI backend, Vue 3 frontend, RCON/A2S based, optional LinuxGSM integration, Chinese UI.

这份 README 面向装面板、用面板的人。想改代码、跑测试、了解结构，看 [docs/development.md](docs/development.md)；开服本身的踩坑在 [docs/l4d2-server-notes.md](docs/l4d2-server-notes.md)。

## 功能

| 页面 | 内容 |
|---|---|
| 概览 | 在线/离线、地图、玩家数、当前预设/难度/白名单状态、Server FPS、出流量、系统负载；FPS 与出流量曲线 |
| 玩家 / 白名单 | 在线玩家（踢出 / 发分 / 加白名单）；白名单开关（带状态、重启保持）与名单增删，SteamID 可填 `STEAM_1:x:y`、`[U:1:x]`、17 位好友码或个人主页链接 |
| 游戏设置 | 游戏模式（5 个基础模式 + 19 个内置突变，分组卡片与中英文搜索，保存默认模式后重载起始地图并核对状态）、特感强度预设（auto / te8 / te12 / te16）、难度（即时生效并高亮）、友伤 / 火焰伤害系数（写入 server.cfg，重启保持）、发放积分（下拉选在线玩家或 @all） |
| 地图 / 战役 | 切图（官方 14 战役 + 已安装 VPK 中的地图）；按创意工坊 ID 或链接下载安装（直连 Steam CDN，多连接分块、失败重试、断点续传、可取消，带进度条）；在创意工坊里按名字搜全部 L4D2 内容、一键安装（需 `steam_api_key`）；上传 vpk 或 zip（zip 自动解压出里面的 vpk，gamemaps.com 下载的压缩包可以直接传）；列出 / 切到第一章 / 打包下载 / 删除，装完热加载不用重启。所有有效 VPK 都可安装，地图选择只显示其中含 `maps/*.bsp` 的文件。|
| 插件 | SourceMod 插件列表，启用 / 禁用 / 重载 / 删除，上传 .smx 即时加载；通用 CFG 参数查看、校验、保存、临时应用、备份恢复；核心插件受保护，不能禁用或删除 |
| 控制台 | 任意 RCON 命令，命令历史 |
| 日志 / 性能 | 控制台日志、SourceMod 报错、性能采样 |
| 服务器 | Docker 一键安装 L4D2；Docker / LinuxGSM 启动、停止、重启与巡检；系统信息 |
| 账号 | 每个人都能改自己的密码、绑定 / 解绑 Steam；owner 还能管理全部账号（建 / 删、改密码、改绑定）。绑定 SteamID 的账号自动写入 `admins_simple.ini` 的面板托管块并热重载游戏管理员 |

没装的组件对应功能会**自动隐藏**（面板通过 `sm plugins list` 探测，每 2 分钟一次）。接口文档在 `/api/docs`（OpenAPI）。

插件的“参数设置”会在 `game_dir/cfg/sourcemod/` 中查找标准 `ConVars for plugin "xxx.smx"` 文件头对应的 CFG；没有插件文件头时，按插件与 CFG 同名匹配。可编辑项须有标准 `// Default: "…"` 注释，支持说明和最小 / 最大值。含执行命令或不支持语法的复杂文件只读，KeyValues 等结构化配置暂不支持，后续可针对插件适配。

页面区分默认值、文件保存值和运行值；运行值需手动查询，每批最多 20 项。可选择“保存配置”“临时应用”或“保存并应用”：保存只改磁盘，应用通过 RCON 逐项设置并回读，显示实际值或失败原因；禁用插件只能保存，启用后再应用。保存不会执行整个 CFG，换图后的值仍取决于插件自己的加载规则。

配置仅支持 UTF-8 / UTF-8 BOM，保留原有注释、缩进和换行；新值须为最多 254 字节的可打印 ASCII，不能含引号、反斜线、分号或控制字符。保存前检查文件版本，每个文件在 `panel/config_backups/` 保留最近 20 份变更前备份；恢复也检查版本，且**只恢复磁盘文件，不修改运行值**。

### 游戏模式

在“游戏设置”的“游戏模式”中通过分组卡片选择模式，支持按中文名、英文名和模式 ID 搜索。模式列表包含 5 个基础模式和 19 个内置突变模式，包括写实对抗（`mutation12`）、生还者对抗（`mutation15`）、绝境求生和孤身一人等。筛选不会改变已选择的切换目标，底部会始终显示目标摘要。确认后先自动备份 `server.cfg`，将所选模式保存为默认模式，再重载起始地图。默认模式在重载和重启后继续使用，当前对局进度会重置。战役、写实和对抗从死亡中心旅馆（`c1m1_hotel`）开始；生存和清道夫从死亡中心中庭（`c1m4_atrium`）开始。突变根据官方基础规则使用旅馆或中庭；“单人房间”（`mutation10`）只适用终章，因此使用中庭。孤身一人、孤胆枪手的原生规则为单人；“单人房间”是多人争夺一个逃生名额，并非单人模式。使用固定起始地图，不提供任意模式与地图的组合。

此功能需要 SourceMod，读取和设置隐藏变量 `mp_gamemode`。页面并列显示默认模式与当前实际模式；配置已保存不代表当前已生效。切换后重新读取模式和地图，连续两次匹配才显示核对完成；重载断线时保留已保存的默认模式并继续查询，不自动重复切换。配置读取异常会禁止保存和切换，但不影响实时状态展示。

配置保存失败时不执行游戏写操作；运行值写入或回读被拒绝时，回滚配置并尝试恢复原运行值，错误说明会报告回滚结果。重载明确被拒绝时也会回滚配置并尝试恢复原运行值；重载断线则无法确认命令是否已执行，保留已保存的默认模式并核对实际状态。

面板会更新 `server.cfg` 中全部直接定义的模式默认值，裸 `mp_gamemode` 指令会改为 `sm_cvar mp_gamemode`，避免旧值或隐藏变量不生效的问题。配置备份位于同目录的 `server.cfg.bak-mode-*`，权限为 0600；未发生配置变化时不新建备份。其他独立执行的配置命令或插件仍可能覆盖模式，可刷新实际状态核对。

2026-09-24 已在真实服务器验证五种模式的保存、地图重载与状态回读，并验证游戏进程重启后仍保持保存的写实模式。测试后已恢复原模式、地图和运行参数。新增 19 个突变的 ID、中文名、基础规则与脚本存在性已只读核对服务器官方资源，尚未逐个实服切换。多特和人数插件可能覆盖内置规则；完整玩法及所有插件的游玩兼容性仍需真人入服验收。

## 要求

- 服务器：Linux + **Python 3.10+**（Ubuntu 22.04 / 24.04 自带 3.10 / 3.12）。Ubuntu 默认没有 venv 模块，先 `sudo apt install python3-venv`；依赖只有 `fastapi` 和 `uvicorn`，装在 `panel/venv/` 里，不碰系统 Python
- 游戏开启 RCON（`server.cfg` 里有 `rcon_password`）
- 可选：LinuxGSM（开关服）、本仓库的 SourceMod 插件（预设 / 白名单）、Points System（发分）；DepotDownloader 只在工坊物品没有直链时作回退，绝大多数 L4D2 地图不需要
- 开发机（改前端时才需要）：Node.js 20+，用来把 `frontend/` 构建成静态文件；服务器上不需要 Node

## 安装

前端是构建产物，仓库里不带，所以先在开发机构建，再把 `panel/` 整个目录放到服务器：

```bash
git clone https://github.com/KilimiaoSix/l4d2-ops-panel.git
cd l4d2-ops-panel/frontend && npm ci && npm run build     # 产物写入 ../panel/l4d2panel/static/
rsync -a --exclude venv --exclude tests --exclude devenv --exclude panel.json --exclude 'panel.db*' --exclude config_backups/ --exclude docker/ ../panel/ l4d2server@<服务器>:/home/l4d2server/panel/
```

服务器上（以运行游戏的用户执行）：

```bash
cd /home/l4d2server/panel
./install.sh          # 建 venv 装依赖；交互式填路径，自动生成密码、证书和 systemd 服务
```

国内主机 pip 慢，先 `export PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple` 再跑 `install.sh`。

装完在云防火墙放行面板端口（默认 TCP 8443），浏览器打开 `https://<服务器IP或域名>:8443/`。第一次打开面板会要求给 owner 账号（默认 `admin`，即 `bootstrap_user`）设置密码，设完直接进入面板，之后就是正常登录；安装时也可以预先填一个密码，那样首次启动直接用它建账号。改密码、加账号都在“账号”页。忘记密码：停掉面板，删掉 `panel.db`（账号、会话和审计记录一起清空），再启动后重新走一次初始化。自签名证书首次会有一次警告；换成正式证书只需替换 `cert.pem` / `key.pem` 后 `systemctl restart l4d2panel`。

想放在 nginx 后面：安装时选“方式 2”，参考 `panel/nginx.example.conf`。反代必须把 `X-Real-IP` 传给面板（示例里已有），登录失败限速按这个头识别来源 IP。

### 更新与回滚

更新：开发机 `npm run build` → 同 rsync 一次 → 服务器 `venv/bin/pip install -r requirements.txt`（依赖版本变了才需要）→ `sudo systemctl restart l4d2panel`。`panel.json`、`panel.db`、证书和 `config_backups/` 都在 `panel/` 目录里，rsync 时排除即可保留。

回滚：`panel.py` 只是入口，把整个 `panel/` 目录换回上一版再 restart 即可；`panel.db` 的表结构与早期单文件版一致，来回切换都能直接用。带备份、冒烟检查的完整发布步骤见 [docs/development.md](docs/development.md#发布到服务器)。

## 配置 `panel/panel.json`

| 键 | 说明 |
|---|---|
| `password` | 可留空。留空则第一次打开面板时在网页上设置 owner 密码；填了则首次启动直接用它建出 owner 账号。只在建库时用一次，之后改密码在“账号”页 |
| `db` / `bootstrap_user` | SQLite 文件（账号 / 会话 / 审计，默认 `panel.db`，相对路径相对于 panel.py 所在目录）、首次启动建出的 owner 账号名（默认 `admin`） |
| `port` / `bind` / `tls` / `cert` / `key` | 监听端口、地址、是否自带 HTTPS、证书路径 |
| `rcon_host` / `rcon_port` / `rcon_password` | RCON 地址。`rcon_password` 留空则自动读 `game_dir/cfg/server.cfg`。LinuxGSM / 原生服填服务器网卡 IP（L4D2 不回应直发到 127.0.0.1 的查询）；本面板安装的 Docker 服通过已发布的本机端口连接，自动配置 |
| `game_dir` | `…/serverfiles/left4dead2` |
| `lgsm_script` | LinuxGSM 实例脚本；仅 LinuxGSM 模式下留空会隐藏开关服按钮，Docker 使用自己的控制接口 |
| `console_log` / `perf_csv` | LinuxGSM 的控制台日志、性能采样文件，不存在则隐藏对应功能；Docker 使用容器日志与 RCON 采样 |
| `depotdownloader` | [DepotDownloader](https://github.com/SteamRE/DepotDownloader) 路径，仅作工坊下载的回退（物品没有直链时），可留空 |
| `workshop_connections` / `workshop_retries` | 工坊下载的并发连接数（默认 8）和每个 8 MB 分块的最大重试次数（默认 8）。下载中断或取消后已完成的分块保留在 `workshop_tmp/`，再点一次会续传 |
| `steam_api_base` / `steam_community_base` | 查询工坊物品的 Steam Web API 地址（默认 `https://api.steampowered.com`）、解析 `/id/自定义名` 用的社区地址（默认 `https://steamcommunity.com`），需要走镜像 / 代理时改这里 |
| `steam_api_key` | Steam Web API Key（免费，登录 Steam 后在 https://steamcommunity.com/dev/apikey 申请，域名随便填）。填了才会显示“搜索创意工坊”卡片；只在服务器上用来调 `IPublishedFileService/QueryFiles`，不会出现在页面里。留空则只能按 ID / 链接下载 |
| `panel_title` / `display_host` | 标题、对外显示的连接地址 |
| `max_upload_mb` / `protected_addons` | 上传上限、不允许删除的 vpk |
| `protected_plugins` | 插件页里不允许禁用 / 删除的插件名（不带 `.smx`） |
| `server_backend` | 默认 `lgsm`；Docker 安装成功后自动接管并持久化，无需手改此项 |
| `docker_project` / `install_dir` | Docker 项目名（默认 `l4d2-panel`）与配置目录（默认面板目录下的 `docker/`，相对路径按面板目录解析）。一个项目名只对应一个安装目录 |

### 在当前面板安装 Docker 游戏服

服务器页填写游戏端口，选择 Tick、VAC 和镜像源后点“开始安装”。镜像参考 [LaoYutang/l4d2-server-next](https://github.com/LaoYutang/l4d2-server-next)，只运行 `l4d2-pure` 游戏容器，继续使用当前面板的账号和界面。默认镜像源为 `docker.cnb.cool`，清空表示 Docker Hub。

主机需要安装 Docker Engine / Docker Desktop 与 Compose，运行面板的用户需要能访问**本机** Docker daemon、写入 `game_dir` 和 `install_dir`。生产环境推荐 Linux x86_64；游戏镜像固定 `linux/amd64`，ARM 主机能运行 Docker 不代表能运行 32 位 L4D2 引擎。默认 30 Tick，更高 Tick 需要游戏内对应扩展，安装器不会自动安装扩展。

首次安装要求 `game_dir` 为空或不存在。安装器先把镜像内游戏文件复制到临时目录，校验后写入随机 RCON 密码并原子移到 `game_dir`；按面板用户 UID/GID 运行，地图、插件、配置在主机和容器间共享。已有 LinuxGSM 目录、无关 Compose 文件或另一个安装占用的同名 Docker 项目都会拒绝覆盖。安装失败可以重试；取消不删除游戏数据，也不撤销已经完成的容器操作。

安装成功后自动把当前面板的 RCON/A2S 连接切到本机游戏端口，从 `server.cfg` 读取密码。面板重启时读取 `install_dir/installed.json` 恢复连接；`panel.json` 不必手改。启动、停止、重启和日志读取均作用于该安装的 `l4d2` 服务；Docker 巡检只查询状态，不会拉起已停止的游戏。游戏端口需同时放行 TCP/UDP。

重启使用面板生成的启动脚本，读取已保存的游戏模式并选对应起始地图，保留 `server.cfg`，不会调用上游每次覆盖配置的启动脚本。RCON 操作、地图管理、插件文件管理和账号管理沿用现有接口；SourceMod、白名单、特感预设、积分等能力仍需安装对应插件，面板按实际检测显示。

Docker 控制台取容器日志；性能通过 RCON 的 `stats` / `status` 读取，每 15 秒最多采样一次，缓存最近 120 条。采样由页面请求触发，面板重启清空，不依赖 LinuxGSM 的 tmux / CSV 采样脚本。系统负载仍指面板所在主机，非游戏容器限额。

“已安装”表示安装文件及配置完整；“容器运行中”和“游戏在线”分别检查 Docker 与 A2S/RCON，不把启动容器当成可入服。此入口只负责首次安装和未完成任务重试，不提供覆盖重装或游戏更新。保留 `docker/`、`game_dir` 及其面板标记文件；不要用旧版双管理器 Compose 覆盖本安装器生成的配置。

## 配套内容

- `sourcemod/scripting/sipreset.sp` — 特感强度预设 `!preset auto|te8|te12|te16`，基于 [Infected Bots](https://github.com/fbef0102/L4D1_2-Plugins/tree/master/l4dinfectedbots) 的 `l4d_infectedbots_read_data` 切换数据文件；数据文件用 `tools/gen_ib_presets.py` 生成
- `sourcemod/scripting/sm_whitelist.sp` — 无密码私人服白名单：`!wl_add` `!wl_addid` `!wl_del` `!wl_list`，管理员自动放行，名单为空 = 对所有人开放，开关状态持久化
- `tools/perf-sampler.sh` — 有人在线时每 15 秒记录 `stats`（fps / 流量），面板画曲线
- 难度切换会额外执行 `l4d2_force_difficulty <难度>`，供本地的 Force Difficulty 插件跨换图锁定难度（该插件暂未收录进本仓库）；没装时这条命令的报错被忽略，不影响 `z_difficulty` 的设置
- `docs/l4d2-server-notes.md` — L4D2 开服踩坑笔记（cfg 不能有非 ASCII、SteamCMD 匿名下载 bug、SourceMod 在 L4D2 上的几个不触发……）

编译插件：把 `.sp` 放到 `addons/sourcemod/scripting/` 后 `./spcomp64 xxx.sp -o ../plugins/xxx.smx`。

## 安全说明

- 账号分 owner / admin：“账号”页人人可见，能改自己的密码和 Steam 绑定（改密码会登出其他设备）；owner 还能建 / 删账号、改别人的密码和绑定。其余功能两者一样，登录即拥有服务器全部操作权限，别给不该给的人；密码以 PBKDF2-SHA256 存在 `panel.db`，同 IP 连续 6 次失败锁 1 分钟，会话 7 天；登录、账号、插件、RCON、踢人、切图、设置、白名单、战役、开关服等所有写操作都记入 `panel.db` 的 audit 表
- 初始化页面在第一个账号建立之前对所有能打开面板的人开放，装好后尽快打开面板把密码设掉
- 请用 HTTPS（自带自签名或 nginx + 正式证书）；HTTP 明文在公共网络会泄露密码。面板自带 TLS 或反代带 `X-Forwarded-Proto: https` 时会话 cookie 带 `Secure`
- 页面上所有来自游戏的数据（玩家名、地图名、插件输出、工坊搜索结果）只经模板插值渲染，不拼 HTML，不用 `v-html`
- 面板只在你自己的服务器上运行，不上报任何东西；除主动安装时 Docker 拉取所选镜像源外，面板的对外请求包括：创意工坊（搜索和查询走 Steam Web API、从 Steam CDN 拉文件，或回退 DepotDownloader）和把 `steamcommunity.com/id/自定义名` 解析成 SteamID（只在你填了这种链接时发生）。搜索结果里的缩略图由**浏览器**直接从 Steam 的图片 CDN 加载，加载不到就不显示
- 面板不会去 gamemaps.com 抓文件：那个站用 Cloudflare 拦掉了所有非浏览器客户端。在自己的浏览器里下载它的 zip，再从“地图 / 战役”页上传即可
- 页面会让**浏览器**从 Google Fonts 异步加载两款字体（Barlow Condensed / IBM Plex Mono）作为渐进增强，加载不到就回退到系统字体、不阻塞显示；不想要的话删掉 `frontend/index.html` 里 `fonts.googleapis.com` 的 `<link>` 再构建即可

## 许可

MIT
