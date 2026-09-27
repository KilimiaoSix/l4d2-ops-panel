## Context

调用路径为 cron -> tools/perf-sampler.sh -> tmux stats/profiler -> 全量控制台扫描 -> CSV -> Monitoring.perf_rows/latest_perf。已读取采样脚本、RconClient、Monitoring、Settings/Paths、FakeGame 及正式服配置。生产 PID 3523205，面板保持在线；主要磁盘浪费是停止的隔离测试 Docker 镜像，测试绑定目录仍有验收成果。

## Goals / Non-Goals

目标：低成本可用指标、无常驻详细分析、有界数据增长、降低磁盘压力并可回滚。

非目标：解决未经现场复现的客户端渲染掉帧、升级 tick、改变武器/刷怪/难度、改地图包或生产服务重启。

## Decisions

1. 用 Python CLI 复用 panel 的 RconClient/read_rcon_password/STATUS_SUMMARY；只发送 status、stats。有真人 15 秒采样，空服 60 秒仅查 status，失败退避 60 秒且不伪造数据。保留原 7 列 CSV 及 bytes/s 单位。状态不落玩家隐私数据，凭据从现有配置读取，不进入参数/日志。
2. Shell 入口仅定位已安装 panel 的 Python 环境并 exec；systemd 管理独立进程，以文件锁防重复，低 CPU/IO 优先级。替换旧 cron 采样项但保留 LinuxGSM monitor/start。旧采样器停掉后仅执行 prof stop/vprof_off，不 dump。
3. CSV 每文件最多约 4 MiB，最多两份历史。控制台日志用 logrotate copytruncate（不丢失打开的 FD；存在极短复制/截断竞态），64 MiB 或每天轮转，保留 4 份压缩历史；单独每小时触发轮转检查。普通游戏日志保留，关闭重复 sv_logecho；SourceMod 错误日志保留。
4. 现有 sv_maxupdaterate 60 超过实际 30 tick，配置为 30；不增高 tick、rate 或并行开关，不按未经证实的网络秘方调参。动态与持久配置一致，写入专用 cfg 并由 server.cfg 末尾 exec。备份原文件和动态值。
5. 清理前核对容器处于 exited、无生产关联、绑定成果仍在；备份 inspect、diff 和小量可写层（若有实际独有成果则不删），只删除两项已知测试容器及其无其它使用者的镜像。生产 serverfiles、测试 bind 数据和原始地图压缩包保留。清理作低优先级并观测玩家/PID。

## File / Layer Map

| 文件 | 层及改动 |
| --- | --- |
| tools/perf-sampler.sh, tools/perf-sampler.py | 独立采样入口和业务控制；复用现有 RCON 集成 |
| tools/operations/* | systemd 服务、定时日志轮转和 logrotate 模板 |
| panel/tests/unit/test_perf_sampler.py | 真实本地 TCP RCON 协议、空服/错误/轮转/配置路径验证 |
| README.md, docs/development.md | 保留现有改动，追加采样安装与运维说明 |
| docs/10-reports/2026-09-28/*, docs/09-agent-work-log/logs/* | 授权、执行证据、回滚与限制 |

## Risks / Trade-offs

copytruncate 在写入瞬间有小量日志丢失窗口，因此保留游戏/SM 独立日志，并在空服首次轮转。删除镜像意味着下次隔离测试需要重新拉取，配置和测试目录保留。降低重复日志与 profiler 开销不保证消除池核救援关渲染掉帧；地图脚本错误与实体/特效负载仍需单独复现。sampler 依赖已安装面板环境；缺失时明确失败，不自动安装或启动 profiler。

## Migration / Rollback

2026-09-28 协调更新：用户在安装发布聊天中明确授权“允许协调，保留双方工作”。该聊天负责完整备份到本电脑、面板发布及统一测试资源清理；本变更提供核对清单与结果核验，不并发删除资源或部署面板。等待该聊天确认原配置/工具已备份后再部署监控和 cvar，避免备份竞争。

在专用备份目录保存原 sampler、crontab、server.cfg、动态 cvar 和容器元数据/差异。验证本地协议测试与 bash/systemd/logrotate 语法，部署新 sampler 后保持游戏 PID 不变验证真实 RCON 与面板 CSV 读取。回滚时停止新采样服务，恢复备份配置并恢复原动态 cvar；旧脚本仅供审计，不建议重新启用其 profiler。Docker 镜像按保存的 image digest/compose 配置重新拉取和重建。
