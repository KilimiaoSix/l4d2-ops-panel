## Context

本文件整合 2026-09-26 Claude 会话的 M1/M2/M3 设计和两份评审，并按 2026-09-27 本地代码重新核对。该会话只授权制定计划；本次交付为规划工件，下面的 API、文件及流程均为拟实现设计。

基线：`b73ef2a`。未提交的 Steam Web API 自定义主页解析会使 `SteamClient` 持有 `steam_api_key` 快照，因此配置热更新必须更新该对象。已有 AppShell 页脚已经支持连接地址复制；原草稿“完全没有 connect”的判断应改为“缺少可靠地址来源与完整加入引导”。

现有代码关系：

| 入口/调用者 | 编排与下游 | 必须保持的约束 |
|---|---|---|
| `main.main → config_path → run` | `load_settings → build_context → Paths/服务/store` | 实际 conf 当前仅用于读取与日志；必须显式传递，路径相对关系仍按既有 base 规则 |
| `SetupView → /api/setup` | `AuthService → AccountStore → Database` | 目前 count 和 create 分开；并发失败应在持久层保证唯一初始化、服务层返回 409 |
| `ServerView → /api/install` | `GameInstallService → DockerGameInstaller → Compose` | 非空 game_dir 拒绝首装；向导不能提前在游戏目录创建文件 |
| `ServerView → /api/action` | `ServerControl → DockerServer/Lgsm` | 与游戏安装共享 operation_lock；启动/重启完成后需失效能力缓存 |
| `PluginsView → /api/plugins` | `PluginService → sm_files/RCON` | 手动上传继续可用，不让新插件包绕过保护规则 |
| `GameModePanel → /api/game-mode` | `GameService/GameModeConfig → SERVER_CFG_LOCK/RCON` | 已有模式保存、备份、回滚与确认语义不能被基础设置破坏 |
| `MapsView → /api/addons` | `AddonService.list → os.listdir(addons)` | 未安装游戏时当前会抛错；新空状态应修正，并禁止查询创建 game_dir |
| `JobRegistry.start` | daemon 工作线程 | 面板退出会丢失后台线程；优雅退出不是任务保活方案 |
| `session → api/client → AppShell/视图` | 401 登出、路由和轮询 | 重启提示、过期响应丢弃、卸载清理沿用 ServerView 的 revision/alive 模式 |

## Goals / Non-Goals

**Goals:**
- 首版认证 Ubuntu 22.04/24.04 x86_64、systemd；默认安装全程零技术问答。
- 前端、固定插件载荷随 Release；普通用户无需 Node、spcomp 或自行找插件依赖。
- 保留已确认的最小/可选全套、LinuxGSM 高级配置和自动重启能力。
- 正常流程靠网页完成，异常恢复至多提供明确的一条系统修复命令。
- 每一步区分保存、安装、加载、运行确认和外网入服证据。

**Non-Goals:**
- 多服、整服备份产品、游戏覆盖重装/自动更新、自动操作云安全组、任意远程 URL 插件市场。
- Windows/ARM 游戏服务器支持、无 systemd 主机的自动引导；Windows 仅作为开发机。
- 面板内自动升级。get.sh 的显式重复运行/指定版本更新需要正确，但不做后台自动更新。
- 在本次规划中改代码、运行生产部署、发布 tag 或宣称未来测试已通过。

## Decisions

2026-09-27 实施补充：用户已授权按本计划实现、使用隔离 Docker 安装测试并在现有服务器调试。用户进一步确认 L4DToolZ 因尚未取得明确再分发许可，改为安装时从官方 release 下载固定版本并校验 SHA256；其规范化文件映射仍由同一清单定义，下载/解包在任何游戏文件提交前完成，失败不提交。它不进入发布 tar。Metamod/SourceMod 和其他已确认许可的载荷继续内置；该例外不允许任意 URL 或 latest。

### Decision: 用户决策保持原意

沿用原会话六项已确认选择，见用户阅读版。评审建议中“删掉重启机制”“改成默认全套”与用户选择冲突，不采纳。默认最小允许原生 4 人合作；选择全套或多人包后人数必须可改、能入服。新增 `panel_hostname` 是中文服名的必要自带插件，纳入最小集。

首次账号方案在原会话无答复，本次默认：get.sh 生成随机高熵初始 owner 密码，以 0600 写入初始配置，启动前完成种子初始化；只在首次成功安装时在终端显示，不进入任务日志、审计或 GET 响应；已存在账号时不重置。登录后使用现有改密功能，首次强制改密不是本版要求。旧 install.sh 的网页初始化兼容保留，修复原子性。

