# 开发文档

面向改代码的人：结构、本地环境、测试、构建、发布。安装与使用见 [README](../README.md)。

## 总体结构

```
浏览器（Vue SPA） ──HTTPS──▶ nginx（可选） ──▶ panel.py / uvicorn（FastAPI）
                                                 ├─ RCON TCP / A2S UDP ──▶ srcds
                                                 ├─ subprocess ──▶ LinuxGSM、pgrep
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
│   ├── services/           业务层：auth、status、game、whitelist、addons、plugins、accounts、monitoring、server_control、features
│   ├── integrations/       协议与外部程序：rcon、a2s、srcds（status 解析）、steam、steamid、workshop（分块续传）、lgsm、vpk、sm_files、system
│   ├── store/              SQLite：db（连接 + schema）、accounts、sessions、audit
│   ├── jobs.py             后台任务表（工坊下载、打包）+ 一次性下载令牌
│   ├── placeholder.html    前端没构建时 GET / 显示的占位页
│   └── static/             前端构建产物（git 忽略）
├── tests/                  见“测试”
└── install.sh · nginx.example.conf · panel.example.json
frontend/                   Vue 3 + TypeScript（Vite）
├── src/api/                client.ts（fetch 封装：401 → 登出，{error} → 异常）、types.ts（响应类型）、endpoints.ts（每个接口一个带类型的函数）
├── src/stores/session.ts   全局状态：当前页面（loading / setup / login / app）、最新 status、在线玩家
├── src/views/              九个页面 + 登录 / 初始化
├── src/components/         AppShell（侧栏 + 顶栏）、Sparkline、JobRow、Switch、Toast、Mark
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

## 测试

```bash
cd panel && python3 -m pytest          # 约 90 秒
```

两层：

- `tests/parity/`——黑盒对齐套件。以子进程启动 `python3 panel.py --config <临时 panel.json>`，对着假游戏 / 假 Steam / 临时 game_dir 通过真实 HTTP 逐个接口验证：状态码、JSON 形状、面板向游戏发了哪条 RCON 命令、改了哪些文件（server.cfg 的 cvar 和备份、admins_simple.ini 的托管块、插件目录移动）、工坊下载的重试 / 取消 / 续传、审计记录。它就是 API 契约：**改接口先改这里**。`PANEL_ENTRY=<另一个 panel.py>` 可以拿同一套用例去跑别的版本（重构时就是这样证明行为没变的）。
- `tests/unit/`——进程内：RCON 协议帧（含对端断开不死锁）、`status` 解析、SteamID 各种写法、VPK 目录读取、server.cfg / admins 文件编辑、任务表、密码哈希与登录限速、A2S 被限流时的 RCON 降级路径、错误体形状、每个写操作都有审计。

夹具在 `tests/conftest.py`（临时 game_dir、面板子进程、登录好的 httpx client）和 `tests/fakes/`（`game.py`、`steam.py`、`vpk.py`）。用 `@pytest.mark.panel(key=value)` 覆盖某个用例的 panel.json，`@pytest.mark.game(a2s_challenge=True)` 调假游戏。

## 发布到服务器

服务器上没有 git，部署 = 把 `panel/` 目录同步过去。

1. 本机：`cd frontend && npm run build`；`cd panel && python3 -m pytest` 全绿。
2. 同步到服务器的临时目录（不直接覆盖，先备份）：
   ```bash
   rsync -az --delete --exclude venv --exclude devenv --exclude tests --exclude requirements-dev.txt --exclude pyproject.toml \
     --exclude panel.json --exclude 'panel.db*' --exclude '*.pem' --exclude downloads --exclude workshop_tmp \
     --exclude __pycache__ --exclude .pytest_cache panel/ <user>@<服务器>:/tmp/panel-deploy/
   ```
3. 服务器上（有 sudo 的账号）：
   ```bash
   P=/home/l4d2server/panel
   sudo cp -a $P $P.bak-$(date +%Y%m%d-%H%M%S)                       # 整目录备份
   sudo rsync -a /tmp/panel-deploy/ $P/ && sudo chown -R l4d2server:l4d2server $P
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
