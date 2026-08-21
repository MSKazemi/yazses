---
title: "YazSes — Türkçe"
description: "YazSes; Linux, macOS ve Windows için özgür, açık kaynaklı ve çevrimdışı çalışan bir sesli yazdırma servisidir. Bir tuşu basılı tutun, konuşun, bırakın — metin yazmakta olduğunuz yerde belirir. Her şey kendi bilgisayarınızda çalışır: bulut yok, hesap yok, abonelik yok."
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · Türkçe · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · [português do Brasil](../pt-BR/index.md) · [svenska](../sv/index.md) · [čeština](../cs/index.md) · [ελληνικά](../el/index.md) · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · [বাংলা](../bn/index.md) · [தமிழ்](../ta/index.md) · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · [简体中文](../zh-CN/index.md) · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=tr; source=README.md; source_sha=3baacb8; scope=partial; status=draft -->

> ⚠️ **Taslak çeviri** — Makine destekli ve henüz ana dili konuşan biri tarafından gözden geçirilmedi.
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](https://github.com/MSKazemi/yazses#readme). Improving it is a
> welcome first contribution — see [issue #203](https://github.com/MSKazemi/yazses/issues/203).*

# YazSes

YazSes; Linux, macOS ve Windows için özgür, açık kaynaklı ve çevrimdışı çalışan bir sesli yazdırma servisidir. Bir tuşu basılı tutun, konuşun, bırakın — metin yazmakta olduğunuz yerde belirir. Her şey kendi bilgisayarınızda çalışır: bulut yok, hesap yok, abonelik yok.

## Kurulum

| Platform | Komut |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **Herhangi bir sistem** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

İlk çalıştırma bir kez konuşma modelini indirir (yaklaşık 148 MB). Sonrasında hiç ağ gerekmez.

## Ne yapar

- **Dikte** — Tuşu basılı tutun, konuşun, bırakın. Metin etkin pencereye yazılır.
- **Sesli komutlar** — “dosyayı kaydet” ya da “40. satıra git” deyin; sözcükleri yazmak yerine işlemi yapar.
- **Toplantılar ve kayıtlar** — Bir ses dosyasını yazıya dökün ya da tüm bir toplantıyı konuşmacı etiketleriyle kaydedin — tamamen çevrimdışı.

## Gizlilik

Ses kendi bilgisayarınızda yazıya dökülür ve hiçbir yere gönderilmez. Telemetri yoktur ve buluta giden bir yol yoktur.

## Dahası

Belgelerin geri kalanı şimdilik İngilizcedir.

- [Belgeler](https://mskazemi.com/yazses/)
- [Tam İngilizce README](https://github.com/MSKazemi/yazses#readme)
- [Sorunlar ve sorular](https://github.com/MSKazemi/yazses/issues)

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
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mercael91"><img src="https://avatars.githubusercontent.com/u/257655913?v=4?s=100" width="100px;" alt="mercael"/><br /><sub><b>mercael</b></sub></a><br /><a href="#infra-mercael91" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