### Decision: 单一发布物和插件清单

发布资产：`l4d2-panel-linux-x86_64.tar.gz`、`SHA256SUMS`、固定版本 `get.sh`、来源/许可材料及可验证的校验清单签名。tar 内包含 `panel/`、构建后的 `l4d2panel/static/`、`VERSION`、依赖约束和插件载荷，不带 panel.json、DB、证书、venv、日志、真实 game_dir 或测试秘密。

唯一插件目录：

```text
panel/packs/manifest.json             # 纳入 Git 的声明式注册表
panel/packs/payloads/<payload-id>/    # CI 生成、Git 忽略、随 Release 交付的规范化文件树
panel/packs/payload-manifest.json    # CI 输出的逐文件哈希、源版本及来源信息
panel/packs/licenses/                # 上游声明、许可、对应源码材料/取得方式
```

发布工具放 `tools/release/`；不新增顶层 `packaging` 包。CI 使用符合 Vite engines 的固定 Node 22.x 版本、Python 3.12 构建；运行时测试覆盖 Python 3.10/3.12。固定完整 Python 依赖约束，并在 CI/get.sh 同用；不能只锁 fastapi/uvicorn 而让间接依赖漂移。

CI 从固定 URL/commit + SHA256 取上游，只在构建时解包，验证路径和文件类型后整理成 game-relative 树。编译器 `spcomp64` 显式赋 0755，普通文件 0644，目录 0755；不用 latest 指针决定发布内容。用户运行时只校验、复制规范化文件树，避免两套 tar 解包器和 strip 路径 DSL。最终 release 外层解包仍必须审查绝对路径、`..`、链接和设备文件，再写入 staging。

不承诺整条工具链字节级可复现；承诺固定输入、有来源可追溯、发布物可验证、同输入归档元数据稳定。不得同时要求墙钟 built_at 和双构建逐字节相同。

### Decision: GitHub Releases 托管，可选镜像不改变信任源

用户于 2026-09-27 明确要求不使用现有服务器提供发布资源，改用 GitHub。默认由本仓库 GitHub Releases 托管固定版本的 `get.sh`、`VERSION`、tar、`SHA256SUMS` 和签名；安装入口使用明确的 `v<版本>/get.sh`，不依赖 latest 来选定安装版本。`toolchain.json` 的 `mirror: null` 是受支持的发布配置，独立国内镜像不再是发布前置条件。保留用户显式配置的 HTTPS 镜像和签名离线安装；`MIRROR` 只改变下载路由，不关闭校验。Docker registry 镜像与普通文件镜像分开配置，不能拿 `docker.cnb.cool` 当 tarball 镜像。GitHub 的国内访问质量取决于用户网络，不宣称存在额外的国内分发站点。

以固定公钥验证发布 checksum manifest，再比对 tar SHA256；镜像不能同时替换 tar 和未认证的 checksum 后被接受。引导脚本的最初信任由官方文档提供的 GitHub HTTPS 入口/固定哈希建立，不能声称脚本内嵌公钥证明了脚本自己。P0 负责确定签名格式、密钥保存/轮换与 CI secret；第一份可对外 Release 必须具有真实可下载的 GitHub 版本化资产，不能把源码模板、Actions 临时工件或示例地址当作已发布安装入口。上游消失时可使用维护者已校验归档，仍须同一哈希。

实施格式：RSA-3072 / PKCS#1 v1.5 / SHA-256，固定 384 字节签名 `SHA256SUMS.sig`；认证清单仅允许 tar、`get.sh` 和 `VERSION` 三项。先验签后验哈希，再核对请求版本与 tar 内版本；拒绝重复路径、路径穿越、软/硬链接、特殊文件和过大归档。公钥写入经审查的版本化脚本；私钥独立保存为受保护发布环境的 CI secret，不能出现在代码、tar、测试报告或镜像。轮换必须先在已信任入口公布新公钥指纹及过渡脚本；不能自动信任镜像附带的新公钥。生产公钥未落实或正式签名流程未验证时，不宣称正式发布。当前已配置独立生产公钥及仅 main 分支可用的 GitHub release 环境 secret；正式签名工作流和公开 GitHub 资产下载仍待实测，指纹和保管位置见 docs/release-signing.md。

安装进程使用只读 `/api/health` 检查 version、boot、PID 和 owner 是否已初始化；该接口不探测游戏、不返回配置或凭据。新进程 PID 还需与 systemd MainPID 一致，不能以旧实例的 HTTP 200 判定更新成功。

### Decision: root 引导完成主机工作

