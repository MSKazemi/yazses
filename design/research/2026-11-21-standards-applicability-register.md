# YazSes standards, specifications and regulatory applicability register

**Status:** Research inventory for maintainer review — not a certification, legal opinion, claim of conformity or approval to change runtime behavior.  
**Reviewed:** 2026-11-21 (Europe/Rome).  
**Repository snapshot:** [main @ 8ecfd4a](https://github.com/MSKazemi/yazses/tree/8ecfd4aeadcdeea8590754445653854ddc2ae82a).  
**Scope:** Linux, macOS, Windows and optional Android; offline ASR/dictation, meeting capture, accessibility, multilingual UI, opt-in AI/agent interaction, camera/gaze and biosignals, security, packaging and research.  
**Inventory:** 98 references in 10 topical categories.

This is a *relevance register*, not a list of mandatory certifications. It distinguishes formal consensus standards (ISO/IEC/IEEE/ETSI/ITU/Ecma), community protocol specifications and engineering frameworks, and laws/directives. A reference is **Core** when it should inform current product engineering; **Targeted** when relevant to an existing optional capability or research; **Reference** when contextual; **Governance** when primarily organizational; **Conditional** when contingent on future feature or deployment; and **Scope-check** where applicability requires legal/product characterization. A law's inclusion does not imply it applies to all YazSes uses. Standards referenced by version should be rechecked before an external conformity claim. Proprietary standard texts may require a license; link official catalogue landing pages rather than copying their text.

### Current repo evidence to reconcile

- [AGENTS.md](../../AGENTS.md) sets zero-egress, opt-in features and citation hygiene; [ADR-011](../adr/adr-011.md) is accepted privacy guidance and [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md) governs egress.
- [Architecture](../../docs/architecture.md), [privacy statement](../../docs/privacy-statement.md), [accessibility and throughput spec](../accessibility-and-throughput-spec.md), and [threat model](../threat-model.md) are relevant implementation inputs, not evidence of full standard conformity.
- [ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md) is **proposed**: it provides a more appropriate reproducible WER/CER/latency protocol than substituting telephony speech-quality recommendations for ASR accuracy.
- [ADR-v2-150](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md) is **proposed**: community QA does not automatically become human-participant research evidence.
- The committed [SBOM](../../sbom.cdx.json) declares **CycloneDX specVersion 1.5**; ECMA-424 2nd edition defines CycloneDX 1.7. Version difference is an update/evaluation opportunity, **not proof the existing SBOM is invalid**.
- Existing Qt theme and keyboard tests mention WCAG contrast; these tests do not establish whole-product accessibility conformance.

### Suggested work order

1. **Baseline accessibility:** derive feature-specific test criteria from EN 301 549, ISO 9241-171 (mind its assistive-software scope caveat) and WCAG 2.2 for actual web surfaces; run manual Linux/macOS/Windows keyboard/screen reader/voice-only flows. Link to [accessibility research epic #790](https://github.com/MSKazemi/yazses/issues/790).
2. **Secure offline development:** map NIST SSDF to AGENTS.md/CI, retained local audio and logs, signed releases, egress policy, SBOM and dependency provenance. Keep all changes offline-safe and off by default.
3. **Reproducible speech evaluation:** implement evidence only after the decision on [ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md); track WER, CER, correction cost, cold/warm latency and subgroup/error coverage. See [ASR epic #787](https://github.com/MSKazemi/yazses/issues/787).
4. **Multilingual correctness:** test Unicode bidi, grapheme segmentation, script and BCP 47 tags with Persian-English and Chinese profiles; see [multilingual research #797](https://github.com/MSKazemi/yazses/issues/797).
5. **Conditional lanes:** open XR, biosignal/EDF+, NLIP, Android and medical standards work only after a feature or intended-use decision. No medical claims or high-risk AI classification without scope review.

### Change-control and evidence requirements

For each potential standard adoption: record edition, scoped feature, applicable clauses, owning code and tests, gap/risk, validation method and documented evidence. Create a new issue only if no existing epic/issue covers the gap. Proposed deadlines require owner approval. Nothing in this register authorizes new telemetry, model downloads, cloud runtime, clinical use, legal marketing claims or publication of participant material. Technical research belongs in the public repo; commercial plans remain separate and are not in scope here.

---
## Accessibility, usability and inclusive interaction

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [ETSI EN 301 549 V4.1.1 (2026-09)](https://www.etsi.org/technical-groups/hf/) | Core | Accessibility requirements for ICT, including non-web software and web surfaces; evaluate relevant clauses, not blanket conformance |
| [ISO 9241-171:2025](https://www.iso.org/standard/86308.html) | Core | Accessibility of interactive software and integration of assistive technology; its scope does not define all behavior of assistive software itself |
| [WCAG 2.2 (W3C)](https://www.w3.org/TR/WCAG22/) | Core | Website, browser-based demo, and web documentation; apply appropriate criteria to Qt UI by analogy, not as native-app certification |
| [ISO/IEC 40500:2025](https://www.iso.org/standard/91029.html) | Reference | ISO/IEC adoption of WCAG 2.2; avoid treating it as a separate additional UI test suite |
| [ISO 9241-210:2019](https://www.iso.org/search.html?q=9241-210) | Core | Human-centred research, design and iterative evaluation |
| [ISO 9241-11:2018](https://www.iso.org/search.html?q=9241-11) | Core | Usability: effectiveness, efficiency, satisfaction and context of use |
| [WAI-ARIA 1.2](https://www.w3.org/TR/wai-aria-1.2/) | Targeted | Web widgets, documentation interactions and hosted demos only |
| [WCAG-EM 1.0](https://www.w3.org/TR/WCAG-EM/) | Reference | Repeatable methodology for assessing accessible web content; methodology, not a new substantive standard |

## Speech, audio, annotation and ASR research

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [ISO 24624:2016](https://www.iso.org/standard/37338.html) | Targeted | Spoken-language transcription annotation and corpus interchange |
| [ISO 24617-2:2020](https://www.iso.org/search.html?q=24617-2) | Targeted | Dialogue-act annotation for command/dialogue research |
| [ITU-T P.800](https://www.itu.int/rec/T-REC-P.800) | Targeted | Subjective evaluation of perceived speech quality |
| [ITU-T P.808](https://www.itu.int/rec/T-REC-P.808) | Targeted | Crowdsourced subjective speech-quality assessment |
| [ITU-T P.835](https://www.itu.int/rec/T-REC-P.835) | Targeted | Perceived speech, noise and overall quality of noise-suppressed audio |
| [ITU-T P.851](https://www.itu.int/rec/T-REC-P.851) | Targeted | Subjective assessment of spoken dialogue systems |
| [ITU-T P.863](https://www.itu.int/rec/T-REC-P.863) | Targeted | Objective perceptual listening quality of speech |
| [RFC 6716 (Opus)](https://www.rfc-editor.org/rfc/rfc6716) | Conditional | Audio compression interoperability, only for supported export/import formats |
| [RFC 7845 (Ogg Opus)](https://www.rfc-editor.org/rfc/rfc7845) | Conditional | Opus in Ogg container if recordings/export support this format |

## Multilingual text, scripts, locale and text security

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [Unicode Standard (18.0 as of review date)](https://www.unicode.org/releases/) | Core | Unicode storage, rendering and character semantics; verify separately which Unicode version Python/Qt embeds |
| [UAX #9 Unicode Bidirectional Algorithm](https://www.unicode.org/reports/tr9/) | Core | Right-to-left and mixed Persian/English text |
| [UAX #14 Line Breaking](https://www.unicode.org/reports/tr14/) | Targeted | Line wrapping of multilingual transcripts and captions |
| [UAX #15 Normalization Forms](https://www.unicode.org/reports/tr15/) | Core | Normalization without unintended loss of transcript fidelity |
| [UAX #29 Text Segmentation](https://www.unicode.org/reports/tr29/) | Core | Grapheme clusters, cursoring, word boundaries and error metrics |
| [UTS #35 LDML](https://unicode.org/reports/tr35/) | Targeted | Locale display, formats and localized UI data |
| [UTS #39 Unicode Security Mechanisms](https://www.unicode.org/reports/tr39/) | Targeted | Confusable identifiers and risky dictated technical text |
| [Unicode CLDR (49 as of review date)](https://cldr.unicode.org/index/downloads) | Targeted | Language and locale data; application dependencies may use earlier datasets |
| [ISO 639:2023](https://www.iso.org/standard/74575.html) | Core | Language codes and language names for engine metadata |
| [ISO 15924:2022](https://www.iso.org/standard/81905.html) | Core | Script identifiers, e.g. Hans/Hant |
| [BCP 47 / RFC 5646](https://www.rfc-editor.org/rfc/rfc5646) | Core | Interoperable language tags, e.g. fa-IR, zh-Hans, zh-Hant |
| [RFC 4647](https://www.rfc-editor.org/rfc/rfc4647) | Targeted | Language matching and fallback |
| [ISO 3166-1](https://www.iso.org/iso-3166-country-codes.html) | Reference | Region tags used with language metadata |

## Security, privacy, encryption and threat modeling

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [ISO/IEC 27001:2022](https://www.iso.org/standard/27001) | Governance | Organizational information-security management; not a product-level certificate |
| [ISO/IEC 27002:2022](https://www.iso.org/search.html?q=27002) | Governance | Security controls and implementation guidance |
| [ISO/IEC 27701:2025](https://www.iso.org/standard/27701) | Governance | Privacy information management system |
| [ISO/IEC 29100](https://www.iso.org/search.html?q=29100) | Reference | Privacy framework and vocabulary |
| [ISO/IEC 20889:2018](https://www.iso.org/standard/69373.html) | Targeted | De-identification methods for shared study/QA data |
| [NIST SP 800-218 SSDF v1.1](https://csrc.nist.gov/pubs/sp/800/218/final) | Core | Secure software development practices and security review gates |
| [NIST Cybersecurity Framework 2.0](https://www.nist.gov/cyberframework) | Governance | Security governance and risk management |
| [NIST Privacy Framework](https://www.nist.gov/privacy-framework) | Reference | Risk analysis for personal audio, transcripts, camera and research records |
| [NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final) | Targeted | GCM authenticated encryption for opt-in encrypted local storage |
| [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) | Conditional | Web-based deployments, demos or exposed interfaces; not a blanket requirement for local daemon |
| [RFC 8446 (TLS 1.3)](https://www.rfc-editor.org/rfc/rfc8446) | Conditional | User-authorized remote secure HTTPS connections only |
| [RFC 4253 (SSH transport)](https://www.rfc-editor.org/rfc/rfc4253) | Targeted | Explicitly opted-in SSH remote text destination |

## AI lifecycle, risk, fairness, evaluation and reproducibility

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [ISO/IEC 42001:2023](https://www.iso.org/standard/42001) | Governance | AI management systems; organizational scope |
| [ISO/IEC 23894:2023](https://www.iso.org/standard/77304.html) | Targeted | AI risk management guidance |
| [ISO/IEC 42005:2025](https://www.iso.org/search.html?q=42005) | Targeted | AI impact assessment and affected-user considerations |
| [ISO/IEC 5338:2023](https://www.iso.org/standard/81118.html) | Targeted | AI system life-cycle processes |
| [ISO/IEC 25059:2023](https://www.iso.org/standard/80655.html) | Targeted | Quality model for AI systems |
| [ISO/IEC 22989:2022](https://www.iso.org/search.html?q=22989) | Reference | AI concepts and terminology |
| [ISO/IEC 23053:2022](https://www.iso.org/search.html?q=23053) | Reference | AI systems using machine learning: conceptual framework |
| [ISO/IEC TR 24027:2021](https://www.iso.org/standard/77607.html) | Targeted | Bias in AI systems and AI-aided decision-making; accent and language subgroup analysis |
| [ISO/IEC TR 24028:2020](https://www.iso.org/search.html?q=24028) | Reference | Overview of trustworthiness in AI |
| [NIST AI RMF 1.0](https://www.nist.gov/itl/ai-risk-management-framework) | Targeted | Voluntary AI risk management and evidence-based assessment |

## Software quality, architecture, requirements and testing

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html) | Core | Software product quality including reliability, performance, usability and security |
| [ISO/IEC 25019:2023](https://www.iso.org/standard/78177.html) | Targeted | Quality-in-use measures and user experience |
| [ISO/IEC/IEEE 29119-1:2022](https://www.iso.org/standard/81291.html) | Targeted | Software testing concepts and evidence |
| [ISO/IEC/IEEE 29148:2018](https://www.iso.org/standard/72089.html) | Targeted | Traceable, verifiable software requirements |
| [ISO/IEC/IEEE 12207:2017](https://www.iso.org/search.html?q=12207) | Reference | Software life-cycle processes |
| [ISO/IEC/IEEE 42010:2022](https://www.iso.org/search.html?q=42010) | Targeted | Architecture descriptions and viewpoints |

## Open-source licensing, packaging, SBOM and supply chain

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [SPDX / ISO/IEC 5962:2021](https://spdx.dev/use/specifications/) | Core | Machine-readable license and component metadata; distinguish current SPDX spec from its ISO adoption |
| [CycloneDX / ECMA-424 2nd ed. (Dec 2025)](https://ecma-international.org/publications-and-standards/standards/ecma-424/) | Core | SBOM standard based on CycloneDX 1.7; repository currently contains a CycloneDX 1.5 SBOM |
| [OpenChain ISO/IEC 5230:2020](https://openchainproject.org/) | Governance | Open-source license-compliance management |
| [OpenChain ISO/IEC 18974:2023](https://openchainproject.org/) | Governance | Open-source security assurance |
| [SLSA v1.2](https://slsa.dev/spec/v1.2/) | Targeted | Artifact provenance, build integrity and supply-chain controls |
| [Package-URL / ECMA-427:2025](https://ecma-international.org/publications-and-standards/standards/ecma-427/) | Targeted | Standard identifiers for dependency/component references |
| [OpenSSF Scorecard](https://securityscorecards.dev/) | Reference | Open-source security hygiene assessment; not a formal ISO conformance standard |
| [PEP 517](https://peps.python.org/pep-0517/) | Core | Python build backend interface |
| [PEP 621](https://peps.python.org/pep-0621/) | Core | pyproject.toml project metadata |
| [PEP 639](https://peps.python.org/pep-0639/) | Targeted | Python package license metadata and license files |
| [PEP 440](https://peps.python.org/pep-0440/) | Core | Python distribution version identification and constraints |

## Desktop, local IPC, operating-system APIs and agent interoperability

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/) | Core | Linux configuration, state, cache and local-data placement |
| [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry/latest/) | Targeted | Linux launcher integration and desktop metadata |
| [XDG Desktop Portal RemoteDesktop API](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html) | Targeted | Permission-mediated remote-control/input on Wayland |
| [AT-SPI2](https://www.freedesktop.org/wiki/Accessibility/AT-SPI2/) | Core | Linux assistive technology and accessible target information |
| [Microsoft UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview) | Core | Windows accessibility and target interaction API |
| [Apple Accessibility APIs](https://developer.apple.com/documentation/applicationservices/accessibility) | Core | macOS Accessibility/AX integration |
| [Android InputMethodService / IME](https://developer.android.com/develop/ui/views/touch-and-input/creating-input-method) | Conditional | Android port: keyboard semantics, input connection and platform restrictions |
| [D-Bus specification](https://dbus.freedesktop.org/doc/dbus-specification.html) | Targeted | Linux local IPC interoperability |
| [RFC 8259 (JSON)](https://www.rfc-editor.org/rfc/rfc8259) | Core | JSON interoperability for locally exchanged messages |
| [JSON-RPC 2.0](https://www.jsonrpc.org/specification) | Targeted | Local IPC method/response protocol (community specification; not an IETF RFC) |
| [Model Context Protocol (MCP)](https://modelcontextprotocol.io/specification/) | Conditional | Opt-in coding-agent integration with explicit trust boundaries |
| [ECMA-430:2025 (NLIP)](https://ecma-international.org/publications-and-standards/standards/ecma-430/) | Conditional | Natural-language interaction protocol for future interoperation |
| [ECMA-431 to ECMA-434:2025](https://ecma-international.org/publications-and-standards/standards/) | Conditional | NLIP transports and security profiles, only if NLIP interoperation is investigated |

## Optional XR, biosignal, research and medical-device paths

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [OpenXR 1.1](https://registry.khronos.org/OpenXR/) | Conditional | XR client runtime/API interoperability; XR track is research, not a shipping integration |
| [W3C WebXR Device API](https://www.w3.org/TR/webxr/) | Conditional | Browser-based immersive interaction research; confirm current maturity |
| [EDF+](https://www.edfplus.info/specs/edfplus.html) | Conditional | Physiological time-series data interchange for consenting research participants |
| [BIDS-EEG](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html) | Conditional | Structured EEG study datasets and metadata, where licensed/consented |
| [Lab Streaming Layer (LSL)](https://labstreaminglayer.readthedocs.io/info/intro.html) | Conditional | Time synchronization and live streams for experimental sensors |
| [IEC 62304:2006 + AMD1:2015](https://www.iso.org/standard/38421.html) | Conditional | Medical-device software lifecycle, only if intended medical-device use brings YazSes into scope |
| [ISO 14971:2019](https://www.iso.org/standard/72704.html) | Conditional | Medical-device risk management, only for intended medical-device use |
| [ISO 13485:2016](https://www.iso.org/standard/13485) | Conditional | Medical-device quality-management system, only for a regulated medical-device operation |
| [ISO 14155:2020](https://www.iso.org/search.html?q=14155) | Conditional | Clinical investigations of medical devices, only for studies within its scope |

## Regulations and jurisdiction-specific obligations (not technical standards)

| Reference | Applicability | Why YazSes should track it |
|---|---|---|
| [EU GDPR (Regulation 2016/679)](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng) | Scope-check | User or study personal data; pure on-device user processing is not automatically a developer-controlled database |
| [EU AI Act (2024/1689; amended 2026/1744)](https://eur-lex.europa.eu/eli/reg/2024/1689/2026-07-27/eng) | Scope-check | Classify role and use case before assessing obligations; Annex III high-risk date Dec 2 2027, Annex I Aug 2 2028 |
| [EU Cyber Resilience Act (2024/2847)](https://eur-lex.europa.eu/eli/reg/2024/2847/oj/eng) | Scope-check | Assess commercial digital-product distribution and OSS steward roles separately; free non-commercial OSS has distinct treatment |
| [European Accessibility Act (Directive 2019/882)](https://eur-lex.europa.eu/eli/dir/2019/882/oj/eng) | Scope-check | Only covered product/service categories and national transposition, not automatically every free desktop utility |
| [EU Web Accessibility Directive (2016/2102)](https://eur-lex.europa.eu/eli/dir/2016/2102/oj/eng) | Conditional | Public-sector website/mobile-app settings where applicable |
| [EU Medical Device Regulation (2017/745)](https://eur-lex.europa.eu/eli/reg/2017/745/oj/eng) | Conditional | Only if intended purpose/claims qualify as a regulated medical device |
| [US Revised Section 508](https://www.section508.gov/manage/laws-and-policies/) | Conditional | US federal procurement/in-scope covered ICT |

---

## Boundaries and key interpretations

- **Telephony audio quality is not transcript quality.** ITU-T P.8xx and P.863 measure perceived signal/dialogue characteristics, not WER/CER for offline ASR; a YazSes-specific pinned benchmark protocol is still needed.
- **WCAG is web-content guidance.** Native Qt/OS accessibility needs its own API, focus/keyboard, speech and assistive-technology tests; EN 301 549 has broader ICT scope.
- **A management standard is not a product certificate.** ISO/IEC 27001, 27701 and 42001 concern organizational systems; no adoption/certification is asserted here.
- **Hardware/clinical standards are conditional.** Experimental gaze, EMG/EEG and accessibility work alone does not establish a medical intended purpose.
- **EU AI Act dates reflect the 2026 consolidated text.** Recheck the current EUR-Lex consolidated act before legal use; ordinary offline dictation is not automatically a high-risk AI system.
- **The EU CRA distinguishes commercial products and non-commercial open-source activity.** Scope and steward/manufacturer responsibilities require specific analysis, not a blanket claim.

## Review and validation commands (future work; NOT executed in this research update)

```sh
uv sync
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
```

For any documentation-only follow-up, run the applicable docs/citation checks before requesting merge. Review this register against [AGENTS.md](../../AGENTS.md) and the current standard editions first.
