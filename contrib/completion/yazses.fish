# yazses fish completion
#
# Generated from: yazses --show-completion fish
# To regenerate: yazses --show-completion fish > contrib/completion/yazses.fish
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

function _yazses_completion;
    set -l response (env _YAZSES_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) yazses);

    for completion in $response;
        set -l metadata (string split "," $completion);

        if test $metadata[1] = "dir";
            __fish_complete_directories $metadata[2];
        else if test $metadata[1] = "file";
            __fish_complete_path $metadata[2];
        else if test $metadata[1] = "plain";
            echo $metadata[2];
        end;
    end;
end;

complete --no-files --command yazses --arguments "(_yazses_completion)";