get.sh 限定 root、Ubuntu 22.04/24.04、x86_64 和 systemd；不满足时在改动前退出并解释。固定专用用户 `l4d2panel`，默认 `/home/l4d2panel/panel`、独立且不预创建的游戏目录。已有用户、unit、安装目录须有本工具安装标记且身份一致，否则拒绝接管。可用 Docker 原样复用，包冲突不自动删除别人的容器或运行环境。

Docker 从官方签名 apt 仓库安装 `docker-ce/docker-ce-cli/containerd.io/docker-compose-plugin` 及所需组件；国内替代源必须使用相同包签名信任和经过验证的包版本。失败是引导失败：退出非零，打印阶段、原因和一条 `get.sh --repair-docker` 重试命令；即使面板已保留可访问，也只报告“面板已安装、环境未就绪”。不给无 sudo 的网页放一个无法工作的“帮我安装 Docker”按钮。

依赖与 venv 以服务用户创建。首次配置采用统一配置生成/校验入口，TLS 证书有正确的 IP/DNS SAN；有效证书不覆盖。写 unit 后 daemon-reload，再 enable/start，探测当前版本和登录状态。面板用户加入 docker 组并非安全隔离边界；文档准确说明其主机控制能力，不扩大到任意 sudo。

重复执行：系统互斥锁 → 验证并 staging 新版本 → 校验旧状态归属 → 停掉面板 → 备份代码/配置（无需复制整个游戏树）→ 保留可变数据 → 替换 → daemon-reload/start → 校验新进程 boot/version。失败恢复旧代码和已保存的配置并启动。不得用 `enable --now` 加旧进程的 200 响应冒充更新成功。保留 DB/WAL、证书、配置备份、插件收据、下载/续传数据和 docker 元数据。不同用户/目录迁移需要独立操作，不由重跑猜测。

系统脚本只调整本工具端口规则，保留 SSH，不启用一个原来关闭的防火墙。默认面板 8443/TCP，默认游戏 27015/TCP+UDP 的本机规则在首次引导处理。后续选择非默认游戏端口时，网页显示准确的一条 `l4d2panel-network --game-port N` 修复命令；root-owned helper 只接受合法端口并操作已识别规则，不读取可执行用户命令。Docker 发布端口与 UFW 的关系不能仅凭 `ufw allow` 判断，结合发布映射、DOCKER-USER 和云安全组诊断。云安全组不由脚本伪装为已开放。

### Decision: 面板配置采用受控字段表

实际配置路径从 `main` 显式传入 `build_context` 和配置服务；相对路径保持按 panel base 解析的既有契约。文件编辑保留未知旧字段，不将 `Settings.model_dump()` 当作原文覆盖。HTTP 更新严格拒绝未知键；`--check-config` 明确报告未知键（旧启动读取仍保留兼容的 extra=ignore）。

| 字段组 | 处理 |
|---|---|
| panel_title/display_host/max_upload_mb/steam_api_key | 热生效；同步 Settings、SteamClient 快照、能力缓存、应用展示标题 |
| port/bind/tls/cert/key/session_days | 高级设置，需要重启；端口类型范围、路径、证书配对及服务用户可读性预检 |
| rcon_host/rcon_port/rcon_password/lgsm_script/console_log/perf_csv/depotdownloader | LinuxGSM 高级配置，需要重启；秘密只写不回显；Docker 管理下的 RCON 目标由安装元数据锁定 |
| game_dir/install_dir/docker_project | 仅在无游戏安装且目标不含既有游戏时允许修改并重启；不是游戏迁移入口 |
| db/bootstrap_user/password/server_backend/受保护文件清单 | 不开放此通用编辑器；账号操作走原账号接口，backend 由安装器确定 |

保存流程：owner → 原文版本 SHA256 → 全部字段校验 → 资源互斥 → 0600 唯一备份 → 临时文件/fsync/原子替换 → 应用运行时字段或安排重启。无变化不备份、不重启。GET 隐去 panel/RCON/API 密钥，只返回 `*_set`。日志和错误文本也不可携带新旧秘密。

重启参数更新默认 `restart=false`；若涉及重启字段且未确认，返回 409 `restart_required`，不保存，避免“文件已新、内存仍旧”的混合状态。确认后一个事务接受整批变更。变化可能使浏览器失联时，先显示新 URL 或反代前提，并明确风险再提交。

### Decision: 重启协调与有界恢复

