# YazSes White Paper Authoring Standard

**Status:** Maintainer guideline  
**Audience:** maintainers, contributors, technical writers, designers, researchers, and automation agents  
**Purpose:** define the evidence, structure, visual system, review gates, and release procedure for producing a professional YazSes white paper that remains accurate as the project evolves.

---

## 1. Why this document exists

A YazSes white paper is not a long README and it is not advertising copy with technical decoration.

It is a durable, externally shareable explanation of:

- what YazSes is;
- which problems it is designed to solve;
- what the shipping software actually does;
- how the system is architected;
- where the privacy boundary is;
- what evidence exists for accuracy, latency, reliability, and platform support;
- which capabilities are optional, experimental, designed-only, or not yet implemented;
- what a technically serious evaluator should verify before adopting it.

The white paper may be read by engineers, security reviewers, accessibility specialists, researchers, open-source contributors, prospective users, institutions, journalists, or potential partners. It therefore has to be understandable without sacrificing precision.

The standard is intentionally strict because YazSes changes quickly. A beautiful white paper that is six releases out of date is worse than no white paper at all.

---

## 2. Normative language

The words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are used in their RFC-style sense.

- **MUST / MUST NOT**: publication gate. A white paper that violates the rule is not ready.
- **SHOULD / SHOULD NOT**: strong default. Deviations require a documented reason.
- **MAY**: optional practice that can improve quality when appropriate.

---

## 3. Scope

This standard governs:

1. the canonical long-form YazSes white paper;
2. derivative one-page briefs and executive summaries;
3. figures, tables, diagrams, and benchmark charts used in those documents;
4. publication metadata and versioning;
5. evidence collection and claim review;
6. final export and visual QA.

This standard does **not** replace:

- user documentation under <code>docs/</code>;
- architecture and decision records under <code>design/</code>;
- the benchmark harness and archived results;
- release notes;
- academic manuscripts.

Those sources are inputs to the white paper.

---

## 4. Repository and artifact policy

### 4.1 What belongs in Git

The **authoring rules, source text, evidence register, reproducible figure definitions, and generation scripts** MAY be tracked in the repository when they are public, technically useful, and consistent with the repository visibility contract.

Generated PDF files MUST NOT be committed to the repository. The repository already treats generated PDFs as build artifacts and enforces that rule.

A released white paper PDF SHOULD instead be attached to a GitHub Release, a DOI-backed archival release, or another project-controlled publication endpoint.

### 4.2 Recommended future layout

If the project later chooses to keep the white paper source in-repository, use a structure similar to:

~~~
publications/
  white-paper/
    README.md
    white-paper.md
    claims.yml
    references.bib
    figures/
      source/
      generated/
    scripts/
      build_whitepaper.py
      verify_claims.py
      verify_links.py
~~~

Do not create this tree merely to satisfy the convention. Create it only when the project is ready to maintain the source and automation.

### 4.3 Binary policy

The source of a figure SHOULD be text or data when practical:

- SVG;
- Mermaid source;
- Graphviz;
- CSV/JSON input plus a generator;
- Python script that deterministically produces the chart.

Raster images MAY be used for screenshots or photos, but should not be the primary representation of architecture or benchmark data.

---

## 5. The central rule: the repository is the source of truth

No factual statement should be copied into a new white paper merely because it appeared in an older white paper.

Every edition starts by re-reading the current repository state.

### 5.1 Required source snapshot

Before drafting, record:

| Field | Required value |
|---|---|
| Repository | <code>MSKazemi/yazses</code> |
| Commit | full 40-character commit SHA |
| Branch or tag | release tag when available; otherwise branch name |
| Package version | read from <code>pyproject.toml</code> |
| White-paper date | ISO date, YYYY-MM-DD |
| Development classifier | read from package metadata |
| Benchmark revision | commit SHA containing the benchmark tables/results |
| Author/reviewer | names or roles responsible for the edition |

The white paper MUST contain at least the package version, publication date, and repository commit or release tag.

### 5.2 Source-of-truth precedence

When two project documents disagree, use this order and investigate the mismatch rather than silently choosing the more attractive statement.

1. **Shipping code and generated registries**
   - feature registry;
   - platform factories;
   - engine factory;
   - configuration schema;
   - packaging metadata.
