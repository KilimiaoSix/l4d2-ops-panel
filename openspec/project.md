# L4D2 Ops Panel 工程上下文

本轮实施起始代码基线为 `b73ef2a`，后端 FastAPI + Python，前端 Vue 3 + TypeScript。现有分层、接口契约和测试约定以 `docs/development.md` 为准；引擎实测限制见 `docs/l4d2-server-notes.md`。

- `api` 负责 HTTP、输入模型和鉴权；`services` 负责业务流程与审计；`integrations` 负责文件、协议和外部进程；`store` 负责 SQLite。
- 写操作在服务层审计，秘密不进入审计、任务日志或普通查询响应。前端不使用 `v-html`。
- 游戏安装与开关服已有共用操作锁；新增流程必须纳入相同资源的互斥规则。
- `tests/parity` 启动真实后端子进程，通过 HTTP 和协议夹具验证契约；`tests/unit` 可做进程内服务注入。二者不可混淆。
- Linux/POSIX 文件权限、进程、systemd 和真实引擎行为不能仅凭 Windows 测试或假游戏证明。
- 当前依赖声明：FastAPI 0.141.1、uvicorn 0.53.0；前端 lockfile 中 Vue 3.5.43、Vite 8.3.0、TypeScript 6.0.3、vue-tsc 3.3.11。Vite 的 Node 要求是 `^20.19.0 || >=22.12.0`，不能只写“Node 20+”。
- 2026-09-27 用户已授权按新手化计划实施；已完成项及证据见活动 change 的 tasks 和交付状态。未勾选项仍须继续验收。2026-09-28 用户另行授权提前正式发布及生产部署，由 beginner-deployment-plan 7.7 记录；真人未测项目不因发布而勾选。发布资源按用户最新指示由 GitHub 托管，不使用游戏服务器提供下载。

本地已有 README 和 Steam 自定义主页解析的未提交工作；后续实施应保留、核对并显式衔接，不覆盖或混入无关回退。
