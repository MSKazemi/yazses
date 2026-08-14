**Read this in other languages:** [English](README.md) · [Deutsch](README.de.md) · [Nederlands](README.nl.md) · [Tiếng Việt](README.vi.md) · [Türkçe](README.tr.md) · [bahasa Indonesia](README.id.md) · [español](README.es.md) · [français](README.fr.md) · [italiano](README.it.md) · [polski](README.pl.md) · [português do Brasil](README.pt-BR.md) · [svenska](README.sv.md) · [čeština](README.cs.md) · [ελληνικά](README.el.md) · [Русский](README.ru.md) · [українська](README.uk.md) · [עברית](README.he.md) · [اردو](README.ur.md) · [العربية](README.ar.md) · [فارسی](README.fa.md) · [हिंदी](README.hi.md) · [বাংলা](README.bn.md) · [தமிழ்](README.ta.md) · [తెలుగు](README.te.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · 한국어
<!-- yazses-l10n: locale=ko; source=README.md; source_sha=346ba97; scope=partial; status=draft -->

> ⚠️ **초안 번역** — 기계 보조로 작성되었으며 아직 원어민의 검토를 거치지 않았습니다.
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](README.md). Improving it is a
> welcome first contribution — see [issue #198](https://github.com/MSKazemi/yazses/issues/198).*

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

YazSes는 Linux, macOS, Windows용 무료 오픈소스 오프라인 음성 받아쓰기 데몬입니다. 키를 누른 채 말하고 놓으면, 입력 중이던 곳에 글자가 나타납니다. 모든 처리는 사용자의 컴퓨터에서 이루어지며 클라우드도, 계정도, 구독도 필요하지 않습니다.

## 설치

| 플랫폼 | 명령 |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **모든 운영체제** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

처음 실행할 때 음성 모델(약 148 MB)을 한 번 내려받습니다. 그 뒤로는 네트워크가 전혀 필요하지 않습니다.

## 할 수 있는 일

- **받아쓰기** — 키를 누른 채 말하고 놓으세요. 글자가 활성 창에 입력됩니다.
- **음성 명령** — “파일 저장”이나 “40번째 줄로 이동”이라고 말하면 그 말을 적는 대신 실행합니다.
- **회의와 녹음** — 오디오 파일을 받아쓰거나 회의 전체를 화자 표시와 함께 기록할 수 있습니다. 모두 오프라인입니다.

## 개인정보

음성은 사용자의 컴퓨터에서 처리되며 어디에도 전송되지 않습니다. 원격 측정도, 클라우드 경로도 없습니다.

## 더 보기

나머지 문서는 현재 영어로 되어 있습니다.

- [문서](https://mskazemi.com/yazses/)
- [영어 전체 README](README.md)
- [이슈와 질문](https://github.com/MSKazemi/yazses/issues)

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
