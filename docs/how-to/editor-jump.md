---
title: Jump to a symbol by voice
# No double quotes here: they are emitted unescaped into the meta description's
# content attribute, which truncates it at the first one (verified in site/).
description: Say go to line 240, or jump to function tokenize, and your editor moves there — resolved offline through the LSP symbols Neovim or VS Code already has.
---

# Jump to a symbol by voice

Say where you want to be and the cursor goes there: YazSes jumps to lines, symbols, and functions in your active editor. It resolves the spoken target through your editor's own LSP backend over the editor bridge, then moves the cursor — offline, like everything else.

## Setup

Your editor has to be reachable from YazSes.

- **Neovim** — start it with `nvim --listen /tmp/nvim.sock`, or rely on `$NVIM`, which Neovim sets automatically inside its own terminal.
- **VS Code** — install the YazSes extension so it writes the context file.

If neither is reachable, `yazses jump` says so and exits rather than moving a cursor somewhere else.

## Usage

You can use the CLI command to jump:

```bash
# Jump to line 42
yazses jump "go to line 42"

# Jump to a function or symbol
yazses jump "jump to function tokenize"
```

The spoken jump target is parsed, the symbol list is fetched from the editor's LSP backend, fuzzy-matched, and the cursor is moved automatically.
