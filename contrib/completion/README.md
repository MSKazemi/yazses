# Shell Completion for yazses

`yazses` supports **Tab completion** for bash, zsh, and fish via
[Typer](https://typer.tiangolo.com/tutorial/commands/)'s built-in Click completion.

## Option 1 — built-in install (one command)

```bash
yazses --install-completion   # detects your shell automatically
```

Or to inspect the generated script first without writing anything:

```bash
yazses --show-completion
```

## Option 2 — static scripts (no yazses needed at install time)

Pre-generated scripts live in this directory. Pick your shell:

### Bash

```bash
mkdir -p ~/.local/share/bash-completion/completions
curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.bash \
    > ~/.local/share/bash-completion/completions/yazses
# start a new shell, or:
source ~/.bashrc
```

System-wide (requires sudo):

```bash
sudo curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.bash \
    > /etc/bash_completion.d/yazses
```

### Zsh

```bash
mkdir -p ~/.zfunc
curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.zsh \
    > ~/.zfunc/_yazses
```

Add the following to `~/.zshrc` if not already there:

```zsh
fpath+=~/.zfunc
autoload -Uz compinit && compinit
```

Then start a new shell (`exec zsh`).

### Fish

```bash
mkdir -p ~/.config/fish/completions
curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.fish \
    > ~/.config/fish/completions/yazses.fish
```

Fish picks these up automatically — no further steps needed.

## Regenerating

`yazses --show-completion` emits the script for the shell it is *run from*
(it takes no shell argument). If new subcommands are added, regenerate each
script from its own shell and re-add the header comment:

```bash
# from bash:
yazses --show-completion > contrib/completion/yazses.bash
# from zsh:
yazses --show-completion > contrib/completion/yazses.zsh
# from fish:
yazses --show-completion > contrib/completion/yazses.fish
```
