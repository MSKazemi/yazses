---
title: Ten open questions in voice-first HCI
description: Ten measurable research directions for offline voice input — the method, the code seam each touches, and what a result would establish. Three need no new code.
---

# Ten open questions

This is what we think is worth measuring next — and what we are honest about not having
measured yet.

Each direction is stated as a **claim to test**, not a feature to build. That is
deliberate. YazSes has more features than evidence, and the scarce resource in an
offline-voice project run by one maintainer is *measurement*, not ideas. Everything below
names the method, the literature that fixes it, and what a result would actually say.

They are ordered by **evidence produced per unit of effort**. Directions 1, 2 and 9 need
no new code at all.

!!! tip "These are open, and they are supervised"

    Several are thesis- or course-sized. If you want to take one, open a
    [Discussion](https://github.com/MSKazemi/yazses/discussions) — scoping a variant for
    your semester is a conversation away. See
    [students, researchers & industry](get-involved.md). Full internal write-up with code
    seams: [`design/research/`](https://github.com/MSKazemi/yazses/blob/main/design/research/2026-08-11-hci-research-agenda.md).

---


!!! note "Every question below has an issue"

    The question is stated here; the issue is where you say you are working on it.
    Comment before you start — two groups running the same study without knowing is the
    most expensive duplicate this project could produce. A pilot, or just the measurement
    harness, is a real contribution and unblocks whoever runs the full version.

## 1. The first user study — throughput *and* correction cost

**Claim this question:** [#251](https://github.com/MSKazemi/yazses/issues/251)

**Claim:** for composed prose on a desktop, hold-to-talk dictation beats typing on net
words-per-minute *after correction cost is subtracted* — and by a smaller margin than the
3× that gets quoted.

The often-cited 3× speech advantage ([Ruan et al.](#ref-ruan)) was measured on **short
messages on touchscreen phones** — a different task against a much weaker typing baseline,
and it does not carry correction cost. [Karat et al.](#ref-karat) showed correction
episodes consume a large share of a dictation session. Nobody has published the
desktop-daemon equivalent.

**The method is settled, not open:** [MacKenzie & Soukoreff](#ref-mackenzie2002) give the
protocol, [Soukoreff & MacKenzie](#ref-soukoreff) the unified error metric,
[Vertanen & Kristensson](#ref-vertanen2011) a realistic phrase set from genuine email, and
[Kristensson & Vertanen](#ref-kristensson2012) the warning that the phrase set itself
changes the result — so the comparison must be pre-specified, and
[preregistered](#ref-cockburn).

**Binding constraint:** participants. Even n=8 within-subjects would be the first such
number published for an offline dictation daemon.

## 2. False-activation rate across a real working day

**Claim this question:** [#140](https://github.com/MSKazemi/yazses/issues/140) · [#106](https://github.com/MSKazemi/yazses/issues/106)

**Claim:** a hold-to-talk trigger produces under *N* unintended activations per eight-hour
day, and every competing modality (wake word, EMG squeeze, gaze dwell) produces more.

Benchmarks report accuracy on curated sets. The number that decides whether you can leave
something switched on is how often it fires when you did not mean it — and **no paper in
the silent-input literature reports it.** Even the landmark neuromotor result
([Kaifosh et al.](#ref-kaifosh)) omits latency and false-activation rate. YazSes is
already instrumented and already running on a real machine doing real work.

## 3. An activation seam that carries intent, not just onset

**Claim this question:** [#252](https://github.com/MSKazemi/yazses/issues/252)

**Claim:** a source protocol that emits an *intent* — a word, a gesture class, a
confidence — rather than "started"/"stopped" makes every published silent-speech and
neuromotor decoder pluggable without a bespoke adapter.

The mismatch is architectural: EMG and neural decoders in the literature all produce a
*word*, while the hotkey interface they must plug into accepts two edge events.
[Buxton](#ref-buxton1983) on the lexical and pragmatic structure of input is the right
vocabulary for what a source is allowed to say.

## 4. A confirmation model proportional to the error rate

**Claim this question:** [#253](https://github.com/MSKazemi/yazses/issues/253)

**Claim:** a gate that triggers on *low decoder confidence only* costs less total time
than either always-confirming or never-confirming, at the 3–4% error rate real command
channels exhibit.

Closed-vocabulary silent input runs at 96–97% — about one command in thirty is wrong.
Unacceptable for a destructive action; noise for dictation. The design literature says an
interface should *absorb* recognition error rather than pretend to eliminate it
([Oviatt](#ref-oviatt2000)), that [mixed-initiative principles](#ref-horvitz) govern when
to act versus ask, and — most usefully — that **setting expectations changes acceptance of
an imperfect system more than accuracy does** ([Kocielnik et al.](#ref-kocielnik)).

## 5. Make uncertainty visible

**Claim this question:** [#254](https://github.com/MSKazemi/yazses/issues/254)

**Claim:** rendering per-word recognition confidence at injection time reduces correction
time versus uniform text, without increasing perceived effort.

This is the intelligibility result applied to dictation: why/why-not explanations improve
understanding of an intelligent system ([Lim, Dey & Avrahami](#ref-lim)), and
accountability requires exposing what the system is unsure of
([Bellotti & Edwards](#ref-bellotti)).

**Honest risk:** confidence from a Whisper-family decoder is poorly calibrated. The study
may find the signal is not good enough to show — which is itself a result worth publishing.

## 6. Evaluate with dysfluent and dysarthric speakers

**Claim this question:** [#255](https://github.com/MSKazemi/yazses/issues/255)

**Claim:** the shipped dysfluency-tolerant mode measurably improves usable transcription
for people who stutter — or it does not, and we say so.

YazSes ships a mode named for a population it has not been tested with. This is the
highest-social-impact direction on the list and the method is fully specified:
[Lea et al.](#ref-lea2023) trace how recognition fails people who stutter and what
improves it, [SEP-28k](#ref-lea2021) is a **public dataset that exists today** so the work
can begin without recruitment, and [Green et al.](#ref-green) establish that personalized
models can outperform human listeners on short phrases of disordered speech.

**Non-negotiable:** the disability-studies critique of assistive technology
([Mankoff, Hayes & Kasnitz](#ref-mankoff)) is why this must be done *with*, not *for*. A
benchmark number is a start, not the finish.

## 7. Put-That-There on a $0 sensor

**Claim this question:** [#104](https://github.com/MSKazemi/yazses/issues/104)

**Claim:** at webcam-grade accuracy (2–4°), demonstrative commands — "close this", "focus
that window" — succeed on a real multi-window desktop often enough to justify the
confirmation gate they require.

[Bolt's Put-That-There](#ref-bolt) is 45 years old and ran on custom hardware. The
constraints are known: [the Midas touch problem](#ref-jacob) is why a held key, not dwell
time, commits; [MAGIC pointing](#ref-zhai) is the division of labour. The open parameter
is *when* to sample gaze relative to speech onset — which
[Kaur et al.](#ref-kaur) measured for gaze-speech systems and nobody has re-measured on
commodity webcams.

## 8. Adaptation the user can see and steer

**Claim this question:** [#256](https://github.com/MSKazemi/yazses/issues/256)

**Claim:** propose-and-approve tuning produces higher user trust than silent adaptation
**at equal or slightly worse recognition accuracy** — i.e. the two outcomes disagree, and
predictability wins.

[Gajos et al.](#ref-gajos) found users of adaptive interfaces value predictability
alongside accuracy, so an unannounced improvement can still degrade the interaction.
YazSes already implements the arm the literature predicts wins; the comparison has not
been run.

## 9. The wrong-target slip as an error-prevention study

**Claim this question:** [#257](https://github.com/MSKazemi/yazses/issues/257)

**Claim:** dictating into a window that accepts no text happens at a measurable rate in
ordinary desktop use, and diverting to the clipboard recovers it at lower cost than
warning.

Nearly free: this is [Norman's slips](#ref-norman1981) with a shipped intervention and
**three policies already in the config** to compare. [Hutchins, Hollan & Norman](#ref-hutchins)
supply the framing, and [Sellen et al.](#ref-sellen) explain why a tray colour is a weaker
signal than a held key.

## 10. Code-switching as an equity question

**Claim this question:** [#258](https://github.com/MSKazemi/yazses/issues/258)

**Claim:** for bilingual users, within-utterance code-switching — not accent — is the
dominant source of dictation failure, and *which language pairs matter* has never been
asked of dictation users.

Whisper decodes one language per 30-second window, so a code-switched sentence is
structurally mis-served. Adapters help but need per-pair training, which means somebody
chooses which pairs exist. That choice decides who the tool serves —
[ability-based design](#ref-wobbrock2011) says adapt to the practices people actually
have, and bilingual speakers code-switch as a matter of course.

**Cheapest first step:** ask. A Discussion costs nothing and produces the prioritisation
the training work would otherwise guess.

---

## Where YazSes stands

In [Wobbrock and Kientz's taxonomy](#ref-wobbrock2016), YazSes is today an **artifact**
contribution: a working system with a measured recogniser. The **empirical** contribution
— what happens when people use it — is the one still outstanding, and it is the reason
directions 1, 2 and 6 sit at the top of this list.

The reading behind all of it: [the HCI canon behind YazSes](hci-canon.md).

## References

**Evidence grade**: *measured* (peer-reviewed measurement), *secondary* (survey, review,
or position piece). Every entry resolved against Crossref or DataCite.

1. <a id="ref-ruan"></a>Ruan, S., Wobbrock, J. O., Liou, K., Ng, A., Landay, J. A.
   "Comparing speech and keyboard text entry for short messages in two languages on
   touchscreen phones." *arXiv:1608.07323*, 2016.
   [arXiv](https://arxiv.org/abs/1608.07323) — *measured*
2. <a id="ref-karat"></a>Karat, C.-M., Halverson, C., Horn, D., Karat, J. "Patterns of
   entry and correction in large vocabulary continuous speech recognition systems."
   *CHI '99*, 1999.
   [doi:10.1145/302979.303160](https://doi.org/10.1145/302979.303160) — *measured*
3. <a id="ref-mackenzie2002"></a>MacKenzie, I. S., Soukoreff, R. W. "Text entry for mobile
   computing: models and methods, theory and practice." *Human-Computer Interaction*
   17(2–3), 2002. doi:10.1207/S15327051HCI172&3_2 — *secondary*
4. <a id="ref-soukoreff"></a>Soukoreff, R. W., MacKenzie, I. S. "Metrics for text entry
   research: an evaluation of MSD and KSPC, and a new unified error metric." *CHI '03*,
   2003. [doi:10.1145/642611.642632](https://doi.org/10.1145/642611.642632) — *secondary*
5. <a id="ref-vertanen2011"></a>Vertanen, K., Kristensson, P. O. "A versatile dataset for
   text entry evaluations based on genuine mobile emails." *MobileHCI '11*, 2011.
   [doi:10.1145/2037373.2037418](https://doi.org/10.1145/2037373.2037418) — *measured*
6. <a id="ref-kristensson2012"></a>Kristensson, P. O., Vertanen, K. "Performance
   comparisons of phrase sets and presentation styles for text entry evaluations."
   *IUI '12*, 2012.
   [doi:10.1145/2166966.2166972](https://doi.org/10.1145/2166966.2166972) — *measured*
7. <a id="ref-cockburn"></a>Cockburn, A., Gutwin, C., Dix, A. "HARK no more: on the
   preregistration of CHI experiments." *CHI '18*, 2018.
   [doi:10.1145/3173574.3173715](https://doi.org/10.1145/3173574.3173715) — *secondary*
8. <a id="ref-kaifosh"></a>Kaifosh, P., Reardon, T. R. et al. "A generic non-invasive
   neuromotor interface for human-computer interaction." *Nature*, 2025.
   [doi:10.1038/s41586-025-09255-w](https://doi.org/10.1038/s41586-025-09255-w) —
   *measured*
9. <a id="ref-buxton1983"></a>Buxton, W. "Lexical and pragmatic considerations of input
   structures." *ACM SIGGRAPH Computer Graphics* 17(1), 1983.
   [doi:10.1145/988584.988586](https://doi.org/10.1145/988584.988586) — *secondary*
10. <a id="ref-oviatt2000"></a>Oviatt, S. "Taming recognition errors with a multimodal
    interface." *Communications of the ACM* 43(9), 2000.
    [doi:10.1145/348941.348979](https://doi.org/10.1145/348941.348979) — *secondary*
11. <a id="ref-horvitz"></a>Horvitz, E. "Principles of mixed-initiative user interfaces."
    *CHI '99*, 1999.
    [doi:10.1145/302979.303030](https://doi.org/10.1145/302979.303030) — *secondary*
12. <a id="ref-kocielnik"></a>Kocielnik, R., Amershi, S., Bennett, P. N. "Will you accept
    an imperfect AI? Exploring designs for adjusting end-user expectations of AI systems."
    *CHI '19*, 2019.
    [doi:10.1145/3290605.3300641](https://doi.org/10.1145/3290605.3300641) — *measured*
13. <a id="ref-lim"></a>Lim, B. Y., Dey, A. K., Avrahami, D. "Why and why not explanations
    improve the intelligibility of context-aware intelligent systems." *CHI '09*, 2009.
    [doi:10.1145/1518701.1519023](https://doi.org/10.1145/1518701.1519023) — *measured*
14. <a id="ref-bellotti"></a>Bellotti, V., Edwards, K. "Intelligibility and
    accountability: human considerations in context-aware systems." *Human-Computer
    Interaction* 16(2–4), 2001.
    [doi:10.1207/S15327051HCI16234_05](https://doi.org/10.1207/S15327051HCI16234_05) —
    *secondary*
15. <a id="ref-lea2023"></a>Lea, C. et al. "From user perceptions to technical
    improvement: enabling people who stutter to better use speech recognition."
    *CHI '23*, 2023.
    [doi:10.1145/3544548.3581224](https://doi.org/10.1145/3544548.3581224) — *measured*
16. <a id="ref-lea2021"></a>Lea, C., Mitra, V., Joshi, A., Kajarekar, S., Bigham, J. P.
    "SEP-28k: a dataset for stuttering event detection from podcasts with people who
    stutter." *arXiv:2102.12394*, 2021.
    [arXiv](https://arxiv.org/abs/2102.12394) — *measured*
17. <a id="ref-green"></a>Green, J. R. et al. "Automatic speech recognition of disordered
    speech: personalized models outperforming human listeners on short phrases."
    *Interspeech 2021*.
    [doi:10.21437/Interspeech.2021-1384](https://doi.org/10.21437/Interspeech.2021-1384) —
    *measured*
18. <a id="ref-mankoff"></a>Mankoff, J., Hayes, G. R., Kasnitz, D. "Disability studies as
    a source of critical inquiry for the field of assistive technology." *ASSETS '10*,
    2010. [doi:10.1145/1878803.1878807](https://doi.org/10.1145/1878803.1878807) —
    *secondary*
19. <a id="ref-bolt"></a>Bolt, R. A. "Put-that-there: voice and gesture at the graphics
    interface." *SIGGRAPH '80*, 1980.
    [doi:10.1145/800250.807503](https://doi.org/10.1145/800250.807503) — *secondary*
20. <a id="ref-jacob"></a>Jacob, R. J. K. "What you look at is what you get: eye
    movement-based interaction techniques." *CHI '90*, 1990.
    [doi:10.1145/97243.97246](https://doi.org/10.1145/97243.97246) — *measured*
21. <a id="ref-zhai"></a>Zhai, S., Morimoto, C., Ihde, S. "Manual and gaze input cascaded
    (MAGIC) pointing." *CHI '99*, 1999.
    [doi:10.1145/302979.303053](https://doi.org/10.1145/302979.303053) — *measured*
22. <a id="ref-kaur"></a>Kaur, M. et al. "Where is 'it'? Event synchronization in
    gaze-speech input systems." *ICMI '03*, 2003.
    [doi:10.1145/958432.958463](https://doi.org/10.1145/958432.958463) — *measured*
23. <a id="ref-gajos"></a>Gajos, K. Z., Everitt, K., Tan, D. S., Czerwinski, M., Weld,
    D. S. "Predictability and accuracy in adaptive user interfaces." *CHI '08*, 2008.
    [doi:10.1145/1357054.1357252](https://doi.org/10.1145/1357054.1357252) — *measured*
24. <a id="ref-norman1981"></a>Norman, D. A. "Categorization of action slips."
    *Psychological Review* 88(1), 1981.
    [doi:10.1037/0033-295X.88.1.1](https://doi.org/10.1037/0033-295X.88.1.1) — *secondary*
25. <a id="ref-hutchins"></a>Hutchins, E. L., Hollan, J. D., Norman, D. A. "Direct
    manipulation interfaces." *Human-Computer Interaction* 1(4), 1985.
    [doi:10.1207/s15327051hci0104_2](https://doi.org/10.1207/s15327051hci0104_2) —
    *secondary*
26. <a id="ref-sellen"></a>Sellen, A. J., Kurtenbach, G. P., Buxton, W. A. S. "The
    prevention of mode errors through sensory feedback." *Human-Computer Interaction*
    7(2), 1992.
    [doi:10.1207/s15327051hci0702_1](https://doi.org/10.1207/s15327051hci0702_1) —
    *measured*
27. <a id="ref-wobbrock2011"></a>Wobbrock, J. O., Kane, S. K., Gajos, K. Z., Harada, S.,
    Froehlich, J. "Ability-based design: concept, principles and examples." *ACM TACCESS*
    3(3), 2011.
    [doi:10.1145/1952383.1952384](https://doi.org/10.1145/1952383.1952384) — *secondary*
28. <a id="ref-wobbrock2016"></a>Wobbrock, J. O., Kientz, J. A. "Research contributions in
    human-computer interaction." *Interactions* 23(3), 2016.
    [doi:10.1145/2907069](https://doi.org/10.1145/2907069) — *secondary*