2. **Tests that assert public behavior**
   - especially tests that guard platform support, privacy boundaries, feature maturity, benchmark provenance, and packaging claims.
3. **Measured benchmark artifacts**
   - archived result data;
   - benchmark harness;
   - manifests and provenance.
4. **As-built architecture documentation**
   - particularly the architecture page and privacy/threat-model documentation.
5. **Generated feature reference**
   - useful because it reflects registry state, but still verify important claims against the implementation.
6. **README and install guides**
   - authoritative summaries for current user-facing behavior.
7. **ADRs/specifications**
   - authoritative for design decisions, but an ADR may describe a decision that is not yet wired into the running system.
8. **Roadmap and research notes**
   - never evidence that a capability ships.

A white paper MUST NOT resolve a contradiction by intuition. Fix the contradiction in the repository or explicitly qualify the statement.

---

## 6. Claim classification

Every important factual statement in the white paper MUST belong to one of the following classes.

### 6.1 Class A - shipping fact

A statement about behavior a user can run in the current build.

Examples:

- a supported command exists;
- a feature is wired;
- an operating system is supported;
- a particular backend is selected under a documented condition.

**Evidence requirement:** shipping code, generated feature registry, current user documentation, or tests.

**Wording:** direct factual language is allowed.

### 6.2 Class B - measured result

A numerical claim produced by a benchmark or experiment.

Examples:

- WER;
- decode latency;
- real-time factor;
- memory use;
- installation size;
- reliability recovery time.

**Evidence requirement:** reproducible benchmark procedure plus archived result/provenance.

**Wording:** MUST state the population/dataset and conditions either in the sentence, table, caption, or immediately adjacent note.

### 6.3 Class C - bounded interpretation

An interpretation derived from evidence but not identical to the raw measurement.

Example:

“On the published short-utterance CPU benchmark, Moonshine has the lowest measured real-time factor among the engines tested.”

This is acceptable because the scope is explicit.

The same sentence without “on the published ... benchmark” is too broad.

**Evidence requirement:** the same evidence as the underlying measurement.

**Wording:** MUST preserve the boundary of the evidence.

### 6.4 Class D - design or roadmap statement

A capability, architecture, or research direction that is designed but not shipping.

**Evidence requirement:** ADR, spec, roadmap, or research record.

**Wording:** MUST contain an explicit maturity qualifier such as:

- “designed, not yet wired”;
- “planned”;
- “experimental”;
- “research direction”;
- “prototype-only”.

Never place a designed-only capability in a feature list whose heading implies that everything in the list is available today.

### 6.5 Class E - external comparison

A claim comparing YazSes with another product, project, or service.

**Evidence requirement:** current first-party documentation for both sides, dated at the time of publication.

**Wording:** factual and narrow.

Good:

“YazSes performs its default transcription path locally; Product X documents a cloud-processing path for feature Y as of DATE.”

Bad:

“YazSes is more private than Product X.”

The second sentence is an evaluation unless the criteria and evidence are made explicit.

### 6.6 Class F - qualitative positioning

A statement such as “local-first”, “offline-by-default”, “privacy-oriented”, or “cross-platform”.

**Evidence requirement:** architecture plus concrete implementation behavior.

These terms are acceptable only when the paper immediately explains what they mean operationally.

---

## 7. Claim register

A high-quality edition SHOULD maintain a machine-readable claim register during drafting.

Recommended fields:

~~~yaml
- id: WP-PRIV-001
  text: "Default dictation transcription runs on-device."
  class: A
  source:
    - docs/architecture.md
    - src/yazses/stt/factory.py
  commit: "<sha>"
  reviewed: true
  reviewer: "..."
  expires_on_change:
    - "src/yazses/stt/**"
    - "src/yazses/remote/**"
~~~

The register is not a bibliography. It is a maintenance tool.

Every number, comparison, platform-support claim, privacy statement, feature-count statement, and maturity statement SHOULD have a claim ID.

---

## 8. Required fact checks before writing

Before any prose is drafted, verify all of the following from the current commit.

### 8.1 Product identity

- package version;
- license;
- development classifier;
- supported Python versions;
- supported operating systems;
- canonical project description.

### 8.2 Core workflows

Verify the exact state of:

