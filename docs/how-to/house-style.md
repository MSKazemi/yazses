---
title: Apply a house style to your dictation
description: Keep terminology and spellings consistent by voice, from a rules file.
---

# Apply a house style to your dictation

If you write to a house style — "e-mail" not "email", US spelling, "cannot" not
"can not" — the **Style-Consistency Enforcer** (`styleguard`) rewrites each
dictation to match, so you don't have to remember the rule mid-sentence. A
local Vale-lite pass, entirely offline. **Off by default.**

## 1. Enable the feature

```bash
yazses features enable styleguard
```

## 2. Write your style rules

Create `style-rules.toml` next to `config.toml`
(`~/.config/yazses/style-rules.toml`). Each rule maps a **preferred** term to
the **variants** it replaces:

```toml
# ~/.config/yazses/style-rules.toml
[[rule]]
preferred = "e-mail"
variants = ["email", "e mail"]

[[rule]]
preferred = "cannot"
variants = ["can not"]

[[rule]]
preferred = "U.S."
variants = ["US"]
ignore_case = false        # only the uppercase "US" is rewritten, not "us"
```

- Matching is whole-word and case-insensitive by default (`ignore_case = true`);
  set `ignore_case = false` for terms where case carries meaning.
- Set `regex = true` on a rule to match `preferred` as a pattern instead of a
  literal word (e.g. year-like tokens, ticket-number formats).
- A rule missing `preferred` or with an empty `variants` list is skipped and
  logged — a broken style sheet never breaks the daemon.

## 3. Point the config at the file (optional) and restart

`[styleguard] path` defaults to `style-rules.toml` (relative to the config
dir), so the file above is found automatically. To use a different location:

```toml
# config.toml
[styleguard]
enabled = true                  # written by `yazses features enable styleguard`
path = "style-rules.toml"       # relative to config dir, or an absolute path
```

```bash
yazses restart                  # apply
```

Say "send an email" and it lands as "send an e-mail".

## See also

- [Configuration reference — `[styleguard]`](../configuration.md)
- [Feature reference](../features.md)
- [Create spoken macros and snippets](macros-and-snippets.md) — another
  config-driven, off-by-default text transform on the dictation path.
