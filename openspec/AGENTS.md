# 本目录约定

1. `changes/beginner-deployment-plan/` 保存新手化改造的提案、设计、需求和开发清单。用户已于 2026-09-27 授权按计划实现并在现有服务器调试；安装测试优先本机 Docker，不便时允许服务器隔离 Docker。
2. 先读 `project.md`、活动 change 的全部工件和 `docs/development.md`；接口变化先确定 parity 契约。
3. 按 `tasks.md` 的依赖顺序实施。每项完成必须同时有代码与对应验证；不因计划校验通过而勾选开发任务。
4. 需求变化先更新 spec/design，再改代码；不将最小安装偷偷改成默认全套，也不取消已确认的配置重启能力。
5. 用 `openspec validate beginner-deployment-plan --strict` 校验计划结构。真实系统验收仍须按设计中的验证矩阵执行。
6. 在完整实现和验收前不要归档该 change；规划完成与产品完成分别记录。
