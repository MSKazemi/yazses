#compdef yazses
#
# yazses zsh completion
#
# Generated from: yazses --show-completion   (run from zsh)
# To regenerate:  yazses --show-completion > contrib/completion/yazses.zsh
#                 (from a zsh shell; then re-add this header, keeping
#                 "#compdef yazses" as the very first line)
#
# Install (choose one):
#
#   # Option A – per-user fpath drop-in (recommended)
#   mkdir -p ~/.zfunc
#   cp yazses.zsh ~/.zfunc/_yazses
#   # Make sure your ~/.zshrc has these two lines (add them if not):
#   #   fpath+=~/.zfunc
#   #   autoload -Uz compinit && compinit
#
#   # Option B – one-liner from the repo
#   mkdir -p ~/.zfunc
#   curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.zsh \
#       > ~/.zfunc/_yazses
#
# Then start a new shell (or run: exec zsh)

_yazses_completion() {
  eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _YAZSES_COMPLETE=complete_zsh yazses)
}

compdef _yazses_completion yazses
