---
title: "电脑离线中文语音输入 —— 如何用 YazSes 配置"
description: "YazSes 是一个英文调优的听写工具，默认模型完全无法解码普通话。本页说明如何把它指向多语言 Whisper 模型、简繁混乱这个比看上去更花钱的坑，以及我们实际测到的数字。不对中文效果作任何承诺 —— 这是一篇配置指南，不是支持声明。"
alternates:
  en: use-cases/chinese-voice-typing.md
---

# 在电脑上用中文语音输入，全程离线

> 本页是[英文版本](../use-cases/chinese-voice-typing.md)的简体中文翻译。
> 若有出入，以英文版为准。

!!! warning "结论先行：YazSes 是一个英文听写工具"

    YazSes 默认使用 `base.en`，为英文调优。**我们不宣称它支持中文。**
    本项目公开的每一项准确率基准都是英文的（[LibriSpeech](../benchmarks.md)）。
    下面讲的多语言解码是 **Whisper 的**能力，不是 YazSes 的 —— YazSes 只是把 `language`
    参数透传过去，模型要你自己提供。如果你要的是一个主打中文的工具，请用专门做中文的。

**这一页是什么：**给已经在用 YazSes 写英文、又想顺便试试普通话的人的一份配置指南；
外加一个我们确实修掉的中文专属问题（简繁混乱），以及修它时测到的数字。

它会明确说清楚**哪些能用、哪些还不行** —— 因为离线语音识别的中文支持，通常被吹得过头了。

## 默认并不支持中文，你必须手动换模型

YazSes 默认使用 `base.en`，这是一个**纯英语**的 Whisper 模型。纯英语模型完全不包含语言标记，
因此在架构上无法解码普通话：喂给它中文语音，它不会报错，而是输出看似流畅的英文乱码 ——
这是最糟糕的一种失败方式。YazSes 启动时会就此发出警告，但设置仍然需要你自己改。

编辑 `~/.config/yazses/config.toml`：

```toml
[stt]
model = "small"                  # 多语言模型（不带 .en 后缀）：base / small / medium / large-v3
language = "zh"                  # 普通话
chinese_script = "simplified"    # 简体；台湾／香港用户请设为 "traditional"
```

然后执行：

```sh
yazses features enable chinese-script   # 自动安装所需的 `chinese` 扩展
yazses restart
```

## 为什么 `chinese_script` 比它听起来更重要

Whisper 会**逐句**自行决定输出简体还是繁体，而且并不一致。在 20 段干净的 16 kHz 普通话语音
上实测（ASCEND 测试集，`small` 模型），其中 **13 段返回的是繁体字** —— 包括那些识别本身
完全正确的句子。对大陆用户来说，这意味着说着简体中文，编辑器里却蹦出繁体字。

这种不一致造成的精度损失远超表面观感，因为**识别通常是对的，只是字形写错了**。
以简体参考文本计算字错率（CER）：

| 模型 | `chinese_script = ""` | `chinese_script = "simplified"` |
|---|---|---|
| `small` | 35.9% | **16.9%** |
| `large-v3` | 12.3% | **11.3%** |

同一批音频、同一个模型，只改了一个配置项。**这个设置对小模型的作用最大，
而小模型正是 CPU 用户实际会用的那一档** —— `small` 提升了 19 个百分点，`large-v3`
只提升了 1 个百分点，因为大模型本身就更倾向于输出简体。如果你是在笔记本 CPU 上（而不是 GPU 上）
听写，那么这个设置承担了绝大部分的改善。

测量方法与全部注意事项记录在
[`postprocess/han_script.py`](https://github.com/MSKazemi/yazses/blob/main/src/yazses/postprocess/han_script.py)。

需要说明的是：简繁转换是一个可逆的字符映射，因此它**无法修复听错的内容** ——
它只能防止一段本来正确的识别结果以错误的字形呈现出来。

## 实际准确率到底如何

上述数据来自 ASCEND —— 这是**自然对话**语料，说话人带港式口音，且有中英夹杂，
是刻意选择的偏难场景，样本量也只有 20 句。安静环境下用较好的麦克风朗读效果会更好；
嘈杂环境或口音较重时则会更差。模型大小是你手上最有效的调节手段：在同一批音频上，
`large-v3` 达到 11.3%，而 `small` 为 16.9%。

不要把任何人的基准数据当成对你嗓音的承诺。投入使用前，请先在你自己的录音上实测：

```sh
yazses transcribe 我的录音.m4a
```

模型越大越准，但 CPU 解码也越慢。`small` 是一个合理的起点；如果你的机器能承受更高的延迟，
可以换成 `medium` 或 `large-v3`。

YazSes 的中文听写目前应当被描述为**可用但仍需打磨**。我们非常希望收到真实使用反馈 ——
欢迎[提交 issue](https://github.com/MSKazemi/yazses/issues)，说明哪些好用、哪些不好用。

## 为什么"离线"在这里特别重要

市面上大多数中文语音输入要么是网页，要么是手机输入法：你对着它们的文本框说话，
再把结果复制出来，而且一断网就不能用了。YazSes 是运行在你自己电脑上的后台程序，
因此它直接把文字输入到 Word、浏览器、代码编辑器或终端里 —— 在火车上、在信号很差的地方，
甚至在一台从不联网的机器上都能用。

对于音频绝对不能外传的场景，这一点就是全部意义所在：病历记录、法律文书、未发表的研究、
受伦理审查约束的访谈录音，或者内网隔离机器上的工作。
参见[隐私与机密工作场景](../use-cases/private-offline-dictation.md)与[隐私声明](../privacy-statement.md)。

## 相关页面

- [多语言听写](../use-cases/multilingual-dictation.md) —— 非英语的通用配置方法
- [印地语与印度语言](../use-cases/hindi-voice-typing.md) —— 另一种书写系统的同类做法
- [离线转写录音文件](../use-cases/transcribe-audio-offline.md)
- [English version](../use-cases/chinese-voice-typing.md)
