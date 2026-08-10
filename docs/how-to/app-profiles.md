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
