# 开发实施清单

本清单已于 2026-09-27 进入用户授权的实施阶段，**不因规划完成而勾选**。先读 design.md；每项完成需同时提交代码、对应测试及结果。`R/O/C/P/B` 对应 specs 内的 Requirement 编号，`V0–V8` 对应设计验证矩阵。安装测试允许本机 Docker，或服务器上的独立容器、目录和端口；不得把现有游戏服当成干净安装目标。

当前授权（2026-09-28）：用户已解除生产冻结，要求本次面板/安装相关工作合入 main、正式发布并部署，由用户继续实玩；先将完整备份放到本电脑并校验，保留现有其他工作和全部插件，再清理旧测试资源。与性能优化聊天协调保留其改动。第五人及 8/12 人满员验收继续待验证，不将上线授权等同测试通过。

2026-09-27 实测证据集中于 [交付状态及验收证据](../../../docs/10-reports/2026-09-27/beginner-delivery-status.md)。main 提交 `26dcd33` 的 [CI](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36288551619) 四项通过：Python 3.10.20/3.12.13 各 528 项、前端构建、完整 tar/临时签名/实际安装。正式密钥[签名构建](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36288569886) 和独立验签通过，candidate.11 已公开于 GitHub。7.2 的 candidate.10 已执行 V1–V6 回归；candidate.11 补充真实 GitHub 无镜像双 Ubuntu 首装、实际 tar 安装和真实引擎 29 项复测。安装器代码不变，后端 Python AST 差异只有构建版本；旧故障/浏览器证据保留原版本标识。1.3 的容量 profile 已经真实引擎验证；7.1 的断线恢复采用真实 HTTP/进程/Docker 协议夹具。二者均不代替 7.3 的第五名真人与满员游玩验收。

## 1. P0：跨里程碑契约与基线

后续增量：`49ea5f1` 的 CI（Python 3.10/3.12 各 530 项）、正式签名及实际签名 tar 实服 42 项通过，candidate.12 已发布。官方 SDK 探针另完成真实暂停/恢复保护及清理的 9 项检查。工作版已有单名真人正确密码进入、错误密码拒绝证据；空/清除密码真人行为及多人满员仍缺证据，因此 7.3/7.3a/7.6 继续保持未完成。

- [x] 1.1 保留并核对现有 README/Steam 未提交改动；在 Linux 建隔离开发环境，运行现有 pytest 与前端构建，记录原始失败；确认 FastAPI/uvicorn/Vite 实际锁定版本（V8）。
- [x] 1.2 创建 `panel/packs/manifest.json` 的 schema、真实依赖/冲突与文件策略；确定唯一 `packs/payloads` 路径、收据与事务版本格式，提供同一清单消费测试（R1/P1）。
- [x] 1.3 在 `tools/release/upstreams.json` 固定 Metamod/SourceMod、l4dtoolz、生还者管理、Infected Bots、Points 及依赖的 URL/commit/哈希/架构/许可；区分编译与运行依赖，验证多人生还者+特感容量 profile；没有可再分发材料的包不得算全套完成（R1/P1/B3）。
- [x] 1.4 锁定 Python 直接/间接依赖和 CI Node/Python；确定真实 GitHub Releases 入口、签名格式、公钥轮换与发布 secret；记录 get.sh 初始信任、GitHub 下载与可选镜像/离线获取方式；实跑正式签名（R1/R2，按用户 2026-09-27 指示不使用服务器提供资源）。
- [x] 1.5 先写 API/type 契约和测试表：配置字段生效表、向导状态、插件收据、基础设置结果、错误状态及角色权限；更新本 change 与现有开发文档（O1/C1/P1/B1）。

## 2. M1a：配置、状态与恢复底座