- hold-to-talk dictation;
- file transcription;
- meeting capture;
- voice commands;
- text injection;
- local and remote paths;
- optional learning/personalization paths.

### 8.3 Engines and models

Verify:

- default STT engine;
- optional engines;
- engine-specific limitations;
- language constraints;
- model downloads;
- fallback behavior.

### 8.4 Feature maturity

Obtain the current capability inventory from the feature registry or generated feature reference.

Do not reuse an old count.

The white paper MUST distinguish at least:

- core / always-on;
- recommended or enabled-by-default;
- optional;
- experimental;
- planned/designed-only.

### 8.5 Privacy and network behavior

Verify all outbound paths from current code and documentation.

Do not write “YazSes never uses the network” if any user-enabled path can use it.

Prefer precise statements such as:

“Default dictation performs capture, transcription, and local injection without a network call. Networked behaviors are explicit opt-ins and are described separately.”

The exact wording MUST be revalidated against the current privacy statement and architecture.

### 8.6 Installation and platform support

Verify current install paths independently for Linux, macOS, and Windows.

Do not assume the install command from a previous edition still applies.

### 8.7 Benchmarks

Verify:

- dataset and subset;
- sample size;
- hardware;
- operating system;
- software versions;
- model/engine versions;
- decoding parameters;
- confidence intervals when published;
- known instability or repeated-run variance;
- benchmark caveats.

---

## 9. Canonical white-paper structure

The canonical long-form document SHOULD be approximately 10-16 pages of substantive content, excluding a long appendix if one is necessary.

The following order is the default.

### 9.1 Cover

Required:

- YazSes wordmark/name;
- one-sentence description;
- white-paper edition/version;
- publication date;
- project URL;
- repository snapshot/tag.

Avoid a feature collage on the cover. The cover should communicate identity and trust.

### 9.2 Executive summary

Target: 250-450 words.

Answer, in order:

1. What is YazSes?
2. What is the main user interaction?
3. What runs locally?
4. What are the three strongest current workflows?
5. What evidence is available?
6. What maturity/limitations should an evaluator know?

A reader who stops after this section should still understand the project accurately.

### 9.3 The problem

Explain the problem domain without overstating market claims.

Possible dimensions:

- keyboard-heavy workflows;
- privacy-sensitive speech;
- air-gapped or restricted environments;
- subscription/cloud dependency;
- accessibility and motor-load concerns;
- transcription and meeting capture.

Do not invent market-size numbers merely to make the section look commercial.

### 9.4 What YazSes is

Define the product in plain language.

Recommended conceptual framing:

> YazSes is an open-source, offline-by-default desktop voice interface for dictation and speech-to-text workflows. Its core interaction is hold, speak, release: audio is captured locally, transcribed on the user's machine, and the resulting text is injected into the focused application.

This paragraph is a template, not permanent copy. Revalidate every clause.

### 9.5 Three primary workflows

Use one visual with three lanes:

1. **Dictate into any application**
2. **Transcribe an existing recording**
3. **Capture a meeting**

For each lane show:

- input;
- processing;
- output;
- optional dependencies;
- privacy boundary.

### 9.6 Architecture

Explain the system at two levels:

**Level 1 - evaluator view**

Audio capture -> preprocessing -> STT -> post-processing -> target guard -> injection

**Level 2 - engineering view**

- daemon;
- CLI/control plane;
- platform abstraction;
- STT engine seam;
- injection backend seam;
- optional features;
- local IPC;
- remote path when enabled.

Architecture diagrams MUST identify which components are local, optional, and networked.

### 9.7 Privacy and data handling

This section is mandatory.

It SHOULD answer:

- when audio is captured;
- where STT runs;
- whether an account/API key is required;
- what is stored by default;
- what optional features retain data;
- what is encrypted;
- what optional behavior can cross a machine boundary;
- what the user can inspect/delete;
- whether telemetry exists.

Use a “default path” diagram rather than relying only on prose.

### 9.8 Capability and maturity model

Do not dump the entire feature registry into the white paper.

Group capabilities by user value and show maturity.

A compact table is preferred:

| Capability family | Available now | Optional/experimental | Designed only |
|---|---|---|---|
| Core dictation | ... | ... | ... |
| Accuracy/correction | ... | ... | ... |
| Accessibility | ... | ... | ... |
| Meeting/recording | ... | ... | ... |

