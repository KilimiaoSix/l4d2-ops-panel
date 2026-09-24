# 开发文档

面向改代码的人：结构、本地环境、测试、构建、发布。安装与使用见 [README](../README.md)。

## 总体结构

```
浏览器（Vue SPA） ──HTTPS──▶ nginx（可选） ──▶ panel.py / uvicorn（FastAPI）
                                                 ├─ RCON TCP / A2S UDP ──▶ srcds
                                                 ├─ subprocess ──▶ LinuxGSM / pgrep、Docker Compose
                                                 ├─ 文件系统：addons/、sourcemod/plugins/、server.cfg、admins_simple.ini、whitelist.txt、日志、perf CSV
                                                 ├─ HTTPS ──▶ Steam Web API / Steam CDN（工坊）、steamcommunity（解析自定义主页名）
                                                 └─ SQLite panel.db（账号 / 会话 / 审计）
```

浏览器只和面板后端说话（同源 `/api/*`，cookie 会话），拿不到 RCON 密码，也不直连游戏端口。

```
panel/                      后端 —— 部署到服务器的就是这个目录
├── panel.py                入口 shim：python3 panel.py [--config panel.json]（或 L4D2PANEL_CONFIG=…）
├── requirements.txt        fastapi + uvicorn（锁版本）
├── requirements-dev.txt    pytest + httpx
├── l4d2panel/
│   ├── settings.py         panel.json → pydantic Settings（键与默认值即 README 配置表）+ Paths（所有会碰到的路径）
│   ├── context.py          build_context()：组装 store / integrations / services；import 时不做任何事
│   ├── main.py             create_app() / run()：路由、静态文件、错误处理、uvicorn（含 TLS）
│   ├── deps.py             FastAPI 依赖：当前账号（401）、owner（403）、客户端 IP（X-Real-IP）、会话 cookie
│   ├── errors.py           ApiError / IntegrationError → {"error": msg}
│   ├── api/                接口层：解析请求（pydantic 模型）→ 调一个 service → 返回 dict
│   ├── services/           业务层：auth、status、game、whitelist、addons、plugins、plugin_config、accounts、monitoring、server_control、game_install、features
│   ├── integrations/game_installer.py  Docker Compose 配置生成与 L4D2 镜像启动（后台任务由 services/game_install.py 编排）
│   ├── integrations/       协议与外部程序：rcon、a2s、srcds（status 解析）、steam、steamid、workshop（分块续传）、lgsm、vpk、sm_files、plugin_config（CFG 文件）、convars（运行值）、system
│   ├── store/              SQLite：db（连接 + schema）、accounts、sessions、audit
│   ├── jobs.py             后台任务表（工坊下载、打包）+ 一次性下载令牌
│   ├── placeholder.html    前端没构建时 GET / 显示的占位页
│   └── static/             前端构建产物（git 忽略）
├── config_backups/         插件 CFG 变更前备份（运行时生成，git / 部署同步忽略）
├── tests/                  见“测试”
└── install.sh · nginx.example.conf · panel.example.json
frontend/                   Vue 3 + TypeScript（Vite）
├── src/api/                client.ts（fetch 封装：401 → 登出，{error} → 异常）、types.ts（响应类型）、endpoints.ts（每个接口一个带类型的函数）
├── src/stores/session.ts   全局状态：当前页面（loading / setup / login / app）、最新 status、在线玩家
├── src/views/              九个页面 + 登录 / 初始化
├── src/components/         AppShell（侧栏 + 顶栏）、PluginConfigPanel（参数编辑）、Sparkline、JobRow、Switch、Toast、Mark
└── src/styles/app.css      “safe-room console” 主题
sourcemod/ · tools/ · docs/ 插件源码、采样 / 预设生成脚本、文档
```

分层规则：`api` 不碰数据库和文件，`services` 不碰 HTTP，`integrations` 不含业务判断（只做协议、文件格式、外部进程）。每个写操作在 service 里记一条审计（`store/audit.py`）。

