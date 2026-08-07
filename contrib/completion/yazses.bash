# yazses bash completion
#
# Generated from: yazses --show-completion bash
# To regenerate: yazses --show-completion bash > contrib/completion/yazses.bash
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
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD _YAZSES_COMPLETE=bash_complete $1)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
        fi
    done

    return 0
}

_yazses_completion_setup() {
    complete -o nosort -F _yazses_completion yazses
}

_yazses_completion_setup;
