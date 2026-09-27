# 发布签名与工具链（实施中）

版本化安装脚本由 `tools/release/render_bootstrap.py` 从 `get.sh.in` 生成，内嵌受信任公钥和固定版本。源码模板不能直接当作安装脚本执行。工具链版本记录在 `tools/release/toolchain.json`。按用户 2026-09-27 的决定，发布资源由本仓库 GitHub Releases 托管，不使用游戏服务器提供下载。`mirror: null` 是默认且可用的配置；正式公钥和 GitHub 环境 secret 已配置，正式签名工作流及公开下载仍待实测，不能宣布公开发布完成。

每个版本的 Release 上传五个独立资产：`get.sh`、`l4d2-panel-linux-x86_64.tar.gz`、`VERSION`、`SHA256SUMS`、`SHA256SUMS.sig`。脚本使用本仓库的 `/releases/download/v<版本>/` 路径取得同一版本的资产；GitHub 自动生成的 Source code 压缩包不含构建产物，不能作为安装包。GitHub 支持将构建好的软件附加为 [Release 资产](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

公开发布时，在 Release 正文和 README 中记录该版本的 `get.sh` HTTPS 下载地址及 SHA256。用户先下载并核对脚本哈希，再以 `sudo bash get.sh` 安装；脚本随后验证签名、资产哈希及版本。GitHub 访问失败时可重试、显式传入受认可的 `--mirror https://...`，或在可访问 GitHub 的电脑下载上述五个文件，原样复制至服务器后使用 `sudo bash get.sh --offline-dir <完整发布目录>`。默认不承诺国内独立镜像，也不关闭 TLS 或签名验证。可选镜像必须保持 `v<版本>/<资产名>` 的目录结构。

`sign.py` 使用独立 RSA-3072 私钥对精确包含 tar、get.sh、VERSION 三项的 SHA256SUMS 签名；`verify.py` 使用系统 OpenSSL 先验签再校验文件哈希与版本，最后检查整个归档再解包。签名必须恰为 384 字节，避免 OpenSSL 忽略尾部追加字节。清单、签名、tar、脚本、版本及不安全路径的故障测试在 `test_release_verification.py`。测试用密钥仅在临时目录生成，不能成为生产信任根。

正式公钥为 `tools/release/release-public.pem`，2026-09-27 生成的独立 RSA-3072 公钥 SPKI DER SHA256 指纹为 `0e29c5f28d26e1e71b12d7b4d8c49e4d4374efc3d079b4fe16943b3169ea353d`。本地 challenge 签名/验签成功；它与此前 VM 验收的临时测试密钥不同。私钥通过 GitHub CLI 在本机加密后保存为仓库 `KilimiaoSix/l4d2-ops-panel` 的 `release` 环境 secret `RELEASE_SIGNING_PRIVATE_KEY`，环境部署策略只允许 `main` 分支。普通分支 CI 使用临时测试密钥。

私钥主副本保存在本机 WSL `Ubuntu-22.04` 的 `/var/lib/l4d2-release-signing/release-private.pem`（root，目录 0700、文件 0600），不能随测试 VM 或开发目录清理。GitHub secret 不能取回原文，维护者备份应使用其受控的加密存储。公钥与环境配置证据见 [签名准备记录](10-reports/2026-09-27/release-signing-provisioning.json)；该记录不含私钥。CLI workflow 授权和普通 CI 已通过；代码进入主分支后可运行正式签名工作流，不再要求配置独立镜像。候选工件验证通过后才创建对应 GitHub Release，并回读下载验证；Actions 临时工件不能当作长期公开安装入口。

公钥轮换需维护者通过原有受信任入口分发新指纹和过渡脚本；镜像不能自行更换信任根。安装者对第一份 get.sh 的信任来自文档 HTTPS 入口及独立公布的脚本哈希，内嵌公钥不证明脚本自身可信。

工具链核对：[Node 22.22.0 官方发布](https://nodejs.org/en/blog/release/v22.22.0)、[Python 3.12.13](https://www.python.org/downloads/release/python-31213/)、[Python 3.10.20](https://www.python.org/downloads/release/python-31020/)。签名机制参见 [OpenSSL dgst](https://docs.openssl.org/3.0/man1/openssl-dgst/)，CI secret 保管参见 [GitHub 官方说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)。

Docker 安装使用 [官方签名 apt 仓库](https://docs.docker.com/engine/install/ubuntu/)；2026-09-27 核对官方公钥 SHA256 为 `1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570`，指纹为 `9DC858229FC7DD38854AE2D88D81803C0EBFCD88`。容器映射端口与主机防火墙需要分别诊断，不能以 UFW allow 或 TCP 检测成功宣称公网 UDP 已连通。

官方 Docker 软件源下载失败时回退到[清华 Docker CE 镜像](https://mirrors.tuna.tsinghua.edu.cn/help/docker-ce/)。两个来源取得的公钥必须匹配上述固定哈希，APT 仍检查 Docker 的 Release 签名和包哈希；公钥变更立即停止，不通过关闭校验解决网络问题。这是 Docker 软件包源，独立于面板发布镜像和游戏容器镜像。

高级路径 `panel/install.sh` 由原游戏服务用户执行：已有 `panel.json` 验证后保持原文；首次配置时回车取默认值，可选项输入 `-` 清空，密码使用隐藏输入。旧服务单元保持原样，新建服务含 `RestartPreventExitStatus=78`。证书使用实际 IP/DNS SAN，已有证书不替换；输出证书指纹供核对。
