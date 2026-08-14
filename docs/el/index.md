---
title: "YazSes — ελληνικά"
description: "Το YazSes είναι ένας ελεύθερος, ανοιχτού κώδικα και εκτός σύνδεσης δαίμονας φωνητικής υπαγόρευσης για Linux, macOS και Windows. Κρατήστε ένα πλήκτρο, μιλήστε, αφήστε το — το κείμενο εμφανίζεται εκεί που γράφετε. Όλα εκτελούνται στον δικό σας υπολογιστή: χωρίς νέφος, χωρίς λογαριασμό, χωρίς συνδρομή."
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · [Türkçe](../tr/index.md) · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · [português do Brasil](../pt-BR/index.md) · [svenska](../sv/index.md) · [čeština](../cs/index.md) · ελληνικά · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · [বাংলা](../bn/index.md) · [தமிழ்](../ta/index.md) · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · [简体中文](../zh-CN/index.md) · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=el; source=README.md; source_sha=3baacb8; scope=partial; status=draft -->

> ⚠️ **Προσωρινή μετάφραση** — Με μηχανική υποβοήθηση και χωρίς έλεγχο από φυσικό ομιλητή.
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](https://github.com/MSKazemi/yazses#readme). Improving it is a
> welcome first contribution — see [issue #195](https://github.com/MSKazemi/yazses/issues/195).*

# YazSes

Το YazSes είναι ένας ελεύθερος, ανοιχτού κώδικα και εκτός σύνδεσης δαίμονας φωνητικής υπαγόρευσης για Linux, macOS και Windows. Κρατήστε ένα πλήκτρο, μιλήστε, αφήστε το — το κείμενο εμφανίζεται εκεί που γράφετε. Όλα εκτελούνται στον δικό σας υπολογιστή: χωρίς νέφος, χωρίς λογαριασμό, χωρίς συνδρομή.

## Εγκατάσταση

| Πλατφόρμα | Εντολή |
|---|---|
| **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` |
| **Linux** (Debian/Ubuntu, APT) | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |
| **Οποιοδήποτε σύστημα** (Python ≥ 3.11) | `pipx install yazses` |

```bash
yazses quickstart
yazses start
```

Η πρώτη εκτέλεση κατεβάζει μία φορά ένα μοντέλο ομιλίας (περίπου 148 MB). Μετά δεν χρειάζεται καθόλου δίκτυο.

## Τι κάνει

- **Υπαγόρευση** — Κρατήστε το πλήκτρο, μιλήστε, αφήστε το. Το κείμενο γράφεται στο ενεργό παράθυρο.
- **Φωνητικές εντολές** — Πείτε «αποθήκευση αρχείου» ή «μετάβαση στη γραμμή 40» και εκτελείται, αντί να γραφτούν οι λέξεις.
- **Συσκέψεις και ηχογραφήσεις** — Απομαγνητοφωνήστε ένα αρχείο ήχου ή καταγράψτε μια ολόκληρη σύσκεψη με σήμανση ομιλητών — όλα εκτός σύνδεσης.

## Ιδιωτικότητα

Ο ήχος απομαγνητοφωνείται στον υπολογιστή σας και δεν αποστέλλεται ποτέ πουθενά. Δεν υπάρχει τηλεμετρία ούτε διαδρομή προς το νέφος.

## Περισσότερα

Η υπόλοιπη τεκμηρίωση είναι προς το παρόν στα αγγλικά.

- [Τεκμηρίωση](https://mskazemi.com/yazses/)
- [Το πλήρες αγγλικό README](https://github.com/MSKazemi/yazses#readme)
- [Ζητήματα και ερωτήσεις](https://github.com/MSKazemi/yazses/issues)

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
