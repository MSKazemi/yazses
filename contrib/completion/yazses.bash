# yazses bash completion
#
# Generated from: yazses --show-completion   (run from bash)
# To regenerate:  yazses --show-completion > contrib/completion/yazses.bash
#                 (from a bash shell; then re-add this header)
#
# Install (choose one):
#
#   # Option A – per-user (no sudo needed)
#   mkdir -p ~/.local/share/bash-completion/completions
#   cp yazses.bash ~/.local/share/bash-completion/completions/yazses
#
#   # Option B – system-wide
#   sudo cp yazses.bash /etc/bash_completion.d/yazses
#
#   # Option C – one-liner from the repo
#   mkdir -p ~/.local/share/bash-completion/completions
#   curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/completion/yazses.bash \
#       > ~/.local/share/bash-completion/completions/yazses
#
# Then start a new shell (or run: source ~/.bashrc)

_yazses_completion() {
    local IFS=$'
'
    COMPREPLY=( $( env COMP_WORDS="${COMP_WORDS[*]}" \
                   COMP_CWORD=$COMP_CWORD \
                   _YAZSES_COMPLETE=complete_bash $1 ) )
    return 0
}

complete -o default -F _yazses_completion yazses
