## Why

正式服旧采样器常驻启用 SourceMod VProf，并每 15 秒扫描不断增长的控制台日志；根盘使用率约 90%。用户于 2026-09-28 授权轻量监控、关闭详细分析、优化存储及按社区常见情况优化，要求不影响正在进行的游戏。

## What Changes

- 以限频只读 RCON 查询替换控制台扫描，保留面板 CSV 契约，关闭常驻 profiler。
- 为采样数据、控制台日志设置有界保留与后台服务，保留游戏错误日志。
- 备份后清理确认停止、可重建的测试容器和镜像缓存，不删除测试配置、修改成果或生产资源。
- 对现有 30 tick 服务器应用有依据的保守设置：消除冗余日志回显，匹配快照频率上限；保留现有玩法、刷怪、武器和网络速率预算。
- 记录前后状态、回滚和未解决的地图因素。

## Capabilities

### New Capabilities
- `lightweight-server-operations`: 低开销采样、有界存储和不重启的运维优化。

### Modified Capabilities

无 API 行为变化。

## Impact

涉及 tools/perf-sampler.sh、新 Python 采样器及测试、部署用 systemd/logrotate 文件、运维文档；正式服调整采样进程、日志策略、两项 cvar 和已停止测试缓存。不会重启面板或 srcds、切图、安装新插件或调整玩法。地图 VScript 报错保留为独立问题，本变更不未经引擎验证地覆盖地图脚本。
