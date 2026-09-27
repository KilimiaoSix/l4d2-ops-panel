# 新手安装与使用优化交付状态

已发布 [2.1.0 正式版](https://github.com/KilimiaoSix/l4d2-ops-panel/releases/tag/v2.1.0)，源码为 `34b9f61354dd47ce74f89ce2fcee7f8a828c888f`，保留此前密码兼容修复并合入轻量监控。2026-09-28 用户明确授权合入 main、正式上线并保留双方工作，原生产冻结已解除；真人满员等未测项目继续开放。资源使用 GitHub，不使用游戏服务器提供下载；独立镜像为可选。下表保留旧候选证据的版本范围。

## 实现范围

- 网页开服向导、未安装状态、加入服务器说明和向导恢复。
- owner 面板配置、原子保存、systemd 重启握手及配置回退。
- 最小/全套插件包、固定来源、逐文件安装事务和已有配置保护；L4DToolZ 使用官方固定版本下载并校验哈希。
- 中文服名、进服密码、地区、4–12 人配置和逐项生效结果。
- GitHub CI、完整 Linux 发布包、签名验证、root 安装器、更新及恢复命令。

## 验证证据

| 范围 | 结果与证据 |
|---|---|
| 2.1.0 CI 与签名 | [CI 36334541944](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36334541944) 的 Python 3.10/3.12 各 545 项、前端及实际 tar 11 项通过；[正式签名 36334541763](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36334541763) 成功，本地/服务器独立验签，五个公开资产摘要一致 |
| 2.1.0 既有生产部署 | 14 项隔离预检、生产 10 个登录 GET 接口、公网 HTTPS 健康与前端资源通过；保留 2 个账号、143 个原游戏配置/插件文件哈希、证书和配置，游戏进程未重启 |
| candidate.12 CI 与签名 | [CI 36316205655](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36316205655) 四项通过，Python 3.10/3.12 各 530 项；[正式签名 36316206084](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36316206084) 成功，下载后独立验签、五个公开资产 digest 核对和匿名 get.sh 下载哈希通过 |
| candidate.12 实际包实服 | GitHub 正式签名 tar 在独立服务器通过真实 HTTP/RCON/UDP 42 项，涵盖升级保留配置、密码初始状态/设置/清除、卸载保护/晚加载、4/8/12 参数重启、空服换图及清除后重启，无插件运行错误；详见[密码修复记录](join-password-fix.md) |
| GitHub CI | 提交 `26dcd33` 的 [run 36288551619](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36288551619) 四项全部通过：Python 3.10.20/3.12.13 各 528 项、Node 22.22.0 前端构建、完整包构建/临时签名/最终 tar 安装 11 项 |
| 正式密钥签名及公开下载 | [run 36288569886](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36288569886) 使用 main 限定的 release secret 成功签名；下载工件独立验签，五个 Release 资产的 GitHub digest 与本地逐一一致 |
| GitHub 默认安装 | 两套全新 Ubuntu 22.04/24.04 systemd VM 从公开 GitHub 下载 get.sh 及包，无 mirror/offline 参数，验签及安装均退出 0；HTTPS 登录、非 root UID、systemd/HTTP PID、唯一 owner、数据库、0600 权限、Docker 29.8.1/Compose 5.5.1 均通过，见[安装记录](github-candidate11-installation.json) |
| 引导故障与更新回归 | candidate.10 的本地独立 Ubuntu 22.04/24.04 VM 已完成重跑、更新、失败回退及数据保留；包括错误签名/哈希、磁盘、证书和归属拒绝。candidate.11 的安装器 Python 代码未改变 |
| 真实游戏引擎 | candidate.11 的实际发布包在隔离服务器容器完成 HTTP/RCON 29 项，覆盖升级插件并保留用户配置、中文名称、4/8/12 人服务端配置、重启和换图保持，无插件运行错误；签名构建另通过最终 tar 最小/全套插件事务 11 项 |
| 既有安装兼容 | LinuxGSM 只读兼容 14 项，135 个生产游戏文件哈希保持一致；高级安装脚本保留已有配置 |
| 向导恢复 | 真实 HTTP/新进程/Docker 协议夹具 17 项，覆盖下载失败后重试、最小/全套安装、完成及重开；不等同于真人游戏验证 |
| 发布信任材料 | 独立 RSA-3072 公钥已入库，正式签名实跑和独立验签均通过；GitHub `release` 环境 secret 仅允许 `main`，见[配置记录](release-signing-provisioning.json) |

本机两套 VM 使用现有 HTTP 代理访问 GitHub；它们证明 GitHub 资产及默认下载路径可用，不代表国内网络直连。既有服务器另以无代理方式下载公开 get.sh，HTTP 200 且 SHA256 一致，未在生产执行安装。原始报告保留在维护者工作区；公开记录不含生产数据、私钥或安装凭据。

candidate.10 已完成 V1–V6 的故障、配置、向导和浏览器回归。与该包比较，candidate.11 的安装器代码相同，后端 Python AST 差异只有构建版本；文本换行及重新编译导致归档和部分产物哈希变化，因此重新验证了公开包安装与实际游戏插件。历史证据保留原候选编号，不将未复跑的检查写作 candidate.11 实测。

用户已合并 PR #1，并授权后续直接合入 `main`，无需新 PR。随后 CI 暴露审计测试的时序假设：异步监控尚未完成就请求插件重载，正确返回 409。测试已增加有界等待，11 项定向回归和上述全量 CI 均通过，应用的并发保护保持有效。

## 尚未完成

已在独立测试服定位原生密码兼容问题并验证工作版修复：正确密码进入并能控制角色，错误密码被拒绝，公网 UDP 查询恢复。细节及证据边界见[进服密码修复记录](join-password-fix.md)。修复已随 candidate.12 发布，candidate.11 不包含该修复。安装器、网络/恢复 helper 及 Python 运行依赖文件与 candidate.11 逐字节一致，双 Ubuntu 安装证据继续明确标为 candidate.11。

1. 补齐空/清除密码真人测试，以及第五名真人、8/12 人满员、重连和实际游玩。服务端清除密码、重启/换图、正式 SDK 触发的实际暂停/恢复保护已通过。用户目前只有一名真人可参加，多人验收保留待验证，不以机器人或人数参数替代。
2. 补齐真人验收后才能将 7.3/7.3a 标为完成并归档 OpenSpec。用户已于 2026-09-28 单独授权在此之前正式发布与生产切换；部署工作由 7.7 单独记录，不视为剩余游玩测试通过。

2.1.0 的发布、生产切换、本机备份校验及旧测试资源清理均已完成，详见[生产交付记录](../2026-09-28/production-release-2.1.0.md)。完整真人验收继续保留上述限制。