The exact entries MUST be generated or revalidated from the current registry.

### 9.9 Evidence and benchmarks

Include only benchmark figures that help an evaluator answer a real question.

Recommended order:

1. what was measured;
2. test environment;
3. results;
4. uncertainty/repeatability;
5. what the result does **not** establish.

Never lead with a large number divorced from method.

### 9.10 Deployment and compatibility

Summarize:

- OS support;
- display-server constraints where relevant;
- desktop vs headless paths;
- installation channels;
- CPU/GPU assumptions;
- optional dependency cost.

A deployment table SHOULD indicate “works”, “works with condition”, “not supported”, rather than using vague prose.

### 9.11 Reliability and safety mechanisms

Describe the mechanisms that prevent silent failure or accidental injection when they are present in the current build.

Possible topics:

- target guard;
- config validation;
- daemon supervision;
- microphone change handling;
- staged dictation;
- fallback behavior;
- health/status diagnostics.

The section should explain the failure mode each mechanism addresses.

### 9.12 Use cases

Use concrete scenarios, not personas invented for emotional effect.

Examples:

- confidential local dictation;
- offline transcription;
- developer/editor workflows;
- meeting capture;
- air-gapped environments;
- users reducing keyboard dependence.

Each use case SHOULD state the required feature tier and any relevant limitation.

### 9.13 Limitations and non-goals

This section is mandatory and should be prominent.

Examples of limitations that may need discussion depending on current state:

- Alpha classifier;
- platform-specific injection constraints;
- model/language limitations;
- optional feature installation size;
- experimental feature quality;
- absence of mobile/web support;
- benchmark-to-real-world gap;
- designed but unwired capabilities.

A credible white paper names what the project is not.

### 9.14 Evaluation checklist

End the substantive document with an evaluator-friendly checklist.

Example:

- Can the target OS install using a supported path?
- Does <code>yazses doctor</code> report the required subsystems healthy?
- Is the intended STT engine supported for the target language?
- Does the privacy model satisfy the environment?
- Has latency been measured on the target hardware?
- Is the desired capability shipping rather than planned?

### 9.15 References and reproducibility

List:

- repository snapshot;
- architecture page;
- privacy/threat model;
- feature reference;
- benchmark page;
- benchmark manifest/harness;
- relevant external research;
- project DOI/release archive where applicable.

Use stable landing pages and commit-pinned repository links when possible.

---

## 10. One-page brief standard

The one-page “What is YazSes?” brief is a derivative artifact.

It MUST be generated from claims already approved for the long-form white paper or the same evidence register.

It SHOULD contain only:

- one-sentence definition;
- three workflows;
- one architecture/privacy visual;
- three to five evidence-backed differentiators;
- current maturity/version;
- project URL.

It MUST NOT introduce a new benchmark, comparison, feature claim, or privacy claim that is absent from the evidence set.

---

## 11. Visual design system

The white paper should look like a technical publication, not a sales brochure.

### 11.1 Overall character

Use:

- strong typography;
- generous whitespace;
- restrained accent color;
- consistent grid;
- simple diagrams;
- high data-to-ink ratio;
- clear captions.

Avoid:

- stock photography;
- decorative AI imagery;
- gradients used only for drama;
- dense icon walls;
- fake dashboard screenshots;
- excessive rounded cards;
- dark backgrounds for long-form body text.

### 11.2 Brand source

When a brand mark or palette is needed, derive it from committed YazSes brand assets rather than inventing a separate white-paper identity.

The document should remain legible in grayscale.

### 11.3 Typography

Recommended:

- body: 10.5-12 pt in print-equivalent sizing;
- headings: clear 3-level hierarchy;
- line length: roughly 55-85 characters;
- line spacing: comfortable for sustained reading;
- monospace: only for commands, paths, configuration, and code identifiers.

Use professional, widely available fonts. The build process SHOULD have documented fallbacks so another contributor can reproduce the layout.

### 11.4 Page format

Choose one canonical format per edition and do not mix page sizes.

Recommended digital-first options:

- A4 portrait for international distribution; or
- US Letter portrait when the primary distribution workflow requires it.

