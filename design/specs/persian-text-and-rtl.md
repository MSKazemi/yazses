# Persian Text and RTL Specification

**Status:** Proposed  
**Applies to:** `[stt] language = "fa"`  
**Design goal:** make Persian output stable and safe without turning normalization into a language model.

---

## 1. Principles

Persian post-processing must be:

- deterministic;
- idempotent;
- local/offline;
- conservative;
- safe for mixed Persian/English content;
- independent from transliteration;
- independent from UI locale.

The normalizer may canonicalize Unicode variants. It must not rewrite sentence meaning, guess grammar, translate English, or silently alter code/URLs.

## 2. Processing order

Recommended order:

```text
raw ASR text
 -> Unicode NFC
 -> Persian letter canonicalization
 -> safe zero-width cleanup
 -> safe punctuation/spacing normalization
 -> generic YazSes cleaners
 -> command-safety classification
 -> injection
```

The Persian normalizer should run on final transcription text and on per-word text where word objects are exposed, so subtitles/meeting/streaming surfaces do not disagree.

## 3. Canonical character mappings

In Persian-language output, normalize common Arabic code points that are visually similar but semantically inconsistent for Persian text:

| Input | Output | Name |
|---|---|---|
| U+064A `ي` | U+06CC `ی` | Arabic Yeh -> Farsi Yeh |
| U+0649 `ى` | U+06CC `ی` | Alef Maksura -> Farsi Yeh, only when emitted as Persian letter text |
| U+0643 `ك` | U+06A9 `ک` | Arabic Kaf -> Keheh |

Do not apply mappings inside explicitly protected spans such as URLs or code when the mapping would change an identifier.

The implementation should expose the table as data and test every mapping in both isolated and sentence contexts.

## 4. Unicode normalization

Apply NFC.

Do not use compatibility normalization (NFKC/NFKD) as the default because it may rewrite compatibility characters beyond the Persian support scope.

Preserve valid combining marks.

## 5. ZWNJ / half-space

U+200C ZERO WIDTH NON-JOINER is meaningful Persian orthography and must not be stripped by generic whitespace cleanup.

Rules:

- preserve an existing valid ZWNJ;
- collapse repeated adjacent ZWNJs to one only when no semantic information is lost;
- remove a ZWNJ at absolute string boundaries;
- do not insert ZWNJ using a dictionary or morphology heuristic in the initial release;
- do not convert ordinary spaces to ZWNJ automatically.

A future morphology-aware feature can be separate, opt-in, and benchmarked.

## 6. Bidi controls

The production transcript should not need explicit RLE/LRE/RLO/LRO/PDF or isolate controls in ordinary Persian text.

Policy:

- preserve ordinary Persian/Latin logical character order;
- reject or strip unexpected directional override controls introduced by model output unless a specific safe use is documented;
- do not strip ZWNJ/ZWJ merely because they are zero-width;
- keep bidi-control handling in a small audited function with adversarial tests.

Security-oriented tests should cover hidden overrides around URLs, filenames, and command-looking text.

## 7. Digits

Initial policy: **preserve what the model emitted**.

Do not automatically convert:

- ASCII 0-9,
- Arabic-Indic U+0660..U+0669,
- Eastern Arabic/Persian U+06F0..U+06F9.

Reason: user preference and context differ, and normalization could corrupt technical text.

A later explicit setting may offer digit style:

```toml
[persian]
digits = "preserve"   # preserve | persian | ascii
```

If added, default remains `preserve`.

## 8. Punctuation

Do not globally replace ASCII punctuation with Persian punctuation.

Safe optional mappings may be considered only when context is unambiguous, for example Persian comma `،`, but the first release should preserve model punctuation unless benchmark evidence shows a clear benefit.

Whitespace around punctuation should follow existing YazSes generic rules unless a Persian-specific test demonstrates breakage.

## 9. Mixed Persian/English text

Examples such as these must survive:

```text
من از VS Code استفاده می‌کنم.
ایمیل من name@example.com است.
فایل در /home/user/project قرار دارد.
نسخه Python 3.13 را نصب کن.
```

Requirements:

- Latin runs remain byte-for-byte unchanged unless generic YazSes processing already has a documented transform;
- URLs, emails, paths, semantic versions, package names, and code identifiers remain intact;
- Persian normalization may run around protected Latin spans without merging or reordering them.

## 10. Injection exactness

For every backend under test:

```text
final_text code points == code points received by target harness
```

The harness should record code points, not only screenshots.

Visual QA remains necessary because correct code points can still render poorly due to bidi/layout problems.

## 11. UI rendering

The whole YazSes UI must not switch to RTL merely because dictation language is Persian.

Use localized direction at content surfaces:

- transcript preview: auto/RTL based on content;
- user-editable Persian text fields: auto direction where toolkit support exists;
- labels/buttons/settings chrome: remain in application UI locale;
- mixed transcript lines: rely on Unicode bidi algorithm rather than manual reversal.

Never reverse strings in application code.

## 12. Tests

Minimum unit cases:

- `سلام دنیا`;
- Arabic Yeh/Kaf contamination;
- existing ZWNJ;
- repeated ZWNJ;
- leading/trailing ZWNJ;
- Persian + English;
- Persian + URL;
- Persian + email;
- Persian + path;
- Persian/ASCII digits;
- emoji;
- combining marks;
- bidi override controls;
- empty/whitespace input;
- 5,000+ character Persian text.

Required properties:

- idempotence;
- output is valid Unicode;
- no Latin run deletion;
- no new lexical Persian letters inserted except explicit canonical substitutions;
- generic command classification cannot flip ordinary Persian dictation into an action by accident.

## 13. Acceptance criteria

The Persian normalizer is acceptable when:

1. all documented mappings are exact and tested;
2. mixed Persian/English fixtures remain intact;
3. ZWNJ survives meaningful cases;
4. unsupported bidi controls cannot create hidden command-like text;
5. injection tests show code-point equality;
6. disabling/changing the Persian profile cannot alter English output.
