# yazses fish completion
#
# Generated from: yazses --show-completion   (run from fish)
# To regenerate:  yazses --show-completion > contrib/completion/yazses.fish
#                 (from a fish shell; then re-add this header)
#
# Install (choose one):
#
#   # Option A – per-user (recommended; no sudo needed)
#   mkdir -p ~/.config/fish/completions
#   cp yazses.fish ~/.config/fish/completions/yazses.fish
#
#   # Option B – one-liner from the repo
#   mkdir -p ~/.config/fish/completions
#   curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.fish \
#       > ~/.config/fish/completions/yazses.fish
#
# Fish picks up completions in that directory automatically — no further steps needed.

complete --command yazses --no-files --arguments "(env _YAZSES_COMPLETE=complete_fish _TYPER_COMPLETE_FISH_ACTION=get-args _TYPER_COMPLETE_ARGS=(commandline -cp) yazses)" --condition "env _YAZSES_COMPLETE=complete_fish _TYPER_COMPLETE_FISH_ACTION=is-args _TYPER_COMPLETE_ARGS=(commandline -cp) yazses"
