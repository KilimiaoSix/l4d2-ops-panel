# L4D2 专用服务器踩坑笔记（Linux）

在腾讯云 Ubuntu 24.04 上从零搭一台 10–12 人合作服时踩到的坑，都是实测过的。

## 引擎 / 配置

1. **cfg 文件不能有任何非 ASCII 字符，包括注释。** `cfg/server.cfg`、`cfg/sourcemod/*.cfg` 由引擎解析，多字节字符会被当成命令分隔符：轻则配置失效，重则死循环 + 段错误。SourceMod 自己读的文件（translations、configs、data）可以用中文。检查：`grep -l -P '[^\x00-\x7F]' cfg/server.cfg cfg/sourcemod/*.cfg`。cvar 描述是中文的插件，`AutoExecConfig` 会生成带中文注释的 cfg，同样会炸——改成 `AutoExecConfig(false, …)` 并自己提供 ASCII 版。
2. **中文服名**在 cfg 里设不进去（同上），只能由插件 `SetString` 直接写 cvar。
3. **隐藏 cvar**（`mp_gamemode`、`z_common_limit`、`nb_update_frequency`、`sv_maxupdaterate`、`sv_hibernate_when_empty`、`sv_airaccelerate`…）控制台直接设会报 Unknown command，要 `sm_cvar xxx 值`。
4. L4D2 **不支持 `+servercfgfile`**，永远执行 `cfg/server.cfg`。
5. 服务器**不回应发到 127.0.0.1 的 A2S 查询**，对网卡 IP 正常。LinuxGSM 的 monitor 查 `${ip}`，绑 0.0.0.0 会被判为挂掉反复重启——实例配置里写 `ip="内网IP"`。
6. `sv_setmax`（l4dtoolz）最大 31 个槽位：人 + 特感 + Tank ≤ 31。
7. `stats` 命令的 In/Out 列单位是**字节/秒**，不是 KB/s。
8. `fps_max` 专用服固定 30，`sv_parallel_packentities` / `sv_parallel_sendsnapshot` 默认已开，不用调。
9. **L4D2 会对 A2S 查询限速。** 公网服务器被各种扫描器持续查询，单次查询经常落在限速窗口里超时。做监控要重试几次，进程还在时再用 RCON 确认一遍，不要一次超时就判定挂了。

## SourceMod 在 L4D2 上

- `OnConfigsExecuted` **永远不触发**（引擎没有 `servercfgfile`），插件初始化用 `OnMapStart`。
- `server.cfg` 在 `OnMapStart` **之后**执行，会盖掉插件在 OnMapStart 设的同名 cvar。
- 服务器休眠（没人）时 **定时器不跑**，不要依赖 `CreateTimer` 做一次性初始化。
- l4dtoolz 是引擎级 VSP：`addons/l4dtoolz.vdf` + `.so` 放 `addons/` 根目录，不是 `addons/metamod/`。

## 下载 / 更新

- **SteamCMD 匿名 `app_update 222860` 报 "Invalid platform"**（2024-11 至今，Valve 给这个 app 的 oslist 只写了 windows）。用 [DepotDownloader](https://github.com/SteamRE/DepotDownloader)：`DepotDownloader -app 222860 -os linux -dir <serverfiles>`。
- 创意工坊物品也可匿名拉：`DepotDownloader -app 550 -pubfile <id> -dir <dir>`。
- 国内云主机访问 raw.githubusercontent.com 常常卡死：LinuxGSM 的模块、配置需要在能上 GitHub 的机器下好再传；`update-lgsm` 别在服务器上跑。
- AlliedMods 论坛在 Cloudflare 后面，脚本抓不到附件；找源码去 GitHub：`dvander/sourcepawn-corpus`（论坛附件镜像）、`fbef0102/L4D1_2-Plugins`、`apples1949/douban-l4d2-plugins-set`、`fantasylidong/anne`、`Target5150/MoYu_Server_Stupid_Plugins`。
- `actions.ext` 扩展只在论坛发布，依赖它的插件（如新版 l4d_afk_commands）拿不到就装不了。

## LinuxGSM

- `./l4d2server send` **不带参数**时进入交互提示，在没有终端的脚本/cron 里会死循环吃满 CPU 和内存（实测 40 分钟 3.2GB 后被 OOM）。脚本里改用 `tmux -L <socket> send-keys -t l4d2server "命令" ENTER`。
- Ubuntu 24.04 没有 `libtinfo5`，从 22.04 的源装 `libtinfo5:i386`（或 LinuxGSM 自带的 symlink 修复）。

## 带宽

30 tick 下每个玩家出流量约 30 KB/s（`sv_maxrate 30000`）。3M 带宽 10 人就顶满，12 人以上至少 5M。普通僵尸是流量大头，人多时把 `z_common_limit` 往下调比把特感往下调划算。
