# Jump to Symbol

YazSes supports jumping to lines, symbols, and functions in your active editor. This uses the editor bridge protocol to resolve the spoken target through your editor's LSP backend and moves the cursor appropriately.

## Setup

Ensure your editor is connected to YazSes.
For Neovim, YazSes uses the `$NVIM` socket (automatically set in terminal).
For VS Code, ensure the YazSes extension is installed and writing context.

## Usage

You can use the CLI command to jump:

```bash
# Jump to line 42
yazses jump "go to line 42"

# Jump to a function or symbol
yazses jump "jump to function tokenize"
```

The spoken jump target is parsed, the symbol list is fetched from the editor's LSP backend, fuzzy-matched, and the cursor is moved automatically.
