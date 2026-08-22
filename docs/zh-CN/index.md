---
title: "YazSes — 简体中文"
description: "YazSes 是一个免费、开源、离线的语音听写与语音转文字守护进程，支持 Linux（X11 与 Wayland）、macOS 和 Windows，基于 faster-whisper 构建。当音频不能被上传到 Google、Apple、Microsoft 或 Otter 时使用它 —— 因为会议内容涉密、机器处于内网隔离状态，或者你只是不想再付订阅费。与 Wispr Flow 这类云端听写不同，YazSes 完全在本地设备上运行；与 Talon Voice 不同，它追求开箱即用，而非高级脚本定制。如果你需要的是对话式 AI 助手、开箱即用的非英语模型，或者移动端／网页版应用，那么"
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · [Türkçe](../tr/index.md) · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · [português do Brasil](../pt-BR/index.md) · [svenska](../sv/index.md) · [čeština](../cs/index.md) · [ελληνικά](../el/index.md) · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · [বাংলা](../bn/index.md) · [தமிழ்](../ta/index.md) · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · 简体中文 · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=zh-CN; source=README.md; source_sha=96711bc; scope=partial; status=active -->

> [README.md](https://github.com/MSKazemi/yazses#readme) 的简体中文翻译。若此处内容与英文版有出入，以**英文版为准**。
>
> **翻译进度：** 简介、「三大功能」、快速开始、《中文听写》、系统要求、主要特性、局限与常用命令已翻译；对比与替代方案、常见问题、配置、全部安装方式、开发等章节仍为英文。最后同步的英文源提交：`40d3abd`（2026-08-11）。

# YazSes

## ⬇️ 安装

| 平台 | 命令 |
|---|---|
| **Linux**（推荐） | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux**（Debian/Ubuntu，APT） | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **任意系统**（Python ≥ 3.11） | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

**[Platform support — OS + CPU →](https://mskazemi.com/yazses/platform-support.html)**

---



**你的声音永远不会离开你的电脑。** 离线语音听写：把语音直接输入到任何应用，转写录音文件，或者录下整场会议并生成带说话人姓名的纪要 —— 全部在你自己的 CPU 上完成。无需云端，无需 API key，无需订阅。

YazSes 是一个免费、开源、离线的语音听写与语音转文字守护进程，支持 **Linux（X11 与 Wayland）、macOS 和 Windows**，基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 构建。当音频不能被上传到 Google、Apple、Microsoft 或 Otter 时使用它 —— 因为会议内容涉密、机器处于内网隔离状态，或者你只是不想再付订阅费。与 Wispr Flow 这类云端听写不同，YazSes 完全在本地设备上运行；与 Talon Voice 不同，它追求开箱即用，而非高级脚本定制。如果你需要的是对话式 AI 助手、开箱即用的非英语模型，或者移动端／网页版应用，那么 YazSes **并不适合**你。

📖 **完整文档：[mskazemi.com/yazses](https://mskazemi.com/yazses/)** —— 安装指南、CLI 参考、配置、功能与故障排查。

![YazSes — 按住热键，说话，松开；文字被输入到当前焦点应用](../screenshots/yazses-reel.gif)

*40 秒演示：核心流程、命令行与系统托盘。终端输出是真实的；命令行输入为了清晰起见做了重新演示。*
▶️ **[在 YouTube 上观看](https://www.youtube.com/watch?v=nn8WUKsCvZ4)** —— 同一段演示，带章节。

![yazses doctor — 全部通过，完全离线](../screenshots/yazses-doctor.png)

---

## 三大功能

| | 你运行的命令 | 你得到的结果 |
|---|---|---|
| 🎙️ **听写** | 按住热键，说话，松开 | 文字被输入到当前焦点窗口 —— 编辑器、浏览器、终端、聊天窗口。另外还支持语音命令（*"undo that"*、*"go to line 42"*）与宏。 |
| 📄 **转写文件** | `yazses transcribe interview.m4a` | 任意音频／视频文件的文字稿，可选标注**谁说了什么**。输出格式：txt、md、srt、vtt 或 json。 |
| 👥 **记录会议** | `yazses meeting start` … `yazses meeting stop` | 全程免手动录制 → 生成**带说话人标注的文字稿**，并可选生成**会议纪要**（摘要、决议、待办事项），由本地 LLM 撰写。 |

三者都在你的 CPU 上运行，全程无需联网。除非你明确要求保留，会议录音在转写后会被删除；说话人姓名来自你自己录入的声纹 —— 绝不来自任何云端账号。

> **哪些是可选的：** 听写开箱即用。说话人标注需要 diarization 扩展（`pipx install 'yazses[diarization]'`，约 45 MB 模型，只需下载一次）；会议纪要还额外需要 `notes` 扩展以及你自行指定的本地 GGUF 模型。两者默认关闭 —— 详见[离线会议纪要](../meeting-notes-offline.md)。

---

## 中文听写

**结论先行：默认配置只支持英语。** YazSes 默认使用 `base.en` 模型，它是纯英语模型，在架构上**无法**解码中文 —— 它会把中文语音"音译"成看似流畅的英文乱码。要用中文听写，必须显式切换到多语言模型。

在 `~/.config/yazses/config.toml` 中：

```toml
[stt]
model = "small"            # 多语言模型（不带 .en 后缀）；base / small / medium / large-v3
language = "zh"            # 中文
chinese_script = "simplified"   # 输出简体字；台湾／香港用户请设为 "traditional"
```

然后运行 `yazses features enable chinese-script`（会自动安装所需的 `chinese` 扩展），再运行 `yazses restart`。

### 为什么必须设置 `chinese_script`

Whisper 会**逐句**自行决定输出简体还是繁体，而且并不一致。在 20 段干净的 16 kHz 普通话语音（ASCEND 测试集，`small` 模型）上实测，其中 **13 段**返回的是繁体字 —— 即使识别本身是正确的。对大陆用户来说，这意味着说着简体中文，编辑器里却蹦出繁体字。

这个问题造成的损失比表面看起来大得多，因为**识别通常是对的，只是字形写错了**。以简体参考文本计算字错率（CER）：

| 模型 | `chinese_script = ""` | `chinese_script = "simplified"` |
|---|---|---|
| `small` | 35.9% | **16.9%** |
| `large-v3` | 12.3% | **11.3%** |

同一批音频、同一个模型，只改了这一个配置项。**这个设置对小模型的作用最大，而小模型正是 CPU 用户实际会用的那一档** —— `small` 提升 19 个百分点，`large-v3` 只提升 1 个百分点（大模型本身就更倾向输出简体）。详见 [`src/yazses/postprocess/han_script.py`](https://github.com/MSKazemi/yazses/blob/main/src/yazses/postprocess/han_script.py) 与[中文语音输入文档](https://mskazemi.com/yazses/zh/chinese-voice-typing.html)。

### 请如实看待精度

上述数据来自 ASCEND —— 这是**自然对话**语料，说话人带港式口音，且有中英夹杂，属于偏难的场景，样本量也只有 20 句。安静环境下用好麦克风朗读准确率会更好；嘈杂环境或口音较重时则会更差。模型大小是最有效的调节手段（`large-v3` 11.3% vs `small` 16.9%）。**请先用 `yazses transcribe` 在你自己的录音上测一测，再决定是否投入使用。** 模型越大越准，但 CPU 解码也越慢。

中文听写目前应视为**可用但仍需打磨**，欢迎提交实测结果与改进：[opening an issue](https://github.com/MSKazemi/yazses/issues)。

---

## 快速开始

> **想先听听它准不准，再决定要不要装？**
> 用 Docker 或直接在浏览器里试用 —— 无需安装，不留痕迹：
> **[免安装试用](https://mskazemi.com/yazses/try-without-installing.html)**。
> 仓库里自带一段音频，加上 `--network none` 就能证明转写确实发生在你自己的机器上。

**第 1 步 —— 安装**

| 平台 | 命令 |
|---|---|
| **Linux**（推荐） | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux**（Debian/Ubuntu，APT） | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **任意系统**（Python ≥ 3.11） | `pipx install yazses` |

**推荐**的一行命令会：按需安装 `uv`，安装最新版 YazSes，配置所有系统依赖（音频、按键注入、剪贴板、`input` 用户组、Wayland 的 `ydotoold`），最后运行 **`yazses doctor`**，让缺失的工具在安装过程中就暴露出来。APT 与 `pipx` 安装的是最近一次发布的版本。YazSes 也已上架 [Snap Store](https://snapcraft.io/yazses)（`sudo snap install yazses`）。

> **不放心把网上的脚本直接管道给 shell？** 完全合理。加上 `--dry-run`，它会检查你的机器、打印出所有将要做的改动，然后退出且不做任何修改：
> `bash <(curl -fsSL .../install.sh) --dry-run`
>
> 决定之前请先看：**[安装到底要付出什么代价](https://mskazemi.com/yazses/install-cost.html)**（1.1 GB 加上 141 MB 模型，以及它对系统做的改动）和**[如何卸载](https://mskazemi.com/yazses/uninstall.html)** —— 这两页都是有意提前公开的。

**Shell 补全：** `yazses --install-completion`（或用 `yazses --show-completion` 打印脚本）。详见 [CLI 参考](../cli-reference.md)。

**第 2 步 —— 配置系统** *（Linux 专用，一条命令即可；APT 安装会自动完成）*

```sh
yazses setup        # 安装音频与注入依赖，加入 input 组，配置 ydotoold
# 然后注销并重新登录（input 组变更需要重新登录才生效）
```

`yazses setup` 结束时会打印一份编号的**收尾清单**，列出只有你能完成的步骤 —— 重新登录以应用 `input` 组、校准你的声音（`yazses mic-level --set`）、以及 `yazses start` —— 并会主动询问是否立刻帮你完成麦克风校准。

> **注销／重新登录是必须的，且只需一次。** 加入 `input` 组只在**新的登录会话**中生效 —— 仅仅新开一个终端标签页是**不够**的，因为它继承了旧会话的用户组，热键仍然无效。如果这一步尚未完成，`yazses start` 会给出提示。若不想注销就立刻开始听写，可以为单个会话临时切换组：`sg input -c "yazses restart"`。真正重新登录之后，直接运行 `yazses start` 即可。

`yazses setup` 会补齐听写所需的一切，且可以安全地重复运行 —— 它只做缺失的部分：
- **`libportaudio2`** —— 音频采集（缺失时守护进程启动会崩溃并报 `OSError: PortAudio library not found`）。
- **注入后端** —— `xdotool`/`xclip`（X11）以及 `wtype`/`ydotool`/`wl-clipboard`（Wayland）。
- **`input` 用户组** —— 从内核读取按住说话热键所必需。
- **`ydotoold`** —— 虚拟输入守护进程。在 **GNOME/KDE Wayland** 上这是注入按键的*唯一*途径（`wtype` 在那里被禁用），因此 `setup` 会安装并启用它。

> 想手动完成？`sudo apt install libportaudio2 xdotool ydotool wtype xclip wl-clipboard pipx && sudo usermod -aG input "$USER"`，然后启用 `ydotoold`（见 [install-linux](../install-linux.md)）。随时可用 `yazses doctor` 验证 —— 你需要看到 `[OK] Keyboard capture`、`[OK] Microphone` 和 `[OK] Injection`。macOS/Windows 可跳过此步（按提示授予辅助功能／相关权限，见下文）。

**第 3 步 —— 初始化**

```sh
yazses quickstart           # 不确定下一步做什么？根据你的机器量身定制的 3 步指南
yazses doctor               # 检查麦克风、注入后端、权限（希望全部 [OK]）
yazses enroll               # 校准麦克风（约 30 秒）
yazses autostart enable     # 开机自启，重启后依然可用
yazses start                # 启动听写守护进程
yazses verify               # 说一句话，验证整条流水线确实可用
```

> 刚接触 YazSes？随时运行 **`yazses quickstart`** —— 它会检查已完成的配置，并告诉你接下来该做什么。它不会修改任何东西。

**第 4 步 —— 开始使用** —— 按住热键，说话，松开。文字会被输入到当前焦点应用。

---

## 系统要求

| | |
|---|---|
| **操作系统** | Linux（主要平台）· macOS 11+ · Windows 10 (21H2)+ |
| **内存** | 最低 4 GB · 8 GB 更宽裕 |
| **磁盘** | faster-whisper 模型约需 250 MB–1 GB（首次运行时下载） |
| **CPU** | 2 核以上 · 无需 GPU |
| **麦克风** | 任意 USB 或内置麦克风 |

---

## 主要特性

- **完全离线** —— 默认情况下音频与文字都不会离开本机；无需云服务、API 密钥或订阅
- **按住说话** —— 在 Linux、macOS、Windows 上直接输入到当前焦点应用
- **会议模式** —— 全程免手动录制，生成带发言人标注的文字记录，并可选用本地大模型生成会议纪要（摘要、决议、待办）；除非你选择保留，音频在转写后即被删除
- **离线文件转写** —— `yazses transcribe <file>` 可将任意音视频转成 txt/md/srt/vtt/json，并可选标注「谁说了什么」
- **语音命令** —— 通过正则语法（以及可选的小模型路由）执行编辑器/终端操作（撤销、保存、跳转行、运行测试、重命名等）
- **宏与个人词库** —— 自定义多步命令，并教会 YazSes 那些它总听错的词
- **不流畅友好模式** —— 可选地合并口吃与重复（`b-b-because` → `because`），面向口吃或构音障碍的使用者
- **自我改进** —— 可选、加密、留在本机的学习语料库；`yazses tune` 会根据你自己的修正提出准确率改进建议（不会有任何数据离开本机）
- **编辑器上下文** —— 可选的 Neovim / VS Code LSP 上下文，提升代码标识符的识别准确率
- **无障碍支持** —— VAD 校准向导、麦克风电平调节，以及面向运动障碍使用者的 EMG（肌电传感器）触发
- **语音活动浮层** —— 说话时在光标附近显示声呐式圆环（可选）

---

## 局限 / 什么情况下**不该**用 YazSes

- **它不是 LLM 智能体。** YazSes 负责听写文字、转写录音、执行编辑器与终端命令。它**不会**浏览网页、理解你的文件、设置提醒或与你对话。
- **发言人标注与会议纪要是附加功能，而非默认功能。** `--diarize` 与会议纪要各自需要额外安装可选组件（纪要还需要你自备本地 GGUF 模型）。普通听写与普通转写都不需要。
- **它是 CPU 上的 faster-whisper，不是云服务。** 若你在嘈杂麦克风下追求绝对最低的词错误率，云端 STT 可能仍然更准；代价是数据要离开你的机器。
- **默认针对英语调优。** 默认附带 `*.en` 系列 Whisper 模型；其他语言需要换用对应模型。中文用户请参见上文《中文听写》一节。
- **目前仅支持桌面端。** 尚无可安装的移动端或网页版。**Android 应用正在设计中** —— 架构与十份决策记录已公开在 [docs/mobile](../mobile/index.md)，由贡献者公开协作开发。iOS/iPadOS 将在 Android 之后；macOS 已由本桌面应用支持。

---

## 常用命令

| 命令 | 作用 |
|---|---|
| `yazses start` | 启动守护进程（若已在运行则干净地重启） |
| `yazses status` | 查看状态、热键、模型，以及本机的解码延迟（p50/p95） |
| `yazses stop` | 停止守护进程 |
| `yazses doctor` | 检查系统前置条件，并指出缺什么、怎么修 |
| `yazses mic-level --set` | 测量麦克风电平并写入合适的静音阈值 |
| `yazses transcribe <file>` | 离线转写音视频文件；加 `--diarize` 可标注发言人 |
| `yazses features` | 查看所有能力并开启/关闭 —— 无需手改配置文件 |
| `yazses settings` | 同一个开关面板的窗口版本 |
| `yazses vocab add <词>` | 把 YazSes 总听错的词加入个人词库 |

命令名、配置键与文件路径**一律保持英文原样** —— 翻译过的命令是不存在的命令。

## 参与贡献

> 🙌 **想帮忙？** **[从这里开始](https://mskazemi.com/yazses/contribute/start.html)** —— 只有一页，找到与你条件匹配的那一行，15–45 分钟即可完成。无需申请许可，也没有任何任务被指派；欢迎使用编程 AI 助手，页面里有可直接复制的提示词。有几项任务**完全不需要 Python** —— [把 README 翻译成你的语言](https://github.com/MSKazemi/yazses/issues/18)、[把你的麦克风](https://github.com/MSKazemi/yazses/issues/21)加入已验证列表，或者只是跑一跑然后告诉我们结果。[#22](https://github.com/MSKazemi/yazses/issues/22) 列出了所有待办事项。测试套件完全离线，约 30 秒跑完，所以你不需要麦克风、模型或 GPU 就能参与贡献。

**中文相关的改进尤其欢迎** —— 无论是这份翻译的措辞、中文识别的实测数据，还是词汇表与标点处理。

---

> 以下章节仍为英文，请见 [README.md](https://github.com/MSKazemi/yazses#readme)：全部安装方式、功能列表、配置、语音命令、隐私说明与架构。

---

## 贡献者

感谢这些为 YazSes 出过力的朋友 ✨ —— 每一份 bug 报告、文档修正和补丁都算数。贡献类型遵循 [all-contributors 表情说明](https://allcontributors.org/reference/emoji-key/)（💻 代码 · 📖 文档 · 🌍 翻译 · ⚠️ 测试 · 🛡️ 安全 · 🚧 维护）：

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi"><img src="https://avatars.githubusercontent.com/u/13011878?v=4?s=100" width="100px;" alt="Mohsen Seyedkazemi Ardebili"/><br /><sub><b>Mohsen Seyedkazemi Ardebili</b></sub></a><br /><a href="#maintenance-MSKazemi" title="Maintenance">🚧</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/lntutor"><img src="https://avatars.githubusercontent.com/u/1948922?v=4?s=100" width="100px;" alt="lntutor"/><br /><sub><b>lntutor</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=lntutor" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/HeaTTap"><img src="https://avatars.githubusercontent.com/u/83951176?v=4?s=100" width="100px;" alt="HeaTTap"/><br /><sub><b>HeaTTap</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=HeaTTap" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jackie-cqz"><img src="https://avatars.githubusercontent.com/u/88996311?v=4?s=100" width="100px;" alt="jackie-cqz"/><br /><sub><b>jackie-cqz</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=jackie-cqz" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Parinitha-26"><img src="https://avatars.githubusercontent.com/u/199358281?v=4?s=100" width="100px;" alt="Parinitha-26"/><br /><sub><b>Parinitha-26</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Parinitha-26" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AshSgDe29071999"><img src="https://avatars.githubusercontent.com/u/192003854?v=4?s=100" width="100px;" alt="AshSgDe29071999"/><br /><sub><b>AshSgDe29071999</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Maqbool61"><img src="https://avatars.githubusercontent.com/u/68494045?v=4?s=100" width="100px;" alt="Maqbool Ahmed"/><br /><sub><b>Maqbool Ahmed</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Maqbool61" title="Code">💻</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn"><img src="https://avatars.githubusercontent.com/u/145488564?v=4?s=100" width="100px;" alt="Renji"/><br /><sub><b>Renji</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Tests">⚠️</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Documentation">📖</a> <a href="#security-waterlemonnn" title="Security">🛡️</a> <a href="#infra-waterlemonnn" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/slegarraga"><img src="https://avatars.githubusercontent.com/u/64795732?v=4?s=100" width="100px;" alt="Sebastian Legarraga"/><br /><sub><b>Sebastian Legarraga</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=slegarraga" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/YossiMH"><img src="https://avatars.githubusercontent.com/u/21257793?v=4?s=100" width="100px;" alt="YossiMH"/><br /><sub><b>YossiMH</b></sub></a><br /><a href="#ideas-YossiMH" title="Ideas, Planning, & Feedback">🤔</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3AYossiMH" title="Bug reports">🐛</a> <a href="#research-YossiMH" title="Research">🔬</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Prithvi4904"><img src="https://avatars.githubusercontent.com/u/216231806?v=4?s=100" width="100px;" alt="Prithvi4904"/><br /><sub><b>Prithvi4904</b></sub></a><br /><a href="#translation-Prithvi4904" title="Translation">🌍</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/4nmus"><img src="https://avatars.githubusercontent.com/u/145120721?v=4?s=100" width="100px;" alt="4nmus"/><br /><sub><b>4nmus</b></sub></a><br /><a href="#translation-4nmus" title="Translation">🌍</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Mr-Neutr0n"><img src="https://avatars.githubusercontent.com/u/64578610?v=4?s=100" width="100px;" alt="hari"/><br /><sub><b>hari</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Mr-Neutr0n" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mercael91"><img src="https://avatars.githubusercontent.com/u/257655913?v=4?s=100" width="100px;" alt="mercael"/><br /><sub><b>mercael</b></sub></a><br /><a href="#infra-mercael91" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="https://github.com/MSKazemi/yazses/commits?author=mercael91" title="Documentation">📖</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/happytester-funbugs"><img src="https://avatars.githubusercontent.com/u/184687761?v=4?s=100" width="100px;" alt="Tanya Martin-McClellan"/><br /><sub><b>Tanya Martin-McClellan</b></sub></a><br /><a href="#userTesting-happytester-funbugs" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Ahappytester-funbugs" title="Bug reports">🐛</a> <a href="#platform-happytester-funbugs" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AtmanActive"><img src="https://avatars.githubusercontent.com/u/7526717?v=4?s=100" width="100px;" alt="AtmanActive"/><br /><sub><b>AtmanActive</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/issues?q=author%3AAtmanActive" title="Bug reports">🐛</a> <a href="#userTesting-AtmanActive" title="User Testing">📓</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

想上这面墙？认领一个 [good first issue](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) —— 第一个被合并的 PR 就能为你留一个位置。

---

## 引用

> Seyedkazemi Ardebili, M. (2026). *YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System.* arXiv:2607.28878. <https://arxiv.org/abs/2607.28878>

详见 [CITATION.cff](https://github.com/MSKazemi/yazses/blob/main/CITATION.cff)（CFF 1.2.0 机器可读元数据）。

## 许可证

Apache 2.0 —— 见 [LICENSE](https://github.com/MSKazemi/yazses/blob/main/LICENSE)。

如果 YazSes 对你有用，在 GitHub 上点一个 ⭐，并在你的项目、博客或分享中提一句，就是对它持续开发最好的支持。