用一个明确的重启协调器管理 `restart_pending`。在相同同步域内检查所有后台任务/游戏操作并设置 pending；新的任务注册、开关服、插件/文件写入也必须检查 pending，不能只做一个存在竞态的 `any_running()`。JobRegistry 迭代加锁。仅受本项目 systemd unit 管理时支持自退；其它运行方式拒绝重启字段，不关掉进程。

同一端口不做 socket.bind 探测，避免撞自己的监听；改变端口才做尽力预检。bind 改动、外网可达性和重启期间的竞争最终由启动/回退验证，不将预检当成证明。拒绝游戏端口冲突，远程改为 localhost 时只能走确认的反代配置，不能生成让远程浏览器连自己电脑的链接。

成功响应含旧 boot-id、目标配置 revision 和 next_listener；响应发送后用明确的 uvicorn 退出控制/可预测的 SIGTERM 顺序优雅停止。优雅停止只保护响应，不保活 daemon jobs，所以 pending 排他门不可省略。启动参数实现须针对锁定的 uvicorn 版本测试，不能假定 SIGTERM 一定退出码 0。

磁盘 pending 记录保存目标 revision、旧配置备份和尝试次数，不含秘密。新进程完成配置加载和监听后标记为已启动；若新配置启动失败，且目标文件仍等于本任务写入版本，则自动恢复上一版一次并重新启动。不要恢复覆盖外部编辑，也不要无限重启。已有端口可访问但云规则未开放不是内部启动失败：网页提供旧地址/恢复命令，不能自动反复回滚网络。

同源 UI 轮询认证状态至 boot-id 改变且实际配置 revision 对应（最长 90 秒）；跨源不做会被 CORS 拒绝的 fetch，显示/导航到明确的新地址并按需登录。说明用非敏感原因码传至 LoginView 并真正渲染；退出/换页停止轮询。HTTP 200 或容器 running 都不是重启完成证据。

恢复命令 `sudo l4d2panel-recover`：root-owned wrapper 停固定 unit，以服务用户执行 `panel.py --restore-config --config <实际路径>`，验证选定备份并版本检查，再启动 unit。不得以 root 导入服务用户可改写的 Python 模块。只恢复面板配置，不删除数据库/游戏。恢复不可用时打印明确诊断，不假报成功。

### Decision: 向导按状态续接，不按账号数推断完成

增加 store 中独立 `panel_state`（一次性 schema/migration 标记、setup_complete、step、非秘密草稿）。在 auth.seed 前完成迁移：全新数据库明确写 `complete=false`；既有安装第一次迁移写 `true`；之后只读该标记，不因账号已存在或刚装好 Docker 就改成完成。已完成用户可从设置页重新打开向导。

步骤：环境检查 → 游戏端口/安装 → 最小或可选组件 → 基础服名/密码/人数 → 必要重启与能力确认 → 朋友加入/网络指引 → 完成。可在游戏安装期间填写非秘密草稿，但只在游戏安装完成后调用基础设置保存；密码留在当前输入框，刷新后重新输入，不进 localStorage。不会提前创建 game_dir 导致安装器拒绝。

步骤状态由持久收据、实际游戏与插件查询推导，进度页可离开再回来；只有显式完成且必要安装/设置已确认，才标记完成。公网入服未验证必须明确标注；可允许稍后验证，但不能写“公网已就绪”。

所有依赖游戏的页面在未安装时显示共享空状态和安装入口。读接口返回空集合或带状态的预期 409；不一刀切把所有错误改成 200，不吞掉真实损坏。上传/绑定管理员等写操作在未安装时明确拒绝或存为不落游戏目录的待处理状态。浏览全部九页不创建游戏目录、不持续 500。

### Decision: 插件包有真实依赖和可恢复文件事务

注册表 schema=1：包 id/name/summary/default/required、固定 payload id、requires、conflicts、提供的能力、文件策略和上游来源。保留真实依赖闭包/环检测：多人和特感确有非基础包依赖，不能简化为 required 集合；编译 include 与运行期依赖分开记录。浏览器只能提交预定义 id，不接受任意 URL/路径/命令。

默认集包含 Metamod、SourceMod（含 `cfg/sourcemod`）、sm_whitelist、sipreset、panel_hostname。sipreset 是附带工具，有 Infected Bots 与可用数据时才宣告 preset 能力。全套由所有已验证的可选兼容包组成；多人包含 l4dtoolz + MultiSlots 类生还者管理及依赖，特感包含 Infected Bots 的固定版本依赖闭包和预设，积分含 Points System。不得把上游 master 的当前需求直接套到另一个固定版本。

