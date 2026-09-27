# 插件包接口与文件契约

当前清单 schema、载荷索引 schema、收据和事务 schema 均为 1。唯一源是 `panel/packs/manifest.json`；构建器生成 `payload-manifest.json` 和 `payloads/<id>/`。开发环境未生成某个载荷时，API 明确显示不可用，完整发布构建必须失败，不把缺失包当成空包成功。

| HTTP | 输入 / 输出 | 权限与失败 |
|---|---|---|
| GET `/api/plugin-packs` | 包名、依赖、版本、可用载荷、历史安装收据、未完成事务、文件数量进度；`probe=true` 实际查询运行插件 | 登录账号；GET 不下载、写收据或恢复事务；暂时不可达为 unknown |
| POST `/api/plugin-packs/install` | `packs: string[]` 默认 minimal，`stop_game: boolean` 默认 false；返回 job 与依赖闭包 | 沿用插件管理权限；400 未知 ID/字段/冲突；409 未安装游戏、操作繁忙、未确认停服、残留事务 |
| POST `/api/plugin-packs/cancel` | `{}`；请求协作取消 | 正在提交的文件进入版本检查回滚；不能把取消当成删除整个目录 |
| POST `/api/plugin-packs/recover` | `stop_game`；返回后台 job | 同一停服与操作锁；只恢复事务仍拥有的版本，遇外部修改保留 incomplete |

收据位于面板私有可变目录 `pack_state/receipt.json`，绑定绝对游戏目录，记录包版本、事务 ID、安装时间与逐文件 SHA256/策略/所属包。`managed` 文件允许首次写入、与目标完全相同的文件或上次收据未被修改的文件；其它同名文件冲突。`seed` 文件只初始化缺失项，已有管理员、白名单、中文服名、IB 数据及插件参数保留。载荷和目标拒绝路径越界、符号/硬链接、特殊文件；`cfg/*.cfg` 的命令和注释均需 ASCII。

安装和游戏操作共享 `ServerControl.operation_lock`，手动插件写入也在同一锁下。下载、全量预检后才通过选定 backend 停服，持锁不递归调用 `ServerControl.run`。临时文件及备份完成 fsync 后写 `transaction.json`，再逐文件发布；收据在全部文件完成后原子发布。崩溃后 GET 只报告，恢复操作检查原始/目标哈希。恢复失败阻止 start/restart，避免运行半安装的框架。

状态区分 `not_installed`、`restart_required`、`active`、`unknown` 和 `incomplete`。安装收据只证明文件事务；实际加载必须查询运行实例及依赖。SourceMod 报告中的 `<Failed>` 插件不算已加载。最小包的 sipreset 在 Infected Bots 未安装时不改变原版游戏参数。

2026-09-27 用户确认的唯一运行时下载例外为 L4DToolZ 2.5.1：官方固定 HTTPS URL + SHA256 + 两个 Linux 文件的固定映射。下载失败或哈希/压缩包路径错误不会提交游戏文件。它不在 Release tar 内，不开放自定义 URL 输入。其余确认许可的包继续在构建阶段规范化并内置。

当前验证包括文件事务故障注入、取消、外部修改、链接/路径拒绝、同目录归属、共享锁、停服失败、恢复和真实 HTTP 鉴权。真实引擎组合与客户端人数验证另行记录，不能由这些测试替代。