A one-page brief MAY use landscape if that materially improves the information hierarchy.

### 11.5 Color

Use one primary accent plus neutral grays.

Semantic colors SHOULD be reserved for meaning, for example:

- shipping/available;
- optional/experimental;
- designed/not available;
- warning/limitation.

Never use color as the only carrier of status. Include text labels or symbols.

---

## 12. Figure standards

Every figure MUST answer a specific question.

### 12.1 Required figure types

A full white paper SHOULD include at least four of these:

1. **Core interaction diagram**
   - hold -> capture -> local STT -> text -> focused app.
2. **Three-workflow diagram**
   - dictation / file transcription / meeting capture.
3. **Architecture diagram**
   - data plane vs control plane.
4. **Privacy-boundary diagram**
   - what remains on-device and which optional path crosses the boundary.
5. **Benchmark chart**
   - only from current archived results.
6. **Capability maturity diagram**
   - available vs experimental vs designed-only.
7. **Deployment matrix**
   - platform and installation path.

### 12.2 Figure provenance

Every quantitative figure MUST be traceable to source data.

The caption SHOULD include a short source identifier.

Example:

“Source: YazSes benchmark archive, commit abc123..., LibriSpeech test-clean subset, 200 utterances.”

### 12.3 Generated figures

Prefer generators over hand-edited charts.

A generator SHOULD:

- read the current source data;
- fail on missing fields;
- use deterministic dimensions;
- refuse label overflow where practical;
- export vector SVG/PDF-compatible artwork;
- have no network dependency during normal rendering.

### 12.4 Screenshots

Screenshots MUST:

- come from the current version;
- show real application output;
- exclude personal/sensitive information;
- be captured at readable scale;
- include a caption identifying what is shown;
- not imply a platform or capability that is unsupported.

If terminal text is staged or reconstructed for legibility, disclose that.

---

## 13. Benchmark and quantitative-claim rules

This is the most important evidence section.

### 13.1 Minimum benchmark disclosure

Every benchmark table or chart MUST disclose:

- dataset name;
- split/subset;
- sample size;
- number of speakers when relevant;
- hardware;
- OS;
- Python/runtime;
- YazSes version/commit;
- engine/model version;
- quantization/device;
- metric definition.

### 13.2 WER

WER MUST NOT be presented as “accuracy” without explanation.

If the document uses “accuracy” as a heading, define that the reported measure is word error rate and lower is better.

The paper MUST explicitly state that clean read-speech results do not predict spontaneous microphone dictation at a desk.

### 13.3 Latency and RTF

Latency claims MUST specify whether they measure:

- decode time;
- end-to-end time;
- first-token time;
- real-time factor;
- median/p95.

Do not mix these metrics in the same chart without clear labeling.

### 13.4 Repeated runs and instability

If archived results show run-to-run instability for a model, the white paper MUST retain that fact.

Do not select the most flattering run.

### 13.5 Confidence intervals

When the benchmark archive contains confidence intervals, publish them or explain why the chart omits them.

A point estimate alone SHOULD NOT be used to claim superiority when intervals materially overlap.

### 13.6 Ranking language

Avoid:

- “best model”;
- “fastest model”;
- “most accurate model”;

unless the scope is explicit.

Preferred:

“Among the eight engine/model configurations measured on this benchmark, X had the lowest point-estimate WER.”

### 13.7 Do not optimize the test to the paper

A benchmark MUST exist independently of the narrative.

Do not rerun with a new subset solely because an old result is inconvenient.

If methodology changes, mark the new series as a new benchmark revision.

---

## 14. Privacy and security writing rules

Privacy claims are high-risk because a single optional network feature can make an absolute sentence false.

### 14.1 Default-path language

Prefer:

- “offline by default”;
- “on-device for the default dictation path”;
- “no account or API key required for core dictation”;

when supported by current code.

Avoid absolute language such as:

- “never uses the network”;
- “nothing can ever leave the machine”;

unless the architecture and all optional behavior make the statement literally true.

### 14.2 Network exceptions

Every networked or cross-machine path that matters to the evaluator MUST be disclosed, including opt-in behavior.

Distinguish:

- audio leaving the machine;
- transcript text leaving the machine;
- version checks;
- model/package download during installation;
- remote injection;
- external local-network services.