发布前逐包验证 x86 引擎所需 ELF/SMX、gamedata、扩展、翻译、配置、许可与对应源码材料。基础框架不得仅凭文件头宣称游戏兼容。不能从原草稿直接继承“所有上游都是某一种许可”或“Metamod 1.12 必为稳定版”的断言。

安装前计算实际文件计划和冲突列表。源/目标都拒绝路径越界、符号链接、硬链接与特殊文件；仅允许 addons/、cfg/，引擎读取的 cfg 做 ASCII 检查，SourceMod data 保留 UTF-8。未知已有框架不自动覆盖；已被用户修改的托管二进制提示冲突。配置、管理员、白名单、数据文件只初始化缺失项；不覆盖 `panel_hostname.txt`、IB 数据或旧插件参数。

本版只允许游戏停止时提交框架/插件包。网页提供明确的“停止并安装”确认；服务获取共用 operation_lock 后通过同一受控 backend 停服，不能持锁再递归调用也抢锁的 ServerControl.run。停止失败不改文件。安装阶段先全量验证/staging，再使用记录原始哈希和备份的文件事务逐文件提交。取消/失败按版本校验回滚本事务；无法自动恢复时保留 journal 和恢复入口，显示 incomplete 并阻止自动启动，不用完整 installed 收据掩盖半安装。

持久收据放面板可变状态目录（如 `pack_state/`），记录 game_dir 归属、包版本、文件哈希、待重启和最后确认状态，部署时保留。只有事务完整提交后才记 installed；重启后实际探测框架和依赖才记 active。GET 只读，不清理 staging；残留清理在审计的安装/恢复任务进行。进度 done/total 统一使用文件数。

安装提交、游戏 start/restart 后通过注入回调失效 features 和 game flags。探测失败记 unknown，不缓存为确定缺失；用户可重试。平台有插件但不响应时不自动反复停服/安装。

### Decision: 基础设置复用有限的 CFG 编辑能力

沿用单一 `SERVER_CFG_LOCK`、字节快照、备份、原子替换和外部版本检查。对现有模式解析器做只覆盖所需指令的小范围通用化；不用七参数 Directive 框架，也不重写通用插件 CFG 模块。模式兼容外观和已有备份/回滚语义保持，禁止无关格式变化。一个请求对 server.cfg 作一次合并保存。

字段：`server_name`（1–96 UTF-8 字节，禁止控制字符/引擎危险字符）、可选 ASCII fallback、进服密码（空字符串明确表示清除；省略表示不改；可打印安全 ASCII，最多 64 字节）、region（0–7 或 255）、coop_players（可选多人能力下 4–12）。进服密码不得等于 RCON 密码，不回显现值、不写审计。

中文名称保存到 `addons/sourcemod/data/panel_hostname.txt`，文件最后一个换行不计入规范化名称字节；server.cfg 只放 ASCII fallback。SourceMod 插件读取 UTF-8 文件、设置 hostname，监听后续覆盖并使用防重入和有界纠正次数；不依赖本项目实服中不能稳定触发的 OnConfigsExecuted 或休眠时不跑的定时器。RCON 报告使用规范化名称与实际值的 ASCII 十六进制字节串和状态，进行精确比较；不用仅凭字节长度或“命令已发送”判断成功。

server.cfg、名称文件以及多人包配置需要一个可恢复的多文件保存事务：先验证所有输入和 revision，再备份/记录 journal，写入；失败仅在文件仍属于本事务版本时回滚。保存失败不发 RCON。`save` 只保存，`apply` 仅适用可即时执行项，`save_apply` 保存后逐项尝试，返回 saved/applied/unverified/error/restart_required，不因部分生效伪报全成功。名称应用直接探测插件，不以 120 秒缓存作为硬门禁。

进服密码回读被 FCVAR_PROTECTED 隐藏时只显示已保存、运行未确认；不得把掩码当实际密码。地区按实际可读值核对。所有新增指令都纳入 fake 的带引号赋值、空密码、拒读、掉线和调整值路径。

### Decision: 人数和引擎容量分开

`sv_setmax` 是 MaxClients 容量，包含人类/机器人/特感，不作为用户的 coop_players 直接映射。多人包定义经实测的容量 profile（首版计划 31）、`sv_maxplayers`、生还者管理器上限以及必要的 lobby 解锁；角色生成依赖单独验证。容量进入引擎启动参数，单写 server.cfg 不能假定加载时机正确。

为 Docker 启动脚本新增受控 profile 读取，不执行任意用户命令、不覆盖 server.cfg；游戏模式的起始地图选择保持。人数改动是否可热生效由固定组合测试决定；需要重启则网页明确安排游戏重启并回读。人数/特感 profile 验证共用容量预算，保留 Tank/特感空间；不能允许 12 人加 te16 后毫无预算检查。未装多人包返回能力缺失并提供补装入口；安装文件存在不等于能力通过。

