---
title: Create spoken macros and snippets
description: Say a trigger phrase to expand canned boilerplate or a stored template.
---

# Create spoken macros and snippets

If you type the same boilerplate over and over — a signature, a standard reply, a
code stub — you can bind it to a spoken **trigger phrase**. Say the trigger and
YazSes types the expansion. Two features do this; both are **off by default**.

- **Say-Macro (`macros`)** — the fuller mechanism: triggers live in a dedicated
  `macros.toml`, support `text` and `snippet` expansions, and can place the caret
  with a `${cursor}` marker and substitute `${clipboard}`, `${date}`, `${time}`,
  and `${author}`.
- **Voice Snippets (`snippets`)** — a lightweight inline expander: trigger →
  template pairs configured directly in `config.toml` under `[snippets]`.

Both match on **whole-utterance exact match**, so a trigger appearing inside
ordinary prose never fires mid-dictation.

## Say-Macro

### 1. Enable the feature

```bash
yazses features enable macros
```

### 2. Write your macros

Create `macros.toml` next to `config.toml` (`~/.config/yazses/macros.toml`). Each
macro is a `[[macro]]` table:

```toml
# ~/.config/yazses/macros.toml
[[macro]]
trigger = "insert my signature"
type = "text"
text = "Best regards,\nMohsen"

[[macro]]
trigger = "new python function"
type = "snippet"
snippet = "def ${cursor}():\n    pass"

[[macro]]
trigger = "today's date"
type = "text"
text = "${date}"
```

- `type = "text"` or `type = "snippet"` — both type their body; `snippet` is meant
  for code and supports the `${cursor}` marker, which leaves the caret where you
  put it after typing.
- Placeholders `${clipboard}`, `${date}`, `${time}`, `${author}` are substituted at
  expansion time. `${author}` comes from `[macros] author`.

### 3. Point the config at the file (optional) and restart

`[macros] path` defaults to `macros.toml` (relative to the config dir), so the
file above is found automatically. To use a different location or set the author:

```toml
# config.toml
[macros]
enabled = true            # written by `yazses features enable macros`
path = "macros.toml"      # relative to config dir, or an absolute path
author = "Mohsen"         # value substituted for ${author}
```

```bash
yazses restart            # apply
```

A broken macro entry is skipped and logged — it never breaks the daemon.

## Voice Snippets

For simple text expansions without a separate file, use `[snippets]` in
`config.toml`:

```bash
yazses features enable snippets
```

```toml
# config.toml
[snippets]
enabled = true
[snippets.entries]
"insert my signature" = "Best regards,\nMohsen"
"my address" = "1 Example Street, Bologna"
```

```bash
yazses restart
```

Say `insert my signature` and YazSes types the stored template.

## See also

- [Configuration reference — `[macros]` and `[snippets]`](../configuration.md)
- [Feature reference](../features.md)
- [Change the hold-to-talk key](change-hotkey.md) — a dedicated command key pairs
  well with spoken triggers.