Installation-time downloads are not the same thing as runtime data egress. Explain the difference.

### 14.3 Stored data

For any feature that stores:

- audio;
- transcript text;
- voice embeddings;
- usage corpus;
- logs;

state:

- whether it is opt-in;
- where it is stored;
- whether it is encrypted;
- how it can be deleted;
- whether it is uploaded.

Do not generalize from one optional feature to the whole system.

---

## 15. Feature maturity rules

Feature inflation is prohibited.

### 15.1 Availability labels

Every named feature beyond the obvious core SHOULD carry one of:

- **Core**
- **Recommended/default**
- **Optional**
- **Experimental**
- **Designed, not yet wired**

Use the exact current terminology where practical.

### 15.2 Planned features

Planned or designed-only features MAY be discussed in a “future directions” section.

They MUST NOT:

- appear in the executive-summary list of current product capabilities;
- appear in “what YazSes does today” graphics;
- be counted as shipping functionality;
- be shown without a maturity label.

### 15.3 Feature counts

If the paper states a count such as “YazSes has N capabilities”, the number MUST be generated from the current registry at build time or verified on the publication commit.

Prefer “N registry entries, of which X are wired” over a single inflated total.

---

## 16. Platform-support rules

Platform claims change and must be treated as evidence, not branding.

### 16.1 Support matrix

The paper SHOULD show platform support as a table with conditions.

At minimum:

| Platform | Core install | Dictation | Injection path | Important condition |
|---|---|---|---|---|

### 16.2 “Cross-platform”

The phrase “cross-platform” MUST be backed by current support for multiple named desktop operating systems.

It does not imply feature parity.

### 16.3 Packaging

Do not assume identical behavior across:

- pipx/uv;
- native packages;
- Snap;
- WinGet;
- other package managers.

If the white paper names an installation channel, revalidate it on the publication commit.

---

## 17. External product comparisons

Comparisons can date faster than YazSes itself.

### 17.1 Evidence

For every named external product:

- capture the source URL;
- capture the access date;
- prefer first-party documentation;
- quote sparingly;
- compare a concrete capability.

### 17.2 No broad superiority claims

Avoid:

- “more private”;
- “better”;
- “more accurate”;
- “faster”;
- “easier”;

unless the criterion is defined and evidence exists.

### 17.3 Expiration

External comparisons SHOULD be treated as expired after 90 days or after a major competitor release, whichever comes first.

An edition refresh MUST re-check them.

---

## 18. Writing style

### 18.1 Voice

Use:

- precise;
- calm;
- technical but readable;
- evidence-led;
- direct.

Avoid:

- hype;
- “revolutionary”;
- “game-changing”;
- “industry-leading”;
- “military-grade”;
- “zero risk”;
- “perfect accuracy”;
- “guaranteed privacy”.

### 18.2 Sentence construction

Prefer:

“YazSes transcribes the default dictation path locally using the selected on-device STT engine.”

over:

“YazSes leverages cutting-edge AI to deliver seamless next-generation speech intelligence.”

### 18.3 Define terms

Define technical terms on first use:

- STT;
- WER;
- RTF;
- diarization;
- VAD;
- IPC;
- injection backend.

### 18.4 Keep the user model visible

Architecture should be connected to user consequences.

Example:

“Push-to-talk means no audio is captured while the activation control is released.”

This is better than listing the event handler alone.

---

## 19. Citation standard

### 19.1 Internal project sources

Prefer commit-pinned links for evidence in released editions.

For example, link to a file at the exact commit used to generate the paper, not only to <code>main</code>.

### 19.2 Research references

For academic literature:

- cite DOI, arXiv abstract page, publisher landing page, or author landing page;
- do not link directly to a third-party PDF when a landing page exists;
- verify author/title/year/venue;
- do not write a research claim from memory.

### 19.3 Source quality

Preferred order:

1. primary research;
2. standards/specifications;
3. first-party technical documentation;
4. reproducible project measurements;
5. secondary analysis.

Blog posts and social media SHOULD NOT support load-bearing technical claims.

---

## 20. Accessibility standard for the document

The white paper should be readable beyond a sighted desktop-PDF workflow.

### 20.1 Minimum requirements