初版认证 4/8/12 人合作场景，边界拒绝 3/13、非整数及依赖失效。其它模式继续已有模式功能，但不将合作人数认证等同于全部突变/对抗插件兼容；测试报告列出组合范围。

### Decision: 加入信息可用且不泄密

复用页脚复制，新增完整加入卡。地址优先 owner 设置的对外地址，兼容已有 display_host 含端口的写法，避免重复拼接端口；否则使用浏览器访问的非本机主机名和安装元数据中的游戏端口，标注推断来源并允许修正。拒绝 scheme、空白、控制字符和命令分隔符；不使用 0.0.0.0/127.0.0.1 作为朋友地址。

卡片说明 L4D2 开启开发者控制台、输入 connect、若有进服密码如何单独输入；共享文本默认不含任何密码，管理员自行决定如何告知朋友。附上游戏 TCP/UDP、面板 TCP、安全组和客户端 VPK 依赖。A2S/RCON 只证明面板可连接游戏；公网成功须真实外部客户端或明确的外部探测证据。UDP 端口不能以 TCP connect 成功作为通达证明。

## Architecture / Flow

实施文件分组（N=新增，M=修改；路径相对仓库）：

| 任务组 | 主要文件与层 | 调用/约束 |
|---|---|---|
| P0 | N `panel/packs/manifest.json`、`tools/release/upstreams.json`、Python constraints；M 前端/后端契约测试 | 发布和运行时同一契约，来源审查先于打包 |
| M1 发布 | N `.github/workflows/{ci,release}.yml`、`tools/release/`、`get.sh`、root-owned 恢复/网络 helper | 对最终 tar 测试，不读取开发机真实配置 |
| M1 配置 | N `integrations/panel_config.py`、`services/panel_config.py`、`api/panel_config.py`、`store/panel_state.py`；M main/context/settings/jobs/server_control/auth/store/accounts | 文件格式在 integration，流程权限与审计在 service，SQL 在 store |
| M1 UI | N `PanelSetupView.vue`、`PanelRestart.vue`、共享未安装空状态；M session/router/AppShell/LoginView、依赖游戏各视图、api types/endpoints | 控件和异步状态，不在前端伪造安装完成 |
| M2 | N `integrations/plugin_packs.py`、`services/plugin_packs.py`、`api/packs.py`、`PluginPackCard.vue`；M context/features/server_control、PluginsView | 运行时文件树验证与事务；原插件上传逻辑保留 |
| M3 | N `integrations/basic_config.py`、`integrations/hostname_file.py`、`services/basic_settings.py`、`api/basic_settings.py`、`BasicSettingsView.vue`、`JoinServerCard.vue`、`sourcemod/scripting/panel_hostname.sp`；M game_mode_config 的有限共享、game_installer 启动 profile | 共用 CFG 锁；需迁移共享函数时一次移除重复实现，不留无用桥接 |
| E | N targeted unit/parity/release/browser 验收；M tests/conftest.py、fakes/game.py、docker_smoke | 真实配置文件、实际重启端口、完整 Release 与真实引擎分别测试 |

排除：无关地图目录、24 种模式目录、现有 Steam 解析功能重写、生产服务器管理权限/数据、任意现存插件替换。需要交叉文件时先在 tasks/design 标明，不以“顺便优化”为由扩大边界。

## Data or API Changes

继续使用 `{error}` 错误体；新增接口无会话 401，权限不足 403，参数无效 400，版本/运行冲突 409。所有配置/状态响应 no-store，敏感字段只提供 set 标志。

