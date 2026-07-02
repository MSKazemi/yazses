# v2 Voice-First Interaction Layer (preview)

YazSes v2 grows from a dictation daemon into a broader **voice-first interaction
layer** — still 100% on-device and privacy-first. **Every v2 feature is opt-in and
off by default**, so your day-to-day dictation is unchanged until you turn one on.
v1.4.x remains the stable release; the features below are a developer preview
(`v2.0.0-dev`).

Manage all of them with the switchboard:

```bash
yazses features                 # list every capability + on/off + how to toggle
yazses features enable <name>   # turn one on (writes your config)
yazses restart                  # apply
```

Experimental features refuse `enable` unless you add `--force`.

## Dictation upgrades (Wave A)

| Feature | Toggle | What it does |
|---|---|---|
| **Confidence Ink** | `confidence` | Flags words the recognizer was unsure about (from Whisper's own probabilities) so you can re-pick them by voice instead of re-dictating. Local only. |
| **Prosody pause→sentence** | `[prosody] pause_sentence_ms` | Inserts a period when you pause for a sentence-length gap. |
| **Spoken Edit Mode** | `spoken-edit` | Edit the last dictation by voice — "change *their* to *there*", "delete the last sentence". Command-key gated. |
| **Context-Primed Dictation** | `context` | Primes the recognizer with terms from the active window/selection so domain words are transcribed right. Read transiently, **never stored**. |

## New capabilities (Wave B)

| Feature | Toggle | What it does |
|---|---|---|
| **Personal Adapter** | `personalize` | Biases the recognizer toward *your* jargon and names, mined from your local corpus. Nothing leaves the machine. |
| **Spoken Recall & Scratch** | `recall` | Search your past dictations (`yazses recall <query>`) and capture spoken notes-to-self (`yazses scratch`). Corpus-local. |
| **True Code-Switch** | `polyglot` | Routes mixed-language speech to a code-switch model (you supply the adapter). |
| **Voice-to-Tool (Spoken MCP)** | `agent` | Run allowlisted tools by voice via MCP; state-changing tools ask first. Needs the `agent` extra + a local planner model. |
| **Voice Pilot (AT-SPI)** | `pilot` | Drive the desktop by voice via the accessibility tree — "click Save", "focus the terminal". Reads labels only, **no screenshots**. |

## Experimental (Wave C — `--force` to enable)

| Feature | Toggle | What it does |
|---|---|---|
| **Accessibility Continuum** | `continuum` | Whisper/Low-Effort Mode lowers the mic gate so quiet or effortful speech is still captured (no shouting). |
| **Modality Role Router** | `modality` | Assigns each input its fastest role (gaze→point, EMG→command, voice→dictation). Needs EMG/gaze hardware. |
| **Gaze-Routed Dictation** | `[gaze] route_dictation` | Sends the next dictation to the window you look at, with a focus fallback and a confirm for destructive actions. Needs a webcam + calibration. |
| **Glasses↔Desktop Bridge** | `bridge` | Dictate from a paired phone/glasses; the desktop does STT + typing. Local link only. |

## Wave D (v2.1) — new frontier features (all off by default)

A fresh 2026 state-of-the-art round. Manage them with `yazses features enable/disable`.

| Feature | Toggle | What it does |
|---|---|---|
| **Speech Translation** | `translate` | Dictate in another language, type English — uses Whisper's built-in translate (X→English, no extra download); other targets via the `seamless` backend. |
| **Tone-Aware Formatting** | `affect` | Adds `!`/`?` from your vocal tone (beyond pause punctuation). Conservative by default; needs the `affect` extra for tone detection. |
| **Predictive Completion** | `predict` | A tiny on-device model suggests the rest of your sentence; accept by voice. Needs the `predict` extra + a model. |
| **Noise Suppression** | `denoise` | Cleans background noise/echo before transcription so dictation works in noisy rooms. Needs the `denoise` extra (DeepFilterNet). |
| **Meeting Scribe** | `scribe` | On-device "who said what" transcript — you are tagged **You**, others **Speaker N**. Needs the `scribe` extra (diarization). |
| **Ask My Notes (voice RAG)** | `rag` | Ask a question by voice, get an answer grounded in and citing your own local notes/docs. Needs the `rag` extra. |
| **Codec Streaming** | `codec` | Routes decoding to a low-latency streaming neural-codec engine (Kyutai/Mimi). Needs the `codec` extra; English/French-centric. |
| **Voice Guard** (experimental) | `voiceguard` | Types only when the *live* speaker matches your enrolled voiceprint and the audio isn't a recording/synthetic. `--force`; needs the `voiceguard` extra. |

Two more Wave D directions are designed but await hardware: **silent-speech (sEMG)**
dictation by mouthing words, and **pure-vision screen commanding** for surfaces with no
accessibility tree. See `design/adr/adr-v2-023/024` (internal).

## Wave E (v2.1) — more frontier features (all off by default)

| Feature | Toggle | What it does |
|---|---|---|
| **Hallucination Guard** | `hallucination` | Drops Whisper's fabricated ghost text on silence/noise (the phantom "Thank you.") before it's typed. |
| **Voice Snippets** | `snippets` | Say a trigger ("insert my signature") to type a stored template. |
| **Phonetic Corrector** | `phonetic` | Fixes mis-heard proper nouns by sound ("Cuber Netties" → "Kubernetes"). |
| **Multi-User Profiles** | `voiceprint` `multi_profile` | Loads each enrolled speaker's own vocab/hotkey/cleanup from their voiceprint. |
| **Hands-Free Auto-Stop** | `autostop` | Tap once and speak; recording auto-stops when you finish. |
| **Voice Mouse Grid** | `mousegrid` | Drive the cursor and click by voice via a numbered grid, on any pixels. |
| **Spoken Code Mode** | `code` | Dictate code: spoken symbols → punctuation, word-groups → cased identifiers. |
| **Spoken Math (LaTeX)** | `math` | Dictate equations → LaTeX ("x squared plus y squared" → `x^{2} + y^{2}`). |
| **Wake-Word Activation** (exp) | `wakeword` | Start dictation hands-free on a keyword. Always-listening, local-only, `--force`. |
| **Vocal-Strain Guard** | `voicehealth` | Advises a break when your voice shows rising strain over a session (advisory only). |

The **zero-touch bundle** — Wake-Word + Auto-Stop + Voice Mouse Grid — composes into a
complete hands-free operating mode.

## Wave F — self-improvement, adaptation & new modalities (v2.2)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.
Toggle with `yazses features enable <name>`.

| Feature | `features` name | What it does |
|---|---|---|
| **Speaking Coach** | `coach` | Private analytics of your dictation: filler rate, words-per-minute, vocabulary diversity. |
| **Smart-Paste** | `smartpaste` | Adapts injected syntax to the target app (markdown bullets, code casing, URL autolinking). |
| **Audio-Anchored Scrubbing** | `scrub` | Keeps word timestamps so you can replay what you said or re-dictate one word. |
| **Dictation Reflow** | `reflow` | Say "structure this" to rewrite a ramble into bullets + action items. |
| **Acoustic Context Profiles** | `acoustic_profiles` | Detects your environment (quiet/café/car/meeting) and auto-tunes the mic gate + denoise. |
| **Mood Ledger** | `sentiment` | Private speech-sentiment journal; labels stay in the encrypted corpus. |
| **Pronunciation Feedback** | `pronunciation` | Per-phoneme good/fair/poor practice scoring for accent/L2 training. |
| **Personal Read-Back Voice** | `readback_clone` | Read the transcript back in a clone of your own voice (permissive OpenVoice V2). |
| **Gesture Chords** | `gesture` | Bind multi-input chords (held key + nod / key / sEMG squeeze) to actions. |
| **Two-Way Live Interpreter** | `interpret` | Face-to-face mode: each turn is detected and translated into the other language. |

## Wave G — normalization, privacy & new modalities (v2.3)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Entity ITN** | `itn` | Spoken emails/versions → written form, no command words ("john dot doe at gmail dot com"). |
| **Redaction Ink** | `redaction` | Masks spoken secrets (cards via Luhn, SSNs, keys) before they're typed. |
| **Field-Aware Dictation** | `fieldaware` | Shapes output by the focused field; refuses to type into password fields. |
| **Corpus Voiceprint Scrub** | `corpus_scrub` | Speaker-anonymizes stored learning audio (keeps content, not voice). |
| **Compose-in-Target-Language** | `compose` | Speak your strongest language, inject in a target language. |
| **Grammar Repair** | `gec` | Minimal-edit article/agreement fixes for non-native dictation. |
| **Screen-Grounded Dictation** | `screengrounded` | Primes STT with names visible on screen so they transcribe right. |
| **Head-Pointer** | `headpointer` | Move + click the cursor by head pose; fully hands-free with voice. |
| **Silent Lip-Reading** | `lipread` | Dictate with no audible voice; a webcam reads your lips. |
| **Sign-Language Input** | `sign` | Deaf/HoH signers sign to the webcam; ASL is recognized and typed. |

## Wave H — normalization, structured input & awareness (v2.4)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Emoji & Symbol by Voice** | `symbols` | Speak symbols/emoji/arrows → Unicode ("right arrow" → →). |
| **Voice Unit Conversion** | `convert` | "twenty miles in kilometers" → "32.19 kilometers", offline. |
| **Spoken Temporal Normalizer** | `temporal` | "next Friday" → a concrete date, from the local clock. |
| **Mid-Utterance Self-Repair** | `self_repair` | "email Sarah no I mean Sara" → "email Sara" before typing. |
| **Spoken Spreadsheet** | `spreadsheet` | Grid navigation + cell addressing ("next row", "go to B7"). |
| **Clipboard-History by Voice** | `cliphistory` | Recall recent copies by voice ("the second thing I copied"). |
| **Ambient Audio-Event Guard** | `audioguard` | Auto-pause/alert on a doorbell, phone, alarm or your name. |
| **On-Device Condense** | `condense` | Insert a tightened summary of your own long dictation. |
| **Slot-Filling Dictation** | `slotfill` | One utterance fills a named-field template. |
| **Few-Shot Command Spotter** | `cmdspotter` | Enrolled low-latency micro-commands ("send", "stop"). |

## Wave I — safety, patterns & power tools (v2.5, in progress)

All OFF by default. Pure logic ships now; heavy models load only when you enable the feature.

| Feature | `features` name | What it does |
|---|---|---|
| **Terminal Command Safety Gate** | `cmdsafety` | Holds a destructive terminal command until you say "confirm". |
| **Spoken Regex Builder** | `spokenregex` | Build search patterns by voice ("four digits dash two digits" → `\d{4}-\d{2}`). |
| **Structured-Markup Dictation** | `markup` | Speak lists/tables → Markdown/org ("bullet list: apples; oranges"). |
| **Document Find-and-Replace** | `findreplace` | Edit the whole document by voice ("replace every utilise with use"). |
| **Hard Contextual Biasing** | `hotwords` | Biases recognition toward your vocabulary with a hotword trie so rare names win. |
| **Voice Window Management** | `windowctl` | Hands-free desktop layout ("move window left half", "workspace 3"). |
| **Citation-by-Voice** | `cite` | "cite Vaswani 2017" → a formatted citation from your local .bib, offline. |
| **Per-Language Auto Switching** | `langroute` | Detects the language you speak and hot-swaps to its model + ITN. |
| **Adaptive Latency Governor** | `latency` | Keeps dictation responsive under CPU load, faster when idle (speculative decoding). |
| **Diarized Conversation Capture** | `diarize` | Attributed multi-speaker Markdown (**Alice:** …) with rename-by-voice. |

## Privacy

Every v2 feature honours the same guarantees as the rest of YazSes: on-device
processing, no telemetry, and no transcript persistence unless you explicitly enable
the encrypted learning corpus. Context and gaze signals are read transiently and never
stored; the bridge stays on your local link. See the
[privacy statement](https://github.com/MSKazemi/yazses/blob/main/docs/privacy-statement.md).