- sufficient text contrast;
- no information conveyed by color alone;
- meaningful figure captions;
- alt text in source formats that support it;
- logical heading order;
- selectable/searchable text;
- live hyperlinks;
- tables with real text, not screenshots;
- no body text smaller than a comfortable print size;
- page numbers;
- document title metadata.

### 20.2 Charts

Every chart SHOULD have either:

- a companion data table; or
- enough labeled values that the conclusion is available without color interpretation.

---

## 21. White-paper production workflow

Use this workflow for every edition.

### Step 1 - freeze the evidence snapshot

Record commit/tag, version, date, and package classifier.

### Step 2 - generate the fact sheet

Collect:

- current supported platforms;
- current feature maturity;
- current engines;
- current install paths;
- current privacy/network paths;
- current benchmarks.

No prose yet.

### Step 3 - build the claim register

Classify important claims A-F and attach sources.

### Step 4 - draft the executive summary last

Write the body first. The summary should reflect what survived evidence review.

### Step 5 - generate figures from evidence

Do not draw a chart first and then search for data to justify it.

### Step 6 - technical review

At least one reviewer checks:

- architecture;
- feature maturity;
- platform support;
- privacy;
- benchmark interpretation.

### Step 7 - editorial review

Check:

- clarity;
- repetition;
- unexplained jargon;
- unsupported adjectives;
- executive readability.

### Step 8 - render

Export the canonical PDF from the maintained source.

### Step 9 - visual QA

Render every PDF page to an image and inspect at 100% scale.

Check:

- clipping;
- overflow;
- orphaned headings;
- split figures;
- tiny captions;
- broken glyphs;
- table crowding;
- line wrapping;
- page-number consistency;
- broken hyperlinks;
- low-resolution images.

A document is not considered visually reviewed by looking only at the editable source.

### Step 10 - final factual diff

Before publication, compare the evidence snapshot with current <code>main</code>.

If a material behavior changed during drafting, either:

- rebuild on the newer commit; or
- publish against the pinned earlier release and state that explicitly.

### Step 11 - publish artifacts

Recommended release artifacts:

- canonical PDF;
- one-page PDF;
- one-page PNG;
- optional editable source artifact;
- checksum;
- publication metadata.

### Step 12 - archive metadata

Record:

- release URL;
- source commit;
- checksum;
- publication date;
- reviewers;
- superseded prior edition.

---

## 22. Visual QA checklist

Before release, every item MUST be checked.

### Cover

- [ ] title is readable at thumbnail size;
- [ ] version/date are present;
- [ ] repository/release identity is present;
- [ ] no unsupported marketing claim appears on the cover.

### Typography

- [ ] no body text is uncomfortably small;
- [ ] heading hierarchy is consistent;
- [ ] code/commands are visually distinct;
- [ ] no accidental font substitution breaks glyphs.

### Figures

- [ ] every figure has a caption;
- [ ] quantitative figures name their source;
- [ ] labels do not overlap;
- [ ] diagrams remain readable in grayscale;
- [ ] planned items are visibly marked as planned.

### Tables

- [ ] headers repeat across page breaks where supported;
- [ ] cells have adequate padding;
- [ ] long text wraps cleanly;
- [ ] numeric columns are aligned consistently;
- [ ] no table is squeezed to unreadable size.

### Pagination

- [ ] no blank accidental pages;
- [ ] no heading is stranded at the bottom of a page;
- [ ] figures remain with their captions where possible;
- [ ] references do not split awkwardly.

---

## 23. Factual QA checklist

### Identity

- [ ] package version matches <code>pyproject.toml</code>;
- [ ] development classifier is current;
- [ ] license is current;
- [ ] publication commit/tag is recorded.

### Capabilities

- [ ] core workflow claims were re-tested/revalidated;
- [ ] feature counts come from current registry;
- [ ] no designed-only feature is presented as shipping;
- [ ] experimental capabilities are labeled.

### Privacy

- [ ] default runtime network behavior was rechecked;
- [ ] opt-in network paths are disclosed;
- [ ] stored-data behavior is accurate;
- [ ] installation-time downloads are not confused with runtime egress.

### Benchmarks

