---
title: "YazSes — português do Brasil"
description: "O YazSes é um daemon de ditado por voz livre, de código aberto e offline, para Linux, macOS e Windows. Segure uma tecla, fale e solte: o texto aparece onde você estiver digitando. Tudo roda na sua própria máquina: sem nuvem, sem conta e sem assinatura."
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · [Türkçe](../tr/index.md) · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · português do Brasil · [svenska](../sv/index.md) · [čeština](../cs/index.md) · [ελληνικά](../el/index.md) · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · [বাংলা](../bn/index.md) · [தமிழ்](../ta/index.md) · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · [简体中文](../zh-CN/index.md) · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=pt-BR; source=README.md; source_sha=3baacb8; scope=partial; status=draft -->

> ⚠️ **Tradução preliminar** — Assistida por máquina e ainda não revisada por um falante nativo.
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](https://github.com/MSKazemi/yazses#readme). Improving it is a
> welcome first contribution — see [issue #174](https://github.com/MSKazemi/yazses/issues/174).*

# YazSes

O YazSes é um daemon de ditado por voz livre, de código aberto e offline, para Linux, macOS e Windows. Segure uma tecla, fale e solte: o texto aparece onde você estiver digitando. Tudo roda na sua própria máquina: sem nuvem, sem conta e sem assinatura.

## Instalação

| Plataforma | Comando |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **Qualquer sistema** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

A primeira execução baixa um modelo de fala uma única vez (cerca de 148 MB). Depois disso, não precisa de rede alguma.

## O que ele faz

- **Ditado** — Segure a tecla, fale e solte. O texto é digitado na janela em foco.
- **Comandos de voz** — Diga “salvar arquivo” ou “ir para a linha 40” e ele age, em vez de digitar as palavras.
- **Reuniões e gravações** — Transcreva um arquivo de áudio ou capture uma reunião inteira com identificação de quem falou — tudo offline.

## Privacidade

O áudio é transcrito na sua máquina e nunca é enviado a lugar nenhum. Não há telemetria nem caminho para a nuvem.

## Mais

O restante da documentação está em inglês por enquanto.

- [Documentação](https://mskazemi.com/yazses/)
- [README completo em inglês](https://github.com/MSKazemi/yazses#readme)
- [Problemas e dúvidas](https://github.com/MSKazemi/yazses/issues)

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
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Mr-Neutr0n"><img src="https://avatars.githubusercontent.com/u/64578610?v=4?s=100" width="100px;" alt="hari"/><br /><sub><b>hari</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Mr-Neutr0n" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mercael91"><img src="https://avatars.githubusercontent.com/u/257655913?v=4?s=100" width="100px;" alt="mercael"/><br /><sub><b>mercael</b></sub></a><br /><a href="#infra-mercael91" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="https://github.com/MSKazemi/yazses/commits?author=mercael91" title="Documentation">📖</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/happytester-funbugs"><img src="https://avatars.githubusercontent.com/u/184687761?v=4?s=100" width="100px;" alt="Tanya Martin-McClellan"/><br /><sub><b>Tanya Martin-McClellan</b></sub></a><br /><a href="#userTesting-happytester-funbugs" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Ahappytester-funbugs" title="Bug reports">🐛</a> <a href="#platform-happytester-funbugs" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AtmanActive"><img src="https://avatars.githubusercontent.com/u/7526717?v=4?s=100" width="100px;" alt="AtmanActive"/><br /><sub><b>AtmanActive</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/issues?q=author%3AAtmanActive" title="Bug reports">🐛</a> <a href="#userTesting-AtmanActive" title="User Testing">📓</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/hoti-code"><img src="https://avatars.githubusercontent.com/u/320443384?v=4?s=100" width="100px;" alt="hoti-code"/><br /><sub><b>hoti-code</b></sub></a><br /><a href="#userTesting-hoti-code" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Ahoti-code" title="Bug reports">🐛</a> <a href="#platform-hoti-code" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jayavandhiniMK"><img src="https://avatars.githubusercontent.com/u/221181058?v=4?s=100" width="100px;" alt="Jayavandhini M K"/><br /><sub><b>Jayavandhini M K</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=jayavandhiniMK" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/visheshbpatel"><img src="https://avatars.githubusercontent.com/u/206997413?v=4?s=100" width="100px;" alt="Vishesh Patel"/><br /><sub><b>Vishesh Patel</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=visheshbpatel" title="Documentation">📖</a> <a href="#userTesting-visheshbpatel" title="User Testing">📓</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