| 接口 | 权限 | 请求/主要响应 |
|---|---|---|
| GET `/api/panel-config` | owner | 受控 fields、effect、editable/locked_reason、revision、secret_set、实际 conf 路径和 supervisor 状态 |
| POST `/api/panel-config` | owner | `{revision,updates,restart:false}`；`{saved,revision,changed,restart_scheduled,boot,next_listener,backup}`；不确认重启不保存重启字段 |
| GET `/api/onboarding` | 登录 | `{complete,step,checks,draft,missing}`；无秘密，检查失败有明确原因 |
| POST `/api/onboarding` | owner | `{step,draft?,complete?}`；只更新允许的非秘密草稿，完成前检查必要条件；审计 panel.setup |
| GET `/api/status` | 登录 | 增加 `boot`、配置应用 revision、安装/向导摘要；旧字段不删除 |
| GET `/api/packs` | 登录 | 清单、可用性、选择项/依赖、installed/active/unknown、任务、冲突、restart_required |
| POST `/api/packs` | 登录 | `{packs:[id],stop_game:false}`；返回解析后的列表和 job id；运行中须显式停服确认，不提供通用 force 覆盖 |
| POST `/api/packs/cancel` | 登录 | `{}`；协作取消，只有事务恢复结束后才报告取消完成 |
| POST `/api/packs/recover` | 登录 | 固定事务 id + 当前 revision；只恢复本面板事务并审计，不接受路径 |
| GET `/api/basic-settings` | 登录 | 磁盘字段、revision、password_set、人数能力、join 来源、config_error；不强制 RCON |
| POST `/api/basic-settings` | 登录 | `{revision,mode:'save'|'apply'|'save_apply',server_name?,password?,region?,coop_players?}`；省略不变，空密码清除；返回保存结果及逐项应用状态 |
| POST `/api/basic-settings/runtime` | 登录 | `{names:[...]}`；逐项值/未知/错误，受保护密码永不作为实际值回传 |

原 GET `/api/setup` 保持 `{needed,username}`；新引导默认已种子创建 owner。原 POST `/api/setup` 保留兼容但并发检查+创建原子化。新 state 与 pack/config 事务有 schema_version；升级迁移幂等、兼容旧 DB，禁止重建库。

## Validation and delivery gates

| 门槛 | 场景与权威证据 | 不能代替它的证据 |
|---|---|---|
| V0 计划 | OpenSpec strict；任务/需求/文件/验收映射，已确认决策无偷换 | 文档存在而内容互相矛盾 |
| V1 发布 | CI 编译 SPA/.smx，固定依赖；从最终 tar 校验 manifests、载荷和秘密排除；签名/哈希篡改测试 | 在源码测试中手造另一份 packs 目录 |
| V2 引导 | 干净 Ubuntu 22.04/24.04 systemd VM：正常、镜像、失败重跑、第二版本、占用目录、坏证书、磁盘不足、Docker失败、UID/GID | `bash -n`、shellcheck 或 SKIP_DOCKER 容器单独通过 |
| V3 配置 | 真实外置 conf、并发 revision；相同端口/新端口/TLS；job 启动与 pending 竞争；进程退出/启动失败/自动回退；90秒UI超时 | Mock restart 回调或纯内存 Settings |
| V4 向导 | Playwright/浏览器逐页访问未安装状态；中途刷新/重启/重新登录继续，旧 DB 不强制向导；不会提前生成 game_dir | 只有登录页截图 |
| V5 插件 | 最终 Release 的最小、首次全套、事后补全；缺依赖/冲突/取消/每步注入故障/崩溃恢复/配置保全；真实引擎 meta/sm/plugin 检测 | 文件存在或 Docker 容器 running |
| V6 基础设置 | 文件真实 I/O；空密码往返、名称96/97字节、地域边界、并发模式/伤害写；真实引擎中文换图/重启/休眠和被其它插件覆盖 | FakeGame 回显同一请求 |
| V7 游玩 | 外部真实客户端输入进服密码/错误密码/清除密码；4/8/12多人（至少证明第五位可成为生还者）、满员/掉线重连、地图切换与所选特感预算 | sv_setmax 或 A2S max 回读数字 |
| V8 回归 | `cd panel && python3 -m pytest`、`cd frontend && npm ci && npm run build`；真实 Docker smoke；旧 LinuxGSM、账号、地图/ZIP、插件参数、游戏模式不回退 | 14项 Steam/认证单测通过 |

测试夹具具体改动：进程内 app fixture 写真实 panel.json 并传 conf；FakeInstaller 注入只在进程内测；子进程重启 helper 重读 port/TLS/base_url、追加日志和关闭旧句柄；FakeGame 支持普通与 sm_cvar 的引号/空值赋值、protected 拒读、未知 cvar、hostname ASCII报告以及多人 profile。401 测试必须证明真实路由已注册，并同时有合法请求成功用例，不能依赖 catch-all 的 401。

2026-09-27 V7 修正：在同一候选容器内，非空 `sv_password` 使 A2S 静默，清空立即恢复；更换 SDK 不改变这一结果。Valve issue #3416 记录了相同的密码窗口卡住问题。最小包增加 Panel Join Password，使用 protected `sm_panel_join_password` 与客户端 `setinfo l4d2_password` 在 OnClientConnect 校验；不绕过 Steam 身份验证。保存非空密码时，同时把原生 sv_password 写为不可加入的保护值，插件健康运行时才清空原生运行值；插件缺失、卸载或暂停时保持拒绝加入。旧原生密码在插件读取配置时迁移到内存，面板再次保存时改写为新配置。密码仍只写不读、不进入回执或审计。运行回执只说明插件已加载校验配置，不等同于真人进服通过。real_game_smoke 必须真正执行 UDP A2S。

