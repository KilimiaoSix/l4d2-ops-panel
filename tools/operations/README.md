# LinuxGSM 轻量监控

已有 LinuxGSM 面板环境中使用，Docker 后端已有面板内采样，不重复安装。默认路径及用户为 `/home/l4d2server` / `l4d2server`；其它安装需同步修改 unit、logrotate 和环境变量。所有命令在服务器执行；替换前先备份旧脚本、用户 crontab、server.cfg 和已有采样数据，核对游戏进程。不要将含密码的配置/备份提交到仓库。

`perf-sampler.sh` 用已有 panel venv 运行 `perf-sampler.py`，复用 panel RCON，读取 panel.json 与 server.cfg。有人时每 15 秒只读 `status` + `stats`；空服/失败间隔 60 秒，失败不记录虚假样本。错误日志每 10 分钟至多一条且不包含异常正文。仅保存汇总指标，不保存玩家名称、地址或 SteamID。

CSV 路径来自 panel.json 的 `perf_csv`，可用 `OUT` 覆盖。格式保持 `time,humans,cpu%,in_bytes,out_bytes,fps,players`；网络单位沿用 srcds stats 的 bytes/s。单文件 4 MiB、两份历史（约 12 MiB），保持原面板读取方式。旧数据不会因升级主动丢弃，下一次到达上限时轮转。单实例锁位于 CSV 旁的 `.lock`；只读探测也会获取锁，防止与服务同时写入。

将两个 `perf-sampler.*` 文件部署至 `$L4D2_HOME/tools/`（LF 换行），服务文件部署到 `/etc/systemd/system/`，logrotate 配置部署为 `/etc/l4d2-ops-logrotate.conf`。先 `bash -n`、`systemd-analyze verify` 和 `logrotate --debug` 检查。停掉已核对身份的旧采样进程；仅删除 crontab 中旧 sampler 的启动行，保留 LinuxGSM start/monitor。通过现有 RCON 执行一次 `sm prof stop`、`vprof_off`，不要 dump 详细数据。

```bash
# 服务启动前的一次真实探测，可在空服检查 CSV / 面板兼容性。
sudo -u l4d2server env L4D2_HOME=/home/l4d2server /bin/bash /home/l4d2server/tools/perf-sampler.sh --once --include-empty
sudo systemctl daemon-reload
sudo systemctl enable --now l4d2-perf-sampler.service l4d2-logrotate.timer
sudo systemctl start l4d2-logrotate.service
sudo systemctl status l4d2-perf-sampler.service --no-pager
```

logrotate 每小时检查一次，达到 64 MiB 或每天轮转，保留 4 份压缩历史。copytruncate 保留游戏已打开的日志文件，复制和截断间存在极短丢行窗口；首次建议空服执行。它只处理活动控制台日志及旧 sampler.out，游戏和 SourceMod 错误日志继续保留。它是轮转阈值，不是磁盘硬配额；一小时内仍可能临时超过 64 MiB。LinuxGSM 自身重启时另行归档的控制台日志不在本规则内，定期运维时单独核对。

`ops-performance.cfg` 是本次现有 30 tick 服务器的专用配置，不由面板安装器默认强推。确认实际 tick 后，备份 server.cfg，再在其末尾加入 `exec ops-performance.cfg`；运行时分别设置相同的两项值，无需重新 exec 整个 server.cfg。关闭 `sv_logecho` 只减少重复回显，`sv_logfile` 和 SM 错误日志保持；`sv_maxupdaterate 30` 匹配现有 tick。不要据此增加 tick、盲目增加 rate、调低插值或改刷怪预算。

回滚：停止/禁用新 sampler 和日志 timer，恢复已备份的 server.cfg 与对应动态 cvar。保留 CSV 和日志备份。旧 sampler 含常驻 profiler，不建议重新启用；临时关闭采样也不影响游戏。所有操作均不需要重启 srcds 或切图。
