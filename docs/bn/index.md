---
title: "YazSes — বাংলা"
description: "YazSes হলো Linux, macOS ও Windows-এর জন্য একটি বিনামূল্যের, মুক্ত উৎসের ও অফলাইন ভয়েস-ডিকটেশন ডিমন। একটি কী চেপে ধরুন, বলুন, ছেড়ে দিন — আপনি যেখানে লিখছেন সেখানেই লেখাটি এসে যাবে। সবকিছু আপনার নিজের কম্পিউটারে চলে: কোনো ক্লাউড নয়, কোনো অ্যাকাউন্ট নয়, কোনো সাবস্ক্রিপশন নয়।"
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · [Türkçe](../tr/index.md) · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · [português do Brasil](../pt-BR/index.md) · [svenska](../sv/index.md) · [čeština](../cs/index.md) · [ελληνικά](../el/index.md) · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · বাংলা · [தமிழ்](../ta/index.md) · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · [简体中文](../zh-CN/index.md) · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=bn; source=README.md; source_sha=3baacb8; scope=partial; status=draft -->

> ⚠️ **খসড়া অনুবাদ** — যন্ত্রসহায়তায় তৈরি, এখনও কোনো মাতৃভাষীর দ্বারা পর্যালোচিত নয়।
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](https://github.com/MSKazemi/yazses#readme). Improving it is a
> welcome first contribution — see [issue #191](https://github.com/MSKazemi/yazses/issues/191).*

# YazSes

YazSes হলো Linux, macOS ও Windows-এর জন্য একটি বিনামূল্যের, মুক্ত উৎসের ও অফলাইন ভয়েস-ডিকটেশন ডিমন। একটি কী চেপে ধরুন, বলুন, ছেড়ে দিন — আপনি যেখানে লিখছেন সেখানেই লেখাটি এসে যাবে। সবকিছু আপনার নিজের কম্পিউটারে চলে: কোনো ক্লাউড নয়, কোনো অ্যাকাউন্ট নয়, কোনো সাবস্ক্রিপশন নয়।

## ইনস্টল

| প্ল্যাটফর্ম | কমান্ড |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **যেকোনো সিস্টেম** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

প্রথমবার চালালে একবারই একটি স্পিচ মডেল নামানো হয় (প্রায় ১৪৮ MB)। তারপর আর কোনো নেটওয়ার্কের দরকার হয় না।

## এটি যা করে

- **ডিকটেশন** — কী চেপে ধরুন, বলুন, ছেড়ে দিন। লেখাটি সক্রিয় উইন্ডোতে টাইপ হয়ে যায়।
- **ভয়েস কমান্ড** — “ফাইল সেভ করো” বা “৪০ নম্বর লাইনে যাও” বললে সে কথাগুলো না লিখে কাজটাই করে।
- **মিটিং ও রেকর্ডিং** — একটি অডিও ফাইল প্রতিলিপি করুন, বা পুরো মিটিং রেকর্ড করুন কে কী বলল তার চিহ্নসহ — সবই অফলাইনে।

## গোপনীয়তা

অডিও আপনার কম্পিউটারেই লেখায় রূপান্তরিত হয় এবং কোথাও পাঠানো হয় না। কোনো টেলিমেট্রি নেই, ক্লাউডে যাওয়ার কোনো পথও নেই।

## আরও

বাকি নথিপত্র আপাতত ইংরেজিতে।

- [নথিপত্র](https://mskazemi.com/yazses/)
- [সম্পূর্ণ ইংরেজি README](https://github.com/MSKazemi/yazses#readme)
- [সমস্যা ও প্রশ্ন](https://github.com/MSKazemi/yazses/issues)

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
