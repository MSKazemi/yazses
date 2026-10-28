# Pre-publication privacy and release checklist (Hugging Face HCI artifacts)

Status: checklist and evidence report dated 2026-10-28; read-only. Part of epic #692 / issue #701.
**This is a review gate, not an authorisation to publish.** Nothing here creates, uploads or
changes anything on the Hub. The account owner decides whether any artifact is published.

Scope: the static Space prototype (`examples/hci-hf-lab/`, draft PR #703), its draft dataset card,
and any model repository. The Space source is audited as it stands in that branch; it is not on
the Hub.

## How to read the status column

| Status | Meaning |
|---|---|
| PASS | A check ran and its result is recorded in the evidence column. |
| PASS (static) | Verified by reading the shipped files or by a test; not observed at run time on the Hub. |
| OPEN | Not done, or a recommendation nobody has applied yet. |
| N/A | The risk does not apply to this artifact, with the reason stated. |
| BLOCKED | Cannot be assessed until a dependency lands. |

## The release gate

Publication of any HCI artifact stays **BLOCKED** until all of these hold:

| Gate | State on 2026-10-28 |
|---|---|
| Static demo reviewed by the owner (#693, draft PR #703) | BLOCKED: open draft, not reviewed |
| Publication playbook (#698) | BLOCKED: [drafted](HF_PUBLICATION.md), not reviewed |
| Model provenance inventory reviewed (#694, draft PR #704) | BLOCKED: open draft, not reviewed |
| Every OPEN row below resolved or accepted by the owner in writing | BLOCKED: see the tables |
| ADR-030 alignment confirmed for a public release | OPEN: owner decision |

## A. Static Space audit

Threat model: a visitor opens the page. The risk is any data leaving the browser, any device
prompt, or any claim the page makes that it cannot keep.

| # | Risk | Mitigation in the artifact | Test or evidence | Owner | Status |
|---|---|---|---|---|---|
| A1 | The page asks for the camera or microphone, or uses another device API | Only synthetic fixtures are replayed; no `getUserMedia`, `MediaRecorder`, Bluetooth, HID, serial or USB use | `tests/test_hci_hf_lab.py::test_app_files_use_no_device_or_network_api` fails on any identifier in `FORBIDDEN_IDENTIFIERS`; a manual check over local HTTP on 2026-10-28 showed no permission prompt | maintainer | PASS (static) |
| A2 | A network request after load (fetch, XHR, WebSocket, beacon, EventSource, form post) | None of those identifiers appear in the shipped JS/HTML; there is no `<form>` | same test; the manual check listed 6 requests, all same-origin, and 0 console messages | maintainer | PASS (static) |
| A3 | An external script, stylesheet, font, image, iframe or embed | All assets are local (`fixtures.js`, `resolver.js`, `app.js`, `style.css`, `assets/logo.svg`); no web fonts, no `@import` | `test_index_loads_only_local_assets`, `test_app_files_have_no_external_urls`; a grep for `http(s)://` in the shipped `.html`, `.css` and `.js` files found none | maintainer | PASS (static) |
| A4 | Browser storage, cookies or fingerprinting by the demo | `localStorage`, `sessionStorage` and `indexedDB` are on the forbidden list; no analytics or telemetry code | same device/network test; grep above | maintainer | PASS (static) |
| A5 | The logo is not the canonical mark | `assets/logo.svg` must be byte-identical to `contrib/icons/yazses.svg` | `test_logo_is_the_canonical_icon` | maintainer | PASS |
| A6 | The fixtures contain real people's data | Hand-authored, `synthetic: true`, no identifiers; the schema rejects malformed or incomplete cases | `test_fixtures_parse_and_validate`, `test_validator_rejects_bad_fixtures`; the prototype uses schema `0.1-prototype` (not the canonical schema, see #699) | maintainer | PASS (static) |
| A7 | The page implies a measured result, an accuracy figure or a product feature | The README and page say every number is simulated and every outcome is "Preview only - nothing was executed." EEG/EOG is a research proposal, never auto-accepted, no medical claim | `test_dataset_card_is_a_labelled_draft`, the resolver tests that EEG never auto-accepts; wording reviewed in the PR | maintainer | PASS (static) |
| A8 | A hosted Gradio or similar webcam/microphone UI is used instead | Not used: the Space SDK is `static` | `test_readme_front_matter_is_a_static_space` | maintainer | PASS (static) |
| A9 | A Content Security Policy blocks future regressions | None is set. A static Space cannot set response headers (not verified against current Hub documentation); a `<meta http-equiv="Content-Security-Policy">` with `default-src 'self'` would cover script, style, image and connect sources, but it cannot set `frame-ancestors` | none yet | maintainer | OPEN: recommendation, decide and test in the browser before adding |
| A10 | Hub-side behaviour: the Hub wraps Space pages and operates its own cookies and request logging | Outside the artifact's control. The page may say that **the demo** sends nothing; it must not say that visiting the Hub page is private | not examined | owner | OPEN: wording check at publication; compare the live page's Network tab with the local one |
| A11 | Runtime proof of no egress | The checks above are static plus one manual local run. No automated browser test blocks the network and fails on any request | none | maintainer | OPEN: optional, a headless-browser check would turn A2 and A3 from static into observed |

Reproduce the static checks:

```sh
uv run python -m pytest tests/test_hci_hf_lab.py -q
node examples/hci-hf-lab/resolver.test.js
grep -rn -E "https?://" examples/hci-hf-lab/index.html examples/hci-hf-lab/*.css examples/hci-hf-lab/*.js
```

Reproduce the manual check: serve the folder (`python3 -m http.server -d examples/hci-hf-lab 8000`),
open it in a browser with the Network and Console panels open, reload, and use every control.
Expected: only same-origin requests, no permission prompt, no console message. Repeat on the live
Space after publication; requests to the Hub's own domains for the surrounding page are the Hub's.

## B. Dataset card and model repository audit

The only dataset candidate is the synthetic fixture set. No model repository is planned: the
project does not redistribute upstream weights.

| # | Risk | Check | Status |
|---|---|---|---|
| B1 | A licence is granted by an agent rather than the owner | `DATASET_CARD.draft.md` is a labelled draft with no licence granted; the licence for the fixtures is the owner's decision | OPEN: owner decision |
| B2 | The card names a revision, hash or result that was not measured | The draft contains no model revision or measured result; real revisions belong in the provenance inventory (#694) | PASS (static) |
| B3 | Upstream licence or consent mismatch on anything redistributed | Nothing upstream is redistributed. For context, the inventory records that the Systran conversions declare `mit` while the upstream `openai/whisper-*` cards declare `apache-2.0`; that matters only if the project ever re-uploads a conversion | N/A for the Space and fixtures; recorded in #704 |
| B4 | Real human data in a published dataset | Fixtures contain no audio, transcripts, face or eye video, voiceprints, learning-corpus material, EEG or EMG recordings | PASS (static): A6 |
| B5 | Ability to withdraw | Setting a Space or dataset to private, or deleting it, takes it off the public Hub. Copies already fetched, mirrored or indexed by third parties may persist, so treat publication as irreversible in effect and publish nothing that would need withdrawing | OPEN: the unpublish and rollback steps are drafted in [HF_PUBLICATION.md](HF_PUBLICATION.md) section 6, not yet reviewed |
| B6 | Instructions embedded in a third-party model card or file are followed | No third-party model is loaded or fetched by the demo | N/A |

## C. Negative and abuse cases

| Case | Covered by | Status |
|---|---|---|
| Simulated sensitive content in a fixture | `test_validator_rejects_bad_fixtures` rejects malformed or incomplete cases; there is no automated detector for personal data in free text, and the fixtures are hand-written | PASS (static), limited |
| Attempted network call or camera permission added later | The forbidden-identifier test fails the build | PASS (static) |
| An unknown external script or asset added later | `test_index_loads_only_local_assets` | PASS (static) |
| Missing manifest, licence or front matter | `test_readme_front_matter_is_a_static_space`, `test_dataset_card_is_a_labelled_draft` | PASS (static) |
| An overclaim ("mind-reading", clinical, accuracy) reintroduced | Resolver tests cover EEG behaviour; there is no automated scan of page wording | OPEN: review wording at each change |

## D. What this report does not establish

- Nothing was observed on the Hub; the Space is not published.
- The only run-time evidence is one manual local check. The rest is static analysis and tests.
- The Hub's own data practices were not reviewed.
- Accessibility and the resolver's design choices are covered by the prototype's own tests and
  review in #693, not here.

## Cross-references

Epic #692; prototype #693 (draft PR #703); provenance #694 (draft PR #704); fixtures #699;
publication playbook #698 ([HF_PUBLICATION.md](HF_PUBLICATION.md)); egress inventory ADR-019; `AGENTS.md`; direction ADR-030.
