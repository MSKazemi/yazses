---
title: Set a tone per application
description: Dictate casually in Slack, formally in email, and verbatim in a terminal — YazSes picks the tone from the app you are speaking into, fully offline.
---

# Set a tone per application

App profiles let you configure the tone of your dictated text depending on which application you are speaking into — casual in a chat window, formal in an email client, verbatim in a terminal. Like everything else in YazSes, it runs entirely offline.

## Examples

You configure it in your `config.toml` file under the `[profiles.app]` section. You can match the window class using standard wildcard (`*`) patterns.

### 1. Casual Chat
When speaking into Discord or Slack, you might want the LLM to rewrite your text in a more casual, friendly tone.

```toml
[profiles.app]
"*discord*" = "casual"
"*slack*" = "casual"
```

### 2. Formal Emails
For an email client like Thunderbird or Outlook, or a professional word processor, you can enforce a formal tone.

```toml
[profiles.app]
"*thunderbird*" = "formal"
"*outlook*" = "formal"
"*winword*" = "formal"
```

### 3. Verbatim Mode for Terminals
For IDEs and terminals where you want dictation inserted exactly as heard with no formatting, you can use the `verbatim` mode. This bypasses all text formatting passes.

```toml
[profiles.app]
"*term*" = "verbatim"
"*code*" = "verbatim"
"*alacritty*" = "verbatim"
```

### 4. Custom Prompts
You can also supply your own custom LLM prompt directly in the configuration.

```toml
[profiles.app]
"*obsidian*" = "Format as a bulleted markdown list with short actionable items."
```

## How It Works
When you stop holding the dictation key, YazSes resolves the window you are focused on and checks for a match.
If `[filters.disfluency] llm_enabled = true` is set, YazSes will then run the rewrite pass using the specific tone you have configured. If `verbatim` is chosen, the engine skips any processing entirely. Unknown apps get the standard cleaning pass if enabled.

---

## When the application rewrites what you dictated

A profile changes what YazSes *sends*. It cannot change what the application does
with it after it arrives — and some applications rewrite it.

The clearest case, measured by injecting into a live window and reading the
document back:

| | |
|---|---|
| dictated | `kubectl get pods --namespace prod` |
| arrived in LibreOffice Writer | `Kubectl get pods –namespace prod` |

Two of Writer's own defaults did that. **AutoCapitalise** made `kubectl` into
`Kubectl`, a different command. **AutoCorrect** replaced the double hyphen with an
**en dash**, so `--namespace` became `–namespace` — which no program accepts, and
which is nearly invisible when you read it back.

No YazSes setting prevents this, because it happens inside the application. Turn
the features off there:

```
Tools → AutoCorrect Options → Options       [ ] Capitalize first letter of every sentence
Tools → AutoCorrect Options → Localized     [ ] Replace dashes
```

**How to tell whether your app does this:** dictate `--namespace` and look closely
at the dash, then dictate a lowercase command name at the start of a line. Word
processors and chat clients are the usual offenders; terminals and code editors
were verified not to touch the text at all
([kitty, Alacritty, Konsole, tmux, Neovim, Emacs](https://github.com/MSKazemi/yazses/tree/main/examples)).