- [x] 2.1 修改 main/context 显式传递真实 conf 路径；增加 `--check-config`，未知新字段报错且不更改旧 load_settings 兼容规则；进程内 fixture 写实际配置，测试外置 conf（C1/V3）。
- [x] 2.2 增加 integrations/panel_config：保留原文未知键、revision、字段校验、0600备份、原子写、无变化不写、版本安全恢复；覆盖同端口、变端口、TLS配对和权限（C1/C2/C3）。
- [x] 2.3 增加 store/panel_state 幂等迁移；全新库明确 false，旧库一次性回填；修复原 AuthService/AccountStore 并发初始化，两个请求得到成功和409，旧密码/会话不重建（O1/R4）。
- [x] 2.4 在 jobs 与 server_control 引入最小重启协调入口：任务注册/游戏操作/相关写入共享 pending 门；带锁快照、繁忙409、失败清 pending，覆盖并发起任务竞态（C4/V3）。
- [x] 2.5 增加 PanelConfigService/API 与审计：白名单、只写秘密、热更新所有快照、游戏已安装时锁目录和Docker身份；重启参数未确认不保存；验证401/403及真实成功路径（C1/C2/C3）。
- [x] 2.6 增加受systemd管理的优雅退出、boot/revision握手、磁盘pending、有界启动回退和 `--restore-config`；standalone禁用自退，失败不死循环（C4/C5）。
- [x] 2.7 扩展子进程夹具重新读取端口/TLS、追加日志并清理旧句柄；进程内FakeInstaller测归属锁定，真实进程/VM测试换端口、失败回退、任务互斥；不能只mock重启（V3/C5）。

## 3. M1b：发布与零交互引导

- [x] 3.1 新增 tools/release 构建工具：校验固定上游、构建SPA、用配套spcomp64编译自带插件、生成预设、规范化载荷和逐文件清单；路径/类型拒绝与编译器可执行位测试（R1/P1）。
- [x] 3.2 新增 GitHub CI/release workflow：Linux Python矩阵、前端类型/构建、完整tar契约与秘密排除、签名/哈希篡改用例；消费实际tar中的清单和载荷（R1/R2/V1）。
- [x] 3.3 实现 get.sh 前半：平台/root/systemd守卫、互斥锁、归属检测、主/镜像下载验证、staging、用户和服务用户venv；拒绝接管旧目录（R2/R3）。
- [x] 3.4 实现 get.sh 后半：官方签名apt或经验证镜像的Docker安装、服务用户权限、初始配置/随机密码、IP/DNS证书、systemd daemon-reload/start、实际版本健康探测、准确退出码（R3/R4）。
- [x] 3.5 实现显式重跑/指定版本更新与失败恢复，保留DB/WAL/证书/配置/下载/pack_state/docker数据，确认新进程而非旧HTTP200；提供 `--repair-docker` 和受限网络helper（R5/R6）。
- [x] 3.6 实现 root-owned `l4d2panel-recover` 包装器，以服务用户恢复应用配置；TLS和云端口说明明确，旧install.sh保留高级路径、修复可选清空语义并保护已有panel.json（C5/R5/R6）。
- [x] 3.7 在两个干净Ubuntu systemd VM执行真实Docker首装、镜像回退、失败重跑、版本替换、证书/占用/权限场景；保留可复核日志和资产校验（V2）。

## 4. M1c：向导骨架与未安装状态

- [x] 4.1 增加 onboarding store/service/API：持久step、非秘密草稿、完成检查、旧库迁移、主动重开向导；在游戏安装完成前不写game_dir（O1/O2）。
- [x] 4.2 修复 AddonService.list 等未安装读取，逐页核对九个视图、上传及Steam管理员绑定副作用；返回空状态/预期错误且不预创建游戏目录（O2）。
- [x] 4.3 新增 PanelSetupView/PanelRestart 和统一未安装入口；配置高级表单、忙碌/失效响应处理、卸载清轮询；修改LoginView实际显示重启原因（O1/C5）。
- [x] 4.4 浏览器验证同源与跨源重启、Secure cookie变化、90秒超时、老地址恢复、未装游戏全导航；M1只标记为面板底座，待M2/M3接入（V3/V4）。

## 5. M2：最小安装和可选插件包

- [x] 5.1 新增注册表读取/校验/依赖解析，已知id、环/缺依赖/冲突、架构及文件策略验证；所有包以最终release载荷为来源（P1/R1）。
- [x] 5.2 新增插件安装文件事务：全量预检、停止态/staging、源目标路径防越界和链接、ASCII cfg、逐文件备份与版本安全回滚、持久journal/收据、取消与崩溃恢复；覆盖每一提交阶段失败（P2/P3）。
- [x] 5.3 新增 PluginPackService/API，沿用登录管理权限和共用operation_lock；明确stop_game确认，直接协调底层停服避免递归死锁；统一文件数进度和审计，GET无副作用（P2/P3/P4）。
- [x] 5.4 接入FeatureDetector显式失效/重试，ServerControl start/restart完成回调；区分installed/active/unknown/restart_required，sipreset依赖不足不报可用（P4）。
- [x] 5.5 新增PluginPackCard挂插件页和向导，最小默认、全套/按能力勾选、依赖解释、补装、冲突、取消/恢复与重启操作（P1/P4）。
- [x] 5.6 验证保护管理员/白名单/hostname/IB数据/第三方配置；已有非托管框架冲突不覆盖；安装完整SourceMod的addons和cfg；真实引擎验证最小/全套/后续补全（P2/P3/V5）。

