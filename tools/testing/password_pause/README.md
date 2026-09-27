# 密码插件真实暂停探针

对应 `beginner-deployment-plan` B5 / 7.3a。SourceMod 1.12 不提供 `sm plugins pause`，本探针通过正式 C++ SDK 的 `IPlugin::SetPauseState` 暂停及恢复实际发布的 `panel_join_password.smx`，不替换它的代码。

SourcePawn 命令在同一次服务器调用中依次暂停、读取保护值、恢复、核对密码。C++ 返回真实 `Plugin_Paused` / `Plugin_Running` 状态；输出仅包含布尔结果。原生保护值及恢复后的自定义密码都与调用前密码比较，密码本身不输出。

## 固定 SDK

与实测 SourceMod `1.12.0.7253` 的 `version_auto.inc` 相符。后两个提交来自该 SourceMod Git 树的子模块引用。

| 仓库 | commit | codeload tar.gz SHA256 |
|---|---|---|
| alliedmodders/sourcemod | `2e229b111534b1be007dc3bd9acfcf2fc472e893` | `9f4cbcc6fa52f185418fe3ba5037b00b0c45e6d41cac69d12fec256715b60130` |
| alliedmodders/sourcepawn | `11b22edb634b9764d19fd28699e03289cfd18520` | `2c0fadfcf7ce36b4313357ca61cb065094cf1a250993e0333d7fca42098d7f93` |
| alliedmodders/amtl | `2d3b1a3378a3728637f26660c9ffc2df3189cf62` | `c952f201a010eb285d3c5d4c195d24292f7e07ca6574c57ea30db01469a6b5dc` |

下载地址格式为 `https://codeload.github.com/<仓库>/tar.gz/<commit>`，核对哈希后分别解压并去除顶层目录到 `$SDK_ROOT/sourcemod`、`$SDK_ROOT/sourcepawn`、`$SDK_ROOT/amtl`。官方接口见 [IPluginSys.h](https://github.com/alliedmodders/sourcemod/blob/2e229b111534b1be007dc3bd9acfcf2fc472e893/public/IPluginSys.h)。

## 编译及实跑

在 Linux 使用 `g++-multilib`，从本目录执行；`SDK_ROOT` 指向上述隔离 SDK 目录：

```bash
g++ -m32 -std=c++17 -shared -fPIC -fno-rtti -fno-exceptions -O2 \
  extension.cpp "$SDK_ROOT/sourcemod/public/smsdk_ext.cpp" \
  -I. -I"$SDK_ROOT/sourcemod/public" -I"$SDK_ROOT/sourcepawn/include" \
  -I"$SDK_ROOT/amtl" -I"$SDK_ROOT/amtl/amtl" \
  -o panel_password_pause_test.ext.so
```

使用固定 SourceMod 包的 `spcomp64` 和配套 `include` 编译 `panel_password_pause_test.sp`。将两个产物分别放入专用隔离测试服的 `addons/sourcemod/extensions/` 和 `addons/sourcemod/plugins/`；先确认文件名尚不存在、测试服无人在线且已设置临时进服密码。

从测试服 RCON 顺序执行：

```text
sm exts load panel_password_pause_test.ext.so
sm plugins load panel_password_pause_test
sm_panel_password_pause_test
```

预期：`PANEL_PAUSE_TEST paused=1 protected=1 running=1 native_clear=1 secret_preserved=1`。之后核对 `sm_panel_password_status` 的 ready/required 状态、UDP 查询、配置 revision 和正式密码插件 SHA256。

清理时先 `sm plugins unload panel_password_pause_test`，从 `sm exts list` 取得本测试扩展编号，再 `sm exts unload <编号>`。移出这两个临时产物并确认列表中已无测试辅助程序。若探针失败导致密码插件仍暂停，先重载正式密码插件并确认校验恢复，再清理辅助程序。

这些文件属于测试工具，不进入发布包。该探针证明实际暂停/恢复及原生保护值，不代替真实客户端的密码认证测试。
