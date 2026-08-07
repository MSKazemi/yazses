#compdef yazses
#
# yazses zsh completion
#
# Generated from: yazses --show-completion zsh
# To regenerate: yazses --show-completion zsh > contrib/completion/yazses.zsh
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
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[yazses] )) && return 1

    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) _YAZSES_COMPLETE=zsh_complete yazses)}")

    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                completions_with_descriptions+=("$key":"$descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            _path_files -/
        elif [[ "$type" == "file" ]]; then
            _path_files -f
        fi
    done

    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi

    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}

if [[ $zsh_eval_context[-1] == loadautofunc ]]; then
    # autoload from fpath, call function directly
    _yazses_completion "$@"
else
    # eval/source/. command, register function for later
    compdef _yazses_completion yazses
fi