开发顺序：P0 → M1配置/发布底座 → M2与M3服务 → 完整向导和加入页 → V1–V8整体验收。M1单独交付须标明只有面板引导底座。原计划稳定版本等待全部验收；2026-09-28 用户已明确授权提前正式发布本次面板/安装功能并部署，由用户继续实玩。缺少的真人满员、清除密码与重连测试仍保留未验证，change 保持活动，不归档。部署先完成本电脑上的完整备份及验证，合并性能优化任务的相关工作，保留既有游戏数据、全部插件和配置，统一核对后清理旧测试资源；不将已有 LinuxGSM 游戏服重新安装为 Docker。

## Risks / Trade-offs

- GitHub 发布入口、签名密钥、上游具体构建号、Points 来源及多人依赖组合在实施 P0 产生锁定文件与证据；独立镜像按用户最新要求改为可选。
- 公网不能从本机完全证明；云防火墙和真实客户端是单独验收。用户可跳过外网确认，但产品不能误报完成。
- systemd 重启仍有证书、端口、权限等失联风险，保留已确认能力同时增加有界回退和一条命令恢复。
- 中途退出的文件事务恢复有限且必须检查外部修改；不以整树覆盖简化问题。
- 中文、AutoExecConfig、休眠和人数上限采用仓库实服笔记作为当前风险依据，固定新组合须重验，不将单台机器经验宣布为所有版本定律。
- 上游许可必须逐项保留和审查；SourceMod 官方说明为 GPLv3 带例外，Metamod 另有组件许可，不能用原草稿的一句统一许可结论代替材料。

## Alternatives Considered

- 无玩家休眠换图时 `OnConfigsExecuted` 实测可延后至少 20 秒，空密码初次启动也会延后；不能把插件就绪完全依赖该回调。加载时读取当前密码变量、保持上一张地图的有效密码，并监听后续原生密码赋值，立即转入专用校验和清空原生运行值。

- 密码插件停止时的原生保护必须恢复实际配置密码，不能使用公开固定哨兵字符串；这样即使引擎原生密码缺陷被修复，也不会产生已知通用密码。插件健康运行时继续清空原生运行值，由专用 userinfo 校验。

- 只改四个热生效键：更简单，但不符合用户已选定的高级配置/自动重启范围，拒绝。
- 默认强装多人/特感/积分：违反最小默认选择，拒绝；以依赖提示和全套入口解决可发现性。
- 运行时下载最新第三方 tar：违背内置发布物且无法复现，拒绝。
- 两套 tar 解包器/两套载荷目录：统一为 CI 规范化目录和唯一清单。
- 只有 `sv_setmax` 的人数滑块、只有长度的服名回执：都不能证明实际目标，拒绝。
- 广泛重构 CFG/Jobs：仅扩展跨功能正确性所必需的共享锁、受控指令与 pending 协调，不做通用框架。

## References

检索日期 2026-09-27；动态页只作为选型和验证起点，发布时锁定具体版本。

- [Docker Ubuntu 安装](https://docs.docker.com/engine/install/ubuntu/)：官方 apt 路径、Compose 包以及 Docker 发布端口的防火墙注意事项。
- [SourceMod 下载](https://www.sourcemod.net/downloads.php)、[SourceMod 许可](https://www.sourcemod.net/license.php)：固定运行时与编译器来源，逐包记录许可材料。
- [Metamod 下载页](https://www.metamodsource.net/downloads.php)、[Metamod 许可文件](https://raw.githubusercontent.com/alliedmodders/metamod-source/master/LICENSE.txt)：当前抓取页面标注 Dev Builds，不继承旧草稿“1.12 稳定”的断言。
- [l4dtoolz](https://github.com/lakwsh/l4dtoolz/blob/main/README_EN.md)：容量、玩家上限与 lobby 限制分别处理。
- [MultiSlots](https://raw.githubusercontent.com/fbef0102/L4D1_2-Plugins/master/l4dmultislots/readme.md)：额外生还者生成及独立依赖。
- [Infected Bots](https://raw.githubusercontent.com/fbef0102/L4D1_2-Plugins/master/l4dinfectedbots/readme.md)：特感插件本身的运行依赖，不等于多人角色生成器。
