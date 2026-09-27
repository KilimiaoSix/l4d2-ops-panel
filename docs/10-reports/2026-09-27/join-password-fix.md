# L4D2 进服密码修复与真人验收

活动任务：`beginner-deployment-plan` 7.3 / 7.3a；需求 B2/B5/O4。2026-09-27，游戏版本 2.2.4.3 build 10097。公开 candidate.11 不包含本修复。

修复已随 [candidate.12](https://github.com/KilimiaoSix/l4d2-ops-panel/releases/tag/v2.1.0-candidate.12) 发布，源码 `49ea5f1`。[CI](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36316205655) Python 3.10/3.12 各 530 项、前端和最终包安装通过；[正式签名构建](https://github.com/KilimiaoSix/l4d2-ops-panel/actions/runs/36316206084)及独立验签通过。GitHub 正式 tar SHA256 `d119964dfc72d7340f7787cfccfe6d1824c5b2b72825979e05f25da7259141cc` 已复跑下述实服 42 项，全部通过；上传五个资产的 digest 与本地验签文件一致，公开 get.sh 匿名下载哈希也一致。

## 故障证据

云侧放行后，公网 UDP 已进入测试容器并被 srcds 进程接收，但原生非空 `sv_password` 导致查询无回复，客户端密码窗口输入后无进展。四组对照中，原 SDK 与镜像 SteamCMD SDK 均在密码非空时查询失败、密码为空时成功，因此排除 SDK 更换方案。Valve 的[问题记录 #3416](https://github.com/ValveSoftware/Source-1-Games/issues/3416)描述了相同密码窗口现象。

最小包 v2 增加 `Panel Join Password`，在连接阶段校验专用 `l4d2_password` userinfo；正常运行时清空原生密码运行值，继续保留 Steam 认证。配置及卸载/暂停保护使用实际设置的密码，不使用公开固定保护密码。插件回执只包含是否就绪、是否要求密码，不输出密码。

## 已有验收

| 检查 | 结果与范围 |
|---|---|
| 公网 UDP | candidate.11 加载工作版插件后，外部实际 A2S 查询成功 |
| 正确密码 | 用户确认进入地图并能控制角色；服务器同步记录 1 名真人 |
| 错误密码 | 用户断开后设置错误 userinfo，确认被拒绝并显示 `Wrong join password` |
| 客户端资源一致性 | 首次进入被 `scripts/weapon_sniper_scout.txt` 一致性检查拒绝；仅独立测试服临时设 `sv_consistency 0` 后进入成功 |
| 自动化回归 | 初版修复 Linux Python 3.10 全量 530 项通过，前端类型检查/构建通过，实际 tar 插件安装 11 项通过；保护逻辑复核修改后相关 HTTP/配置回归 32 项通过 |
| 最终本地候选包 | candidate.12 本地构建 tar（SHA256 `17694e716a5ced9091fe0a936cd3959974bc2f7e2e08104088fe351a056d408d`）经实际插件升级事务安装，真实 HTTP/RCON/UDP 共 42 项通过；覆盖初始就绪、原生赋值迁移、卸载保护/晚加载、清除密码、4/8/12 配置重启、空服换图和清除后完整重启，无插件运行错误 |

真人测试使用独立 Docker 测试服和临时密码，非正式生产。TCP/RCON 绑定 localhost，公网只发布游戏 UDP。测试用 SDK 替换没有进入产品；`sv_consistency` 产品默认值没有改变。

## 待补证据

空 userinfo 拒绝、清除密码后真人进入仍待反馈；服务端保存/清除与生命周期检查已经通过。暂停测试起初使用了不存在的 `sm plugins pause` 命令，实际仅返回帮助，因此撤销这项无效测试并明确记录未实测。SourceMod 1.12 的 `CPlugin::SetPauseState` 源码确实在暂停运行时前调用 `OnPluginPauseChange`，当前仅完成该路径源码审查。

真实回归发现空服休眠会延后配置完成回调：换图及空密码首次启动可能一直停留在未就绪。最终插件在加载时读取当前变量，以钩子处理后续密码赋值；不再将首次初始化或换图就绪依赖该回调。上述 42 项使用修正后的实际 tar，先前失败结果不计为通过。

第五名真人、8/12 人满员、多人重连和实际游玩尚未验证。正确密码与错误密码的真人测试使用早先手动加载工作版插件，不将它们改写为最终签名包的真人验收。
