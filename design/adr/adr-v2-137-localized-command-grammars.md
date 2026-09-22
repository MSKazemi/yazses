# ADR-v2-137 — Localize command grammars, not command semantics

**Status:** Proposed (2026-09-20)  
**Context:** Chinese voice commands; `commands/grammar.py`; `CommandIntent`; application profiles.

## Context

YazSes command recognition is currently English-specific. Tier 1 contains English regexes and English number-word normalization, while dispatch consumes language-neutral semantic actions such as:

- `undo`
- `save`
- `copy`
- `go_to_line`
- `select_all`

Chinese dictation without Chinese command recognition would type phrases such as “撤销” or “保存文件” instead of performing the corresponding action.

A naive implementation could duplicate the whole command/dispatch subsystem for Chinese. That would create separate behavior, safety fixes and editor mappings per language.

There is also an existing `CommandsConfig.profile`, but it represents application/editor behavior. Reusing it for spoken language would conflate two dimensions.

## Decision

Keep **semantic command IDs and dispatch language-neutral**. Add language-specific Tier-1 grammars that map spoken phrases into the existing `CommandIntent` model.

Add a dedicated command-language setting:

```toml
[commands]
language = "auto"
```

Semantics:

- `auto` follows the configured STT speech language when a grammar exists;
- `en` forces English spoken commands;
- `zh` forces Chinese spoken commands.

`CommandsConfig.profile` retains its current application/editor meaning.

The classifier tier order remains:

```text
user macro -> localized deterministic grammar -> optional local SLM -> dictate
```

P1 Chinese support does not require a Chinese SLM.

### Grammar organization

`grammar.classify()` remains the stable public API.

Internally, move/encapsulate English rules behind a grammar registry and add Chinese rules. The exact file layout may vary, but dispatch and action names must not be copied.

### Locale-specific normalization

Chinese command parsing may normalize:

- terminal Chinese punctuation;
- ASR spacing around digits/Latin text;
- common Chinese numerals needed by commands;
- explicitly reviewed Simplified/Traditional phrase variants.

Normalization applies only to the command candidate. It must not rewrite ordinary dictation.

## Consequences

### Positive

- English and Chinese commands execute identical semantic actions.
- Safety fixes in dispatch apply once.
- More spoken languages can be added without duplicating action logic.
- Users can dictate in Chinese while deliberately keeping English commands, or vice versa.
- Application profile and spoken language remain orthogonal.

### Costs

- The current monolithic English rule table must be refactored carefully.
- Phrase sets need native-speaker review.
- Chinese numeral parsing adds locale-specific logic.
- Contract vectors need a language dimension.

## Alternatives considered

### Translate text to English before the current grammar

Rejected. It adds an ML/translation dependency to a deterministic <5 ms path, creates privacy/latency complexity, and makes exact command safety harder to reason about.

### Put Chinese alternatives into every existing English regex

Rejected. Mixed-language regexes become unreadable, untestable and difficult for contributors to own.

### Duplicate grammar + dispatch for Chinese

Rejected. Semantic behavior would drift and every platform/safety fix would need duplication.

### Reuse `CommandsConfig.profile`

Rejected. “VS Code” and “Chinese” are different axes. Overloading the field would make combinations impossible.

## Acceptance constraints

- Existing English contract vectors remain valid.
- Chinese equivalent phrases emit the same action IDs/arguments.
- Unknown Chinese utterances remain dictation, never fuzzy commands.
- No Chinese rule invokes shell actions more broadly than its English semantic equivalent.
- Traditional/Simplified aliases are explicitly tested.
- Command parser changes do not globally normalize injected prose.