- [ ] benchmark data comes from archived results;
- [ ] dataset/sample/hardware are disclosed;
- [ ] caveats are retained;
- [ ] repeated-run instability is not hidden;
- [ ] no point estimate is oversold.

### Platforms

- [ ] install commands are current;
- [ ] platform matrix is current;
- [ ] Wayland/X11/macOS/Windows distinctions are accurate where relevant.

### External comparisons

- [ ] each external claim has a current first-party source;
- [ ] access date is recorded;
- [ ] comparison language is narrow and factual.

---

## 24. Automated checks recommended for the future

A mature white-paper pipeline SHOULD eventually provide a command such as:

~~~
python scripts/build-whitepaper.py --ref vX.Y.Z
~~~

and fail if any gate below fails.

Recommended automated checks:

1. version in source does not match package metadata;
2. source commit field is missing;
3. feature counts do not match registry;
4. planned features appear in the “available today” list;
5. benchmark values differ from archived result files;
6. benchmark chart omits required provenance;
7. direct third-party PDF links appear;
8. URLs return errors;
9. generated SVG labels overflow;
10. PDF contains a blank page;
11. PDF metadata title/version are missing;
12. one-page brief contains a claim ID absent from the long-form evidence set.

Automation should verify facts that machines can verify and leave interpretation to human review.

---

## 25. Release naming and versioning

Recommended file names:

- <code>YazSes-White-Paper-vX.Y.Z-YYYY-MM-DD.pdf</code>
- <code>YazSes-One-Page-Brief-vX.Y.Z-YYYY-MM-DD.pdf</code>
- <code>YazSes-One-Page-Brief-vX.Y.Z-YYYY-MM-DD.png</code>

The white-paper edition is tied to both:

- YazSes software version; and
- publication date.

If the paper is revised without a software release, add an edition suffix or revision field rather than pretending the software version changed.

Example:

“White Paper for YazSes 2.40.0 - revision 2, 2026-10-12.”

---

## 26. Refresh triggers

The white paper SHOULD be reviewed when any of the following occurs:

- new minor/major release;
- default STT engine changes;
- benchmark methodology changes;
- platform-support change;
- privacy/network behavior change;
- feature maturity changes materially;
- new meeting/transcription architecture;
- installer/channel change;
- external comparison becomes stale;
- security/privacy issue changes a published statement.

A scheduled review every 90 days is reasonable even when no trigger is noticed.

---

## 27. Definition of done

A YazSes white paper is ready to publish only when all of the following are true:

1. the document is pinned to a repository commit or release;
2. every load-bearing claim has evidence;
3. current and planned capabilities are clearly separated;
4. privacy language matches the actual architecture;
5. benchmark claims include methodology and caveats;
6. platform support has been revalidated;
7. external comparisons, if any, have current sources;
8. all figures have provenance and readable captions;
9. every page has been visually inspected after final render;
10. the PDF is accessible enough for practical reading and searching;
11. links and metadata have been checked;
12. the one-page brief, if produced, contains no independent unsupported claims;
13. the generated PDF is published as an artifact rather than committed as repository source;
14. the publication metadata and reviewers are recorded.

If any of these is false, the edition is a draft.

---

## 28. Maintainer template for a new edition

Copy this block into the working source at the beginning of a new white-paper cycle.

~~~
White paper target: YazSes <version>
Source ref: <tag or branch>
Source commit: <40-char SHA>
Evidence frozen: <YYYY-MM-DD>
Publication target: <YYYY-MM-DD>
Development classifier: <current classifier>

Technical reviewer:
Privacy/security reviewer:
Benchmark reviewer:
Editorial reviewer:

Required refresh areas:
- [ ] product identity
- [ ] core workflows
- [ ] architecture
- [ ] privacy/network behavior
- [ ] feature maturity
- [ ] benchmarks
- [ ] platform/install support
- [ ] limitations
- [ ] external comparisons
- [ ] references
- [ ] figures
- [ ] final PDF visual QA
~~~

---

## 29. Final principle

The best YazSes white paper should make a skeptical technical reader trust the document **because it shows its boundaries**.

The project already has an unusually strong foundation for this: public architecture records, explicit feature maturity, reproducible benchmarks, and a documented privacy posture. The white paper should preserve that discipline.

**Do not make YazSes sound larger than the evidence. Make the evidence easy to see.**