## 本地开发

不需要真的游戏服务器。仓库带一个假的 L4D2（RCON + A2S，一个端口，`status` 输出是从线上抓的真实文本，`sm_preset` / `sm_cvar` / `z_difficulty` 会记状态）和一个假的 Steam（工坊查询 / 搜索 / CDN，带 Range）：

```bash
cd panel
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m tests.fakes.devenv           # 建 devenv/（临时 game_dir + panel.json），常驻假游戏 + 假 Steam；Ctrl-C 停
python3 panel.py --config devenv/panel.json     # 另开终端；账号 admin / admin，http://127.0.0.1:8080
```

后端改完要重启 `panel.py`（uvicorn 没开自动重载）。接口文档在 `/api/docs`。

前端：

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173，/api 代理到 127.0.0.1:8080（上面的面板要在跑）
npm run build      # 先 vue-tsc 类型检查，再输出到 ../panel/l4d2panel/static/
```

前端规矩：所有来自后端的数据只经模板插值渲染，**不用 `v-html`**，事件一律 `@click` 绑模型数据（旧版把玩家名拼进 `onclick` 字符串出过存储型 XSS）。响应类型改了先改 `src/api/types.ts`，类型检查会把用到的地方都揪出来。

### Docker 安装与运行时

`GET /api/install` 返回 Docker CLI / Compose / daemon 检测、不可用原因、安装目录、默认值与任务快照。`POST /api/install` 接受 `game_port`、`tick`（30/60/100/128）、`vac`、`mirror_url`（空串为 Docker Hub），不接受第二个面板的密码、端口或任意镜像/命令。`POST /api/install/cancel` 请求取消并审计；进程无输出时也会检查取消。失败保留日志和可恢复数据，安装成功不代表游戏已在线。

`integrations/game_installer.py` 负责镜像拉取、临时容器复制、staging 校验、Compose 启动与非敏感 `installed.json`。拒绝非本任务的目录、Compose 文件与同名项目；随机 RCON 密码仅在游戏配置中，文件权限为 0600。生成的 Compose 是 JSON（Compose 支持的 YAML 子集），只有游戏服务，使用运行面板的 UID/GID、共享 `game_dir`、只读配置的启动脚本，避免上游每次启动覆盖配置。该镜像的 32 位 srcds 沿用上游 `seccomp:unconfined` 设置。

`context.py` 在成功安装时更新所有共用的 RCON/A2S 连接，清缓存；面板启动时按安装标记和元数据恢复。`services/server_control.py` 按 `settings.server_backend` 选择 LinuxGSM / Docker，两种运行时和安装共用操作锁。`integrations/docker.py` 通过 Compose 标签、安装目录验证目标，所有操作仅针对 `l4d2`，巡检不写入。Docker 状态不再读宿主 `pgrep`，日志接入 `docker logs`；`Monitoring` 请求触发 RCON 性能采样（15 秒、120 条内存环形记录）。旧 LinuxGSM 响应字段保持兼容，Docker 状态额外带 `backend: docker` 与 `features.server_control/docker`。

本地 Docker 联调（需要本机 Docker）：

```bash
cd panel
python3 -m tests.docker_smoke          # 真实 Docker + HTTP + RCON/A2S 协议夹具，自动清理自己的项目
python3 -m tests.docker_smoke --keep   # 同样验证，完成后保留本地面板供浏览器调试；Ctrl-C 清理
```

该验证构建轻量 Python 镜像模拟游戏协议，不代表真实 L4D2 引擎或插件的游玩验收。单元/接口回归覆盖取消、失败重试、归属冲突、模式配置保留、日志、性能、安装激活、权限和重启恢复。真实游戏引擎需在支持 Linux x86 的环境另外核对。

### 插件参数接口

接口沿用登录校验和 `{error}` 错误体，`plugin` 必须是已安装插件的 `.smx` 文件名，`file` 是发现结果中相对 `cfg/sourcemod/` 的路径。`services/plugin_config.py` 负责插件归属、批量限制、保存 / 应用流程与审计；文件解析及备份由 `integrations/plugin_config.py` 处理，RCON 运行值由 `integrations/convars.py` 解析。

| 接口 | 参数与行为 |
|---|---|
| `GET /api/plugin-configs` | `plugin`；按标准插件文件头或同名 CFG 发现配置，显式其他插件文件头不会被同名规则覆盖 |
| `GET /api/plugin-config` | `plugin`、`file`；返回参数、文件 SHA256 `revision`、编码、警告和备份列表，不自动查询运行值 |
| `POST /api/plugin-config/runtime` | `plugin`、`file`、`names`；手动读取 1–20 个可识别参数的运行值，每项返回值或错误 |
| `POST /api/plugin-config` | `plugin`、`file`、`revision`、`updates`、`mode`；每批 1–20 项，模式为 `save` / `apply` / `save_apply`，后两种逐项设置并回读；返回磁盘保存结果与各项应用结果，禁用插件仅支持 `save` |
| `POST /api/plugin-config/restore` | `plugin`、`file`、`revision`、`backup_id`；备份绑定原文件，恢复只改磁盘，恢复前的内容也会备份 |

通用编辑仅接受 UTF-8 / BOM、最大 512 KiB 的标准单值 CFG；须有 `Default` 注释才能编辑，可信范围用于数值校验，不把 `0/1` 猜成布尔。重复参数只读，含执行命令或不支持语法的文件整体只读；新值仅允许安全 ASCII（最多 254 字节），拒绝路径越界与符号链接。保存原子替换且保留权限、格式，版本过期返回 409；备份存放于 `panel/config_backups/`，每文件保留最近 20 份。当前不执行整份配置、不重载插件，也不解析 KeyValues；复杂插件适配在后续扩展。

## 游戏模式接口

目录统一定义在 `l4d2panel/game_modes.py`，API 枚举校验、配置持久化白名单和切换目标共用它。依据为安装游戏的 `update/pak01_dir.vpk::scripts/gamemodes.txt`、`missions/campaign1.txt` 及官方中英文语言资源；只记录模式元数据，不引入其他面板代码。`group`、`english`、`base`、`native_players` 为展示字段，原生人数不代表插件调整后的服务器槽位。Mutation ID 为 1–20 中的 19 项，不含 6；`mutation10` 使用终章中庭，`mutation13/15` 也使用中庭，其余使用旅馆。未知 ID 拒绝写入。

- `GET /api/game-mode`：登录后返回 24 项模式目录（基础 5 项、突变 19 项）、实时读取的 `mode` / `map`、运行状态读取错误 `read_error`，以及配置中的默认模式 `saved_mode: string | null` 和配置错误 `config_error: string | null`。不使用状态页缓存，响应带 `Cache-Control: no-store`；读取失败仍提供目录，无法确认的值为 `null`。配置异常不影响实时状态展示，但页面禁止切换。
- `POST /api/game-mode`：请求 `{ "mode": "<目录中的模式 ID>" }`，目标地图由服务端固定选择。先检查配置与运行状态，自动备份并保存 `server.cfg` 中的默认模式，再设置并回读 `mp_gamemode`，匹配后发送 `changelevel`。保存的默认模式用于后续重载和重启。
- 成功返回 `{ state: "switching" | "uncertain", mode, map, message, persisted: true, backup: string | null }`。`persisted` 只表示配置已保存；`state: switching` 仅表示重载命令已发送，重载时 RCON 断开返回 `state: uncertain`。两种情况都必须随后读取实际状态核对，不能直接展示“已生效”。页面连续两次读到目标模式与地图后才完成核对。
- 配置写入失败时不执行游戏写操作。运行值写入或回读被拒绝时不发送切图，回滚配置并尝试恢复原运行值；重载明确被拒绝时同样回滚配置并尝试恢复原运行值。失败返回 `{ error: "中文说明" }`，说明回滚结果，前端刷新实际状态。重载断线不回滚已保存的默认模式，保留配置并继续核对，避免在命令可能已执行时反向覆盖。
- 整段模式切换由服务级锁保护，发送重载后短暂拒绝重复请求；模式配置与伤害配置共用 `SERVER_CFG_LOCK`，避免面板内并发保存覆盖旧内容。模式配置使用唯一的 0600 备份、原子替换和写前版本检查；回滚拒绝覆盖外部修改。记录 `game.mode`、`game.mode.config`、`game.mode.result` 和 `game.mode.rollback` 审计。页面卸载时停止轮询，不会重试写操作。
- 默认模式持久化解决 `server.cfg` 中旧 `coop` 设置覆盖切换结果的问题；解析器仅处理当前文件中的直接指令，不执行 `exec` 文件，也不保证所有插件兼容。2026-09-24 实服已验证五模式切换及保存写实模式后的游戏进程重启；完整玩法需真人入服验收。
- `tests/parity/test_game_mode.py` 和 `tests/unit/test_game_modes.py` 覆盖 HTTP/RCON 调用、配置持久化与备份、回滚、审计、五模式、重载断线和并发边界；`test_game_mode_config.py` 与 `test_sm_files.py` 覆盖真实文件保全、重复定义、故障回滚和跨功能并发保存。

## 测试

```bash
cd panel && python3 -m pytest          # 约 90 秒
```

两层：

- `tests/parity/`——黑盒对齐套件。以子进程启动 `python3 panel.py --config <临时 panel.json>`，对着假游戏 / 假 Steam / 临时 game_dir 通过真实 HTTP 逐个接口验证：状态码、JSON 形状、面板向游戏发了哪条 RCON 命令、改了哪些文件（server.cfg 的 cvar 和备份、admins_simple.ini 的托管块、插件目录移动）、工坊下载的重试 / 取消 / 续传、审计记录。它就是 API 契约：**改接口先改这里**。`PANEL_ENTRY=<另一个 panel.py>` 可以拿同一套用例去跑别的版本（重构时就是这样证明行为没变的）。
- `tests/unit/`——进程内：RCON 协议帧（含对端断开不死锁）、`status` 解析、SteamID 各种写法、VPK 目录读取、server.cfg / admins 文件编辑、任务表、密码哈希与登录限速、A2S 被限流时的 RCON 降级路径、错误体形状、每个写操作都有审计。

插件参数的 `tests/unit/test_plugin_config_files.py` 覆盖真实临时文件的格式保留、范围 / 注入校验、并发版本冲突、备份恢复及路径限制；`test_plugin_config_service.py` 覆盖运行值解析与应用结果；`tests/parity/test_plugin_config.py` 经真实 HTTP 验证发现、保存、恢复、RCON 应用、权限及审计。可先跑 `python3 -m pytest tests/unit/test_plugin_config_files.py tests/unit/test_plugin_config_service.py tests/parity/test_plugin_config.py`。

夹具在 `tests/conftest.py`（临时 game_dir、面板子进程、登录好的 httpx client）和 `tests/fakes/`（`game.py`、`steam.py`、`vpk.py`）。用 `@pytest.mark.panel(key=value)` 覆盖某个用例的 panel.json，`@pytest.mark.game(a2s_challenge=True)` 调假游戏。

## 发布到服务器

服务器上没有 git，部署 = 把 `panel/` 目录同步过去。

1. 本机：`cd frontend && npm run build`；`cd panel && python3 -m pytest` 全绿。
2. 同步到服务器的临时目录（不直接覆盖，先备份）：
   ```bash
   rsync -az --delete --exclude venv --exclude devenv --exclude tests --exclude requirements-dev.txt --exclude pyproject.toml \
     --exclude panel.json --exclude 'panel.db*' --exclude '*.pem' --exclude downloads --exclude workshop_tmp --exclude config_backups/ --exclude docker/ \
     --exclude __pycache__ --exclude .pytest_cache panel/ <user>@<服务器>:/tmp/panel-deploy/
   ```
3. 服务器上（有 sudo 的账号）：
   ```bash
   P=/home/l4d2server/panel
   sudo cp -a $P $P.bak-$(date +%Y%m%d-%H%M%S)                       # 整目录备份
   sudo rsync -a --exclude config_backups/ --exclude docker/ /tmp/panel-deploy/ $P/ && sudo chown -R l4d2server:l4d2server $P
   sudo -u l4d2server -H bash -c "cd $P && venv/bin/pip install -i https://mirrors.cloud.tencent.com/pypi/simple -r requirements.txt"   # requirements.txt 变了才需要
   sudo systemctl restart l4d2panel && sudo journalctl -u l4d2panel -n 10 --no-pager
   curl -s http://127.0.0.1:8080/api/setup && curl -sk https://127.0.0.1:8443/ | grep -o 'assets/index-[^"]*\.js'
   ```
   想在切换前先冒烟：拷一份 `panel.json` 把 `port` 改成 18080、`db` 指到 `/tmp`，用 `systemd-run --unit=l4d2panel-acc --uid=l4d2server --gid=l4d2server -p WorkingDirectory=$P $P/venv/bin/python $P/panel.py --config <那份配置>` 起第二个实例打一遍接口，再 `systemctl stop l4d2panel-acc`。
4. 第一次从单文件版升级：先 `sudo apt install python3-venv`，在 `$P` 里以 l4d2server 执行 `python3 -m venv venv && venv/bin/pip install -r requirements.txt`，把 systemd 单元的 `ExecStart` 改成 `$P/venv/bin/python $P/panel.py` 后 `daemon-reload`。

回滚：停服务，把备份目录换回来，restart。`panel.json` 和 `panel.db` 新旧版本通用；单文件版的 `ExecStart` 是 `/usr/bin/python3 $P/panel.py`。

## 几个设计决定

- **API 契约不随重构变**：路径、JSON、状态码、cookie 名和 `{error}` 错误体都由对齐套件钉死，所以前后端可以分开改；新增字段随意，删改要先动测试。
- **RCON 每条命令新建连接**：srcds 会掐掉空闲的 RCON 连接、多连接并存时应答会乱序，面板一分钟几条命令，连接 + 认证的开销可以忽略；`features`（120 s）和 game flags（15 s）两层缓存把 `/api/status` 每 10 秒一次的轮询压到几乎不发 RCON。
- **A2S 被限流时用 RCON `status` 兜底**：L4D2 对 A2S 有速率限制，公网服务器一直被扫，单次查询经常撞到限流窗口；进程还在（`pgrep srcds_linux`）就改用 RCON 数人，`degraded: true` 标出来。
- **工坊下载自己实现分块续传**：DepotDownloader 对 UGC 文件只发一条 GET、没有重试和续传，国内主机到 Akamai 的单连接速度不稳，大战役经常下不完；见 `integrations/workshop.py` 头部注释。
- **所有安装途径共用一个门**：`services/addons.py` 的 `install_vpk()`——不是 VPK、想覆盖受保护文件的一律拒收并删除；有效 VPK（包括没有 `maps/*.bsp` 的资源依赖包）都可安装，上传 / zip / 工坊 / DepotDownloader 都走它。地图选择由前端只使用解析出的 `maps/*.bsp`。
- **后台任务一种形状**：`jobs.py` 里工坊下载和打包共用 `Job`（state / msg / done / total / speed / files / cancel），前端一个 `JobRow` 组件渲染两种。
