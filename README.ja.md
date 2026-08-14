**Read this in other languages:** [English](README.md) · [Deutsch](README.de.md) · [Nederlands](README.nl.md) · [Tiếng Việt](README.vi.md) · [Türkçe](README.tr.md) · [bahasa Indonesia](README.id.md) · [español](README.es.md) · [français](README.fr.md) · [italiano](README.it.md) · [polski](README.pl.md) · [português do Brasil](README.pt-BR.md) · [svenska](README.sv.md) · [čeština](README.cs.md) · [ελληνικά](README.el.md) · [Русский](README.ru.md) · [українська](README.uk.md) · [עברית](README.he.md) · [اردو](README.ur.md) · [العربية](README.ar.md) · [فارسی](README.fa.md) · [हिंदी](README.hi.md) · [বাংলা](README.bn.md) · [தமிழ்](README.ta.md) · [తెలుగు](README.te.md) · [ไทย](README.th.md) · 日本語 · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [한국어](README.ko.md)
<!-- yazses-l10n: locale=ja; source=README.md; source_sha=346ba97; scope=partial; status=draft -->

> ⚠️ **下書き翻訳** — 機械支援による翻訳で、母語話者のレビューはまだ受けていません。
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](README.md). Improving it is a
> welcome first contribution — see [issue #177](https://github.com/MSKazemi/yazses/issues/177).*

# YazSes

[![Tests](https://github.com/MSKazemi/yazses/actions/workflows/test.yml/badge.svg)](https://github.com/MSKazemi/yazses/actions/workflows/test.yml)
[![Snap Status](https://snapcraft.io/yazses/badge.svg)](https://snapcraft.io/yazses)
[![PyPI](https://img.shields.io/pypi/v/yazses)](https://pypi.org/project/yazses/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/yazses?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/yazses)
[![PyPI Downloads](https://img.shields.io/pypi/dm/yazses)](https://pypi.org/project/yazses/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21856271.svg)](https://doi.org/10.5281/zenodo.21856271)
[![Documentation](https://img.shields.io/badge/docs-mskazemi.com%2Fyazses-5e35b1)](https://mskazemi.com/yazses/)
[![Open Source Helpers](https://www.codetriage.com/mskazemi/yazses/badges/users.svg)](https://www.codetriage.com/mskazemi/yazses)
[![All Contributors](https://img.shields.io/badge/all_contributors-12-orange.svg?style=flat-square)](#contributors)
[![Get it from the Snap Store](https://snapcraft.io/en/light/install.svg)](https://snapcraft.io/yazses)

YazSes は Linux・macOS・Windows 向けの、無料でオープンソースのオフライン音声入力デーモンです。キーを押しながら話し、離すと、入力中の場所にそのまま文字が現れます。すべて自分のマシンで動作し、クラウドもアカウントも定額課金もありません。

## インストール

| プラットフォーム | コマンド |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **任意の OS** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

初回のみ音声モデル（約 148 MB）をダウンロードします。その後はネットワークをまったく必要としません。

## できること

- **音声入力** — キーを押しながら話し、離します。文字はアクティブなウィンドウに入力されます。
- **音声コマンド** — 「ファイルを保存」「40 行目へ移動」と言えば、その言葉を入力する代わりに実行します。
- **会議と録音** — 音声ファイルを文字起こししたり、会議全体を話者ラベル付きで記録したりできます。すべてオフラインです。

## プライバシー

音声はあなたのマシン上で文字起こしされ、どこにも送信されません。テレメトリもクラウド経路もありません。

## さらに詳しく

残りのドキュメントは現時点では英語です。

- [ドキュメント](https://mskazemi.com/yazses/)
- [英語版の完全な README](README.md)
- [課題と質問](https://github.com/MSKazemi/yazses/issues)

---

## Contributors

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
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