## 6. M3：基础设置、中文和多人

- [x] 6.1 有限扩展CFG直接赋值编辑，基础与游戏模式共用SERVER_CFG_LOCK，单次备份/替换、不改无关字节；空密码读写往返、重复定义、复合命令拒绝与并发模式/伤害回归（B1/B2）。
- [x] 6.2 新增hostname_file、panel_hostname.sp及CI编译/最小包项；UTF-8规范字节、ASCII精确回执、防重入/有界覆盖纠正、配置和data多文件事务；真实换图/重启/休眠验收（B1/V6）。
- [x] 6.3 将P0验证的多人profile接入Docker受控启动脚本/配置与能力检测；区分sv_setmax、sv_maxplayers、生还者数量，处理lobby、特感/Tank预算及需重启项，保留模式起始地图逻辑（B3）。
- [x] 6.4 新增BasicSettingsService/API、审计和逐项应用结果；地区范围、密码省略/清空/遮蔽、save/apply/save_apply、版本冲突、配置失败不发RCON；不以缓存缺失阻断实际能力探测（B1/B2/B3/B4）。
- [x] 6.5 扩展FakeGame的普通/SM赋值、引号空串、protected拒读、未知cvar、hostname回执、人数能力与失败；新增真实HTTP parity，不只测模型或回显（B4/V6）。
- [x] 6.6 新增BasicSettingsView/JoinServerCard并复用页脚，准确字节计数、保存/运行分离、依赖补装、4–12人数及边界、地址与TCP/UDP指引、开发者控制台和客户端地图说明（O3/O4/B1/B2/B3）。

## 7. E：完整闭环与交付

- [x] 7.1 把游戏、插件、基础设置、必要重启、加入说明接入向导；测试首次最小、首次全套、后续补全、中途断网/刷新/面板重启与重试（O1/O2/P4）。
- [x] 7.2 用发布候选tar在干净Ubuntu复跑V1–V6；核实脚本及签名资产可从真实 GitHub Releases 固定版本获取，无镜像配置可安装；可选坏镜像/坏签名失败且不修改原安装（R2/V2）。
- [ ] 7.3 用真实外部游戏客户端验证进服密码/错密码/清除密码、中文服名、4/8/12人（含第五人生还者）、换图、掉线重连、所选特感预算；记录确切版本和组合，未测项不宣称兼容（V7/B1/B2/B3）。
- [ ] 7.3a 修复实测的 L4D2 原生 sv_password 导致查询静默及密码窗口卡住：最小包提供进服校验插件，保存兼容密码及失效关闭保护，客户端使用专用 userinfo；验证密码设置、清除、错密码、重启/换图和插件不可用，独立实测 UDP，不以 RCON 或安装元数据代替 A2S（B2/O4/V7）。
- [x] 7.4 全量pytest、前端构建、Docker smoke与旧LinuxGSM兼容回归；更新测试fixture的所有精确features字典和真实路由鉴权用例（V8）。
- [x] 7.5 README改为新手入口与高级路径；development更新架构/API/发布；提供证书、网络、插件来源、数据保留、恢复说明，逐需求填写证据矩阵并执行OpenSpec strict（R6/V0–V8）。
- [ ] 7.6 补齐剩余真人验收后同步稳定 spec 并归档；未验证项保持开放。2026-09-28 用户已单独授权提前正式发布并上线，由 7.7 执行，不据此勾选 7.3/7.3a。
- [ ] 7.7 按 2026-09-28 授权完成生产交付：核对双方工作，合入 main；完整备份现有面板、数据库、全部插件/配置/数据及服务配置到本电脑并验证；发布签名正式包，部署到既有 LinuxGSM 面板并保留当前游戏/插件；验证健康、账号、接口和备份；只删除已确认的旧测试资源，保留后续真人验收的已知限制。
