---
title: "The HCI canon behind YazSes: 48 papers"
description: The HCI literature behind an offline dictation tool — why hold-to-talk beats a toggle, why correction cost outweighs word error rate, and what is unmeasured.
---

# The HCI canon behind YazSes

Most writing about voice input is about *models* — word error rate, parameters,
benchmarks. YazSes is a bet that the harder problems are **interaction** problems,
and that most of them were studied and answered before the current generation of
speech models existed.

This page is the reading list behind that bet: the papers that decide how a
dictation tool should behave, what each one establishes, and where it shows up in
the software. It is deliberately opinionated — a reference earns a place only if it
changes a design decision.

!!! info "How these references were checked"

    Every entry was resolved against a live API before it was written down —
    [Crossref](https://www.crossref.org/) for DOIs, [DataCite](https://datacite.org/)
    for arXiv — confirming title, full author list, year and venue. **Fifteen would
    have been wrong from memory**, including one DOI that resolves to an entirely
    different paper. Where we quote a *number*, the grade says whether we read it in
    the source or are relaying a claim.

    **Evidence grade**: *measured* (peer-reviewed measurement), *secondary* (survey,
    review, or position piece), *vendor* (claimed by the maker).

## The argument in eight claims

Underneath all eight is the field's founding move: treat an input channel as something
with a measurable capacity, not a feature list. That is [Fitts](#ref-fitts), and the
tradition of costing an interaction in time and errors that followed it
([Card, Moran & Newell](#ref-card1980)), together with the principle that the
interface should be a directly manipulable representation rather than a language you
have to learn ([Shneiderman](#ref-shneiderman1983)).

### 1. Speech is fast, but correction is what you actually pay

Measured head-to-head, speech entry is roughly three times faster than touchscreen
typing ([Ruan et al.](#ref-ruan) — 153 vs 52 WPM in English). That number is also the
most over-quoted in the field, because dictation is not transcription: it is entry
*interleaved with correction*, and correction consumes a large share of the session
([Karat et al.](#ref-karat)). Repairing an error by switching modality beats
repeating yourself ([Suhm et al.](#ref-suhm)) — which is why YazSes gives you a
command grammar and a keyboard, not just a retry. Trying to do the repair *by voice*
is where dictation gets genuinely awkward, and that difficulty has been documented for
two decades ([Sears et al.](#ref-sears)). None of this is newly noticed: the open
problems in intelligent text entry were catalogued in 2009
([Kristensson & Jameson](#ref-kristensson)) and most are still open.

**The honest limit:** speech competes with composition for the same mental resources
in a way typing does not ([Shneiderman](#ref-shneiderman2000)). Dictation is not a
universal replacement for a keyboard and anyone selling it as one is overselling.

### 2. Hold-to-talk is a mode design, and the mode literature already picked the winner

Recording only while a key is held is the single most consequential decision in
YazSes. It is not a UX preference — it is the finding that **kinaesthetic feedback
prevents mode errors where visual feedback fails** ([Sellen, Kurtenbach &
Buxton](#ref-sellen)). A mode you are physically holding cannot be silently
forgotten; a toggle can, and then it records your meeting. Raskin named this a
**quasimode** ([Raskin](#ref-raskin)), and Buxton's account of input phrasing treats
sustained tension as the natural boundary of one utterance
([Buxton](#ref-buxton)). Where a mode must exist, making it *perceptible* measurably
reduces the errors it causes ([Monk](#ref-monk)) — which is what the tray's colour
states are for.

### 3. The remaining error is a slip, so the system should absorb it

Dictating into a window that accepts no text is a *slip* in Norman's sense
([Norman](#ref-norman1981)) — the error of a competent user, not a confused one. The
design response is not a warning; it is to make the error recoverable. YazSes
detects the absence of a text target and diverts the transcript to the clipboard
rather than typing it into the void. That is the gulf-of-evaluation problem
([Hutchins, Hollan & Norman](#ref-hutchins)) solved with a tray colour.

### 4. Gaze picks a window; it will never pick a character

Webcam gaze lands around 2–4° — centimetres on a screen. That is enough to know
*which window* you mean and never *which character*
([Sugano et al.](#ref-sugano) measured 2.9° with implicit calibration from mouse
clicks; [Zhang et al.](#ref-zhang), [Krafka et al.](#ref-krafka) set the wider
accuracy regime). Two older results fix the design. **The Midas touch problem** —
your eyes are always somewhere, so gaze alone cannot express intent
([Jacob](#ref-jacob)) — is why YazSes commits on the held hotkey and never on dwell
time. **MAGIC pointing** ([Zhai, Morimoto & Ihde](#ref-zhai)) is the division of
labour: gaze selects coarsely, a manual action confirms.

Gaze *as text entry* has a measured ceiling that settles the division of labour:
adjustable-dwell eye typing reached 19.9 WPM after ten sessions of practice
([Majaranta et al.](#ref-majaranta)) — far below speech. So gaze routes, and speech
types.

The ancestor of all of it is [Bolt's Put-That-There](#ref-bolt): speech carries the
verb, pointing carries the referent. YazSes's "close this" is that idea on a $0
sensor, 45 years later.

### 5. Multimodal input is not simultaneous, and it is not always on

Users go multimodal **under cognitive load**, not uniformly
([Oviatt et al.](#ref-oviatt2004)), and the modalities rarely arrive at the same
instant ([Oviatt](#ref-oviatt1999)) — the timing tolerance matters more than the
fusion algorithm ([Kaur et al.](#ref-kaur) measured exactly this for gaze+speech).
Any feature that assumes "look and talk at once" is designing for a user who does
not exist.

### 6. Muscle and brain interfaces are triggers, not typewriters

The best non-invasive result handwrites at 20.9 WPM
([Kaifosh et al., *Nature* 2025](#ref-kaifosh)) — a seventh of speech. Open-vocabulary
silent speech sits near 68% WER ([Gaddy & Klein](#ref-gaddy)). The fast, accurate
paths are all invasive ([Willett et al.](#ref-willett), [Card et al.](#ref-card2024)).
The honest split is therefore **silent commands plus spoken prose** — the muscle
carries the intent to speak, the voice carries the words. The field has understood
itself this way for fifteen years ([Denby et al.](#ref-denby)); what changed recently
is the invasive ceiling, not the wearable one.

### 7. Adaptation that the user cannot see gets rejected

YazSes's personalization loop proposes configuration changes for approval instead of
applying them silently. That follows mixed-initiative principles
([Horvitz](#ref-horvitz)) and a specific finding: users of adaptive interfaces value
**predictability alongside accuracy**, so an unannounced improvement can still make
the interaction worse ([Gajos et al.](#ref-gajos)). Explanations measurably help
([Lim, Dey & Avrahami](#ref-lim)), and setting expectations changes acceptance of an
imperfect system more than raw accuracy does
([Kocielnik et al.](#ref-kocielnik)). The consolidated human-AI interaction guidelines
([Amershi et al.](#ref-amershi)) are the checklist we audit the optional features
against.

### 8. Privacy is a property of the interaction, not a checkbox

The useful frame is **contextual integrity** ([Nissenbaum](#ref-nissenbaum)): privacy
is violated when information flows outside the context that produced it, which is why
an architecture that never transmits is a stronger guarantee than any consent dialog.
This is not only principle — privacy concern is a documented reason people decline
voice assistants, and users are frequently unaware that recordings are retained
([Lau, Zimmerman & Schaub](#ref-lau)). And because voice interfaces are used in
shared, social settings rather than by isolated individuals
([Porcheron et al.](#ref-porcheron)), the people most exposed are often bystanders who
were never asked — the exact situation meeting capture creates.

## What this literature says we have *not* done

The most useful thing about assembling a canon is what it exposes. Three gaps, stated
plainly:

1. **No user study, ever.** YazSes publishes word error rate and latency. It has never
   measured task-level throughput or correction cost with a human participant. In
   Wobbrock & Kientz's taxonomy ([here](#ref-wobbrock2016)) it is an *artifact*
   contribution missing its *empirical* counterpart. The method is not an open
   question — [MacKenzie & Soukoreff](#ref-mackenzie2002) and
   [Soukoreff & MacKenzie](#ref-soukoreff) define how to run and report it, and
   [Vertanen & Kristensson](#ref-vertanen) is the closest comparable system.
2. **The accessibility features are unevaluated with the people they name.** The design
   philosophy YazSes follows here is ability-based design — adapt the system to the
   abilities a person has, rather than requiring them to conform
   ([Wobbrock et al.](#ref-wobbrock2011)). YazSes ships a dysfluency-tolerant mode. [Lea et al.](#ref-lea2023) show how recognition
   fails people who stutter and what fixes it; [SEP-28k](#ref-lea2021) is a public
   dataset that exists today. [Green et al.](#ref-green) show personalized models can
   beat human listeners on short phrases of disordered speech. We have the loop and
   have not run it with affected speakers — and the disability-studies critique of
   assistive technology ([Mankoff, Hayes & Kasnitz](#ref-mankoff)) is the reason that
   has to mean *with*, not *for*.
3. **False-activation rate per working day is unpublished by anyone.** Every trigger
   modality reports accuracy on a benchmark; none reports how many times it fires
   wrongly across a real workday. It is the number that decides whether you can leave
   a thing switched on.

Whichever of these runs first should be **preregistered** — it is a single-shot claim
about our own software, which is exactly the situation where analysis flexibility
quietly becomes a result ([Cockburn, Gutwin & Dix](#ref-cockburn)).

!!! tip "If you want to work on one of these"

    All three are open, scoped, and supervised — see
    [students, researchers & industry](get-involved.md). The third needs no new
    hardware and no lab.

## References

**Evidence grade**: *measured* (peer-reviewed measurement), *secondary* (survey,
review, or position piece), *vendor* (claimed by the maker). Where a specific number
appears above, it is one we have checked at source or relayed from a page that did.

1. <a id="ref-fitts"></a>Fitts, P. M. "The information capacity of the human motor
   system in controlling the amplitude of movement." *Journal of Experimental
   Psychology* 47(6), 1954.
   [doi:10.1037/h0055392](https://doi.org/10.1037/h0055392) — *measured*
2. <a id="ref-card1980"></a>Card, S. K., Moran, T. P., Newell, A. "The keystroke-level
   model for user performance time with interactive systems." *Communications of the
   ACM* 23(7), 1980.
   [doi:10.1145/358886.358895](https://doi.org/10.1145/358886.358895) — *measured*
3. <a id="ref-shneiderman1983"></a>Shneiderman, B. "Direct manipulation: a step beyond
   programming languages." *IEEE Computer* 16(8), 1983.
   [doi:10.1109/MC.1983.1654471](https://doi.org/10.1109/MC.1983.1654471) — *secondary*
4. <a id="ref-hutchins"></a>Hutchins, E. L., Hollan, J. D., Norman, D. A. "Direct
   manipulation interfaces." *Human-Computer Interaction* 1(4), 1985.
   [doi:10.1207/s15327051hci0104_2](https://doi.org/10.1207/s15327051hci0104_2) — *secondary*
5. <a id="ref-norman1981"></a>Norman, D. A. "Categorization of action slips."
   *Psychological Review* 88(1), 1981.
   [doi:10.1037/0033-295X.88.1.1](https://doi.org/10.1037/0033-295X.88.1.1) — *secondary*
6. <a id="ref-sellen"></a>Sellen, A. J., Kurtenbach, G. P., Buxton, W. A. S. "The
   prevention of mode errors through sensory feedback." *Human-Computer Interaction*
   7(2), 1992.
   [doi:10.1207/s15327051hci0702_1](https://doi.org/10.1207/s15327051hci0702_1) — *measured*
7. <a id="ref-raskin"></a>Raskin, J. *The Humane Interface: New Directions for
   Designing Interactive Systems.* Addison-Wesley, 2000. Book excerpt:
   [doi:10.1145/341836.342022](https://doi.org/10.1145/341836.342022) — *secondary*
8. <a id="ref-buxton"></a>Buxton, W. "Chunking and phrasing and the design of
   human-computer dialogues." *Proc. IFIP World Computer Congress*, 1986. Reprinted in
   *Readings in Human-Computer Interaction*, 1995.
   [doi:10.1016/b978-0-08-051574-8.50051-0](https://doi.org/10.1016/b978-0-08-051574-8.50051-0) — *secondary*
9. <a id="ref-monk"></a>Monk, A. "Mode errors: a user-centred analysis and some
   preventative measures using keying-contingent sound." *International Journal of
   Man-Machine Studies* 24(4), 1986.
   [doi:10.1016/S0020-7373(86)80049-9](https://doi.org/10.1016/S0020-7373(86)80049-9) — *measured*
10. <a id="ref-ruan"></a>Ruan, S., Wobbrock, J. O., Liou, K., Ng, A., Landay, J. A.
    "Comparing speech and keyboard text entry for short messages in two languages on
    touchscreen phones." *arXiv:1608.07323*, 2016.
    [arXiv](https://arxiv.org/abs/1608.07323) — *measured* (153 vs 52 WPM, English)
11. <a id="ref-karat"></a>Karat, C.-M., Halverson, C., Horn, D., Karat, J. "Patterns of
    entry and correction in large vocabulary continuous speech recognition systems."
    *CHI '99*, 1999.
    [doi:10.1145/302979.303160](https://doi.org/10.1145/302979.303160) — *measured*
12. <a id="ref-sears"></a>Sears, A., Feng, J., Oseitutu, K., Karat, C.-M. "Hands-free,
    speech-based navigation during dictation: difficulties, consequences, and
    solutions." *Human-Computer Interaction* 18(3), 2003.
    [doi:10.1207/S15327051HCI1803_2](https://doi.org/10.1207/S15327051HCI1803_2) — *measured*
13. <a id="ref-suhm"></a>Suhm, B., Myers, B., Waibel, A. "Multimodal error correction
    for speech user interfaces." *ACM TOCHI* 8(1), 2001.
    [doi:10.1145/371127.371166](https://doi.org/10.1145/371127.371166) — *measured*
14. <a id="ref-shneiderman2000"></a>Shneiderman, B. "The limits of speech recognition."
    *Communications of the ACM* 43(9), 2000.
    [doi:10.1145/348941.348990](https://doi.org/10.1145/348941.348990) — *secondary*
15. <a id="ref-vertanen"></a>Vertanen, K., Kristensson, P. O. "Parakeet: a continuous
    speech recognition system for mobile touch-screen devices." *IUI '09*, 2009.
    [doi:10.1145/1502650.1502685](https://doi.org/10.1145/1502650.1502685) — *measured*
16. <a id="ref-kristensson"></a>Kristensson, P. O., Jameson, A. "Five challenges for
    intelligent text entry methods." *AI Magazine* 30(4), 2009.
    [doi:10.1609/aimag.v30i4.2269](https://doi.org/10.1609/aimag.v30i4.2269) — *secondary*
17. <a id="ref-oviatt1999"></a>Oviatt, S. "Ten myths of multimodal interaction."
    *Communications of the ACM* 42(11), 1999.
    [doi:10.1145/319382.319398](https://doi.org/10.1145/319382.319398) — *secondary*
18. <a id="ref-oviatt2004"></a>Oviatt, S., Coulston, R., Lunsford, R. "When do we
    interact multimodally? Cognitive load and multimodal communication patterns."
    *ICMI '04*, 2004.
    [doi:10.1145/1027933.1027957](https://doi.org/10.1145/1027933.1027957) — *measured*
19. <a id="ref-bolt"></a>Bolt, R. A. "Put-that-there: voice and gesture at the graphics
    interface." *SIGGRAPH '80*, 1980.
    [doi:10.1145/800250.807503](https://doi.org/10.1145/800250.807503) — *secondary*
20. <a id="ref-kaur"></a>Kaur, M. et al. "Where is 'it'? Event synchronization in
    gaze-speech input systems." *ICMI '03*, 2003.
    [doi:10.1145/958432.958463](https://doi.org/10.1145/958432.958463) — *measured*
21. <a id="ref-jacob"></a>Jacob, R. J. K. "What you look at is what you get: eye
    movement-based interaction techniques." *CHI '90*, 1990.
    [doi:10.1145/97243.97246](https://doi.org/10.1145/97243.97246) — *measured*
22. <a id="ref-zhai"></a>Zhai, S., Morimoto, C., Ihde, S. "Manual and gaze input
    cascaded (MAGIC) pointing." *CHI '99*, 1999.
    [doi:10.1145/302979.303053](https://doi.org/10.1145/302979.303053) — *measured*
23. <a id="ref-majaranta"></a>Majaranta, P., Ahola, U.-K., Špakov, O. "Fast gaze typing
    with an adjustable dwell time." *CHI '09*, 2009.
    [doi:10.1145/1518701.1518758](https://doi.org/10.1145/1518701.1518758) — *measured*
    (6.9 → 19.9 WPM over ten sessions)
24. <a id="ref-sugano"></a>Sugano, Y., Matsushita, Y., Sato, Y., Koike, H.
    "Appearance-based gaze estimation with online calibration from mouse operations."
    *IEEE Transactions on Human-Machine Systems* 45(6), 2015.
    [doi:10.1109/THMS.2015.2400434](https://doi.org/10.1109/THMS.2015.2400434) —
    *measured* (2.9° with no explicit calibration)
25. <a id="ref-zhang"></a>Zhang, X., Sugano, Y., Fritz, M., Bulling, A.
    "Appearance-based gaze estimation in the wild." *arXiv:1504.02863*, 2015.
    [arXiv](https://arxiv.org/abs/1504.02863) — *measured*
26. <a id="ref-krafka"></a>Krafka, K. et al. "Eye tracking for everyone."
    *arXiv:1606.05814*, 2016. [arXiv](https://arxiv.org/abs/1606.05814) — *measured*
27. <a id="ref-kaifosh"></a>Kaifosh, P., Reardon, T. R. et al. "A generic non-invasive
    neuromotor interface for human-computer interaction." *Nature*, 2025.
    [doi:10.1038/s41586-025-09255-w](https://doi.org/10.1038/s41586-025-09255-w) —
    *measured* (20.9 WPM handwriting)
28. <a id="ref-gaddy"></a>Gaddy, D., Klein, D. "Digital voicing of silent speech."
    *arXiv:2010.02960*, 2020. [arXiv](https://arxiv.org/abs/2010.02960) — *measured*
    (open-vocabulary silent speech ≈68% WER)
29. <a id="ref-willett"></a>Willett, F. R. et al. "A high-performance speech
    neuroprosthesis." *Nature* 620, 2023.
    [doi:10.1038/s41586-023-06377-x](https://doi.org/10.1038/s41586-023-06377-x) —
    *measured* (invasive; 62 WPM, 23.8% WER at 125k words)
30. <a id="ref-card2024"></a>Card, N. S. et al. "An accurate and rapidly calibrating
    speech neuroprosthesis." *New England Journal of Medicine*, 2024.
    [doi:10.1056/NEJMoa2314132](https://doi.org/10.1056/NEJMoa2314132) — *measured*
    (invasive; 2.5% WER)
31. <a id="ref-denby"></a>Denby, B. et al. "Silent speech interfaces." *Speech
    Communication* 52(4), 2010.
    [doi:10.1016/j.specom.2009.08.002](https://doi.org/10.1016/j.specom.2009.08.002) — *secondary*
32. <a id="ref-wobbrock2011"></a>Wobbrock, J. O., Kane, S. K., Gajos, K. Z., Harada, S.,
    Froehlich, J. "Ability-based design: concept, principles and examples." *ACM
    TACCESS* 3(3), 2011.
    [doi:10.1145/1952383.1952384](https://doi.org/10.1145/1952383.1952384) — *secondary*
33. <a id="ref-green"></a>Green, J. R. et al. "Automatic speech recognition of disordered
    speech: personalized models outperforming human listeners on short phrases."
    *Interspeech 2021*.
    [doi:10.21437/Interspeech.2021-1384](https://doi.org/10.21437/Interspeech.2021-1384) — *measured*
34. <a id="ref-lea2023"></a>Lea, C. et al. "From user perceptions to technical
    improvement: enabling people who stutter to better use speech recognition."
    *CHI '23*, 2023.
    [doi:10.1145/3544548.3581224](https://doi.org/10.1145/3544548.3581224) — *measured*
35. <a id="ref-lea2021"></a>Lea, C., Mitra, V., Joshi, A., Kajarekar, S., Bigham, J. P.
    "SEP-28k: a dataset for stuttering event detection from podcasts with people who
    stutter." *arXiv:2102.12394*, 2021.
    [arXiv](https://arxiv.org/abs/2102.12394) — *measured*
36. <a id="ref-mankoff"></a>Mankoff, J., Hayes, G. R., Kasnitz, D. "Disability studies
    as a source of critical inquiry for the field of assistive technology."
    *ASSETS '10*, 2010.
    [doi:10.1145/1878803.1878807](https://doi.org/10.1145/1878803.1878807) — *secondary*
37. <a id="ref-horvitz"></a>Horvitz, E. "Principles of mixed-initiative user
    interfaces." *CHI '99*, 1999.
    [doi:10.1145/302979.303030](https://doi.org/10.1145/302979.303030) — *secondary*
38. <a id="ref-gajos"></a>Gajos, K. Z., Everitt, K., Tan, D. S., Czerwinski, M., Weld,
    D. S. "Predictability and accuracy in adaptive user interfaces." *CHI '08*, 2008.
    [doi:10.1145/1357054.1357252](https://doi.org/10.1145/1357054.1357252) — *measured*
39. <a id="ref-lim"></a>Lim, B. Y., Dey, A. K., Avrahami, D. "Why and why not
    explanations improve the intelligibility of context-aware intelligent systems."
    *CHI '09*, 2009.
    [doi:10.1145/1518701.1519023](https://doi.org/10.1145/1518701.1519023) — *measured*
40. <a id="ref-kocielnik"></a>Kocielnik, R., Amershi, S., Bennett, P. N. "Will you
    accept an imperfect AI? Exploring designs for adjusting end-user expectations of AI
    systems." *CHI '19*, 2019.
    [doi:10.1145/3290605.3300641](https://doi.org/10.1145/3290605.3300641) — *measured*
41. <a id="ref-amershi"></a>Amershi, S. et al. "Guidelines for human-AI interaction."
    *CHI '19*, 2019.
    [doi:10.1145/3290605.3300233](https://doi.org/10.1145/3290605.3300233) — *secondary*
42. <a id="ref-nissenbaum"></a>Nissenbaum, H. *Privacy in Context: Technology, Policy,
    and the Integrity of Social Life.* Stanford University Press, 2010.
    [doi:10.1515/9780804772891](https://doi.org/10.1515/9780804772891) — *secondary*
43. <a id="ref-lau"></a>Lau, J., Zimmerman, B., Schaub, F. "Alexa, are you listening?
    Privacy perceptions, concerns and privacy-seeking behaviors with smart speakers."
    *Proc. ACM Human-Computer Interaction* 2(CSCW), 2018.
    [doi:10.1145/3274371](https://doi.org/10.1145/3274371) — *measured*
44. <a id="ref-porcheron"></a>Porcheron, M., Fischer, J. E., Reeves, S., Sharples, S.
    "Voice interfaces in everyday life." *CHI '18*, 2018.
    [doi:10.1145/3173574.3174214](https://doi.org/10.1145/3173574.3174214) — *measured*
45. <a id="ref-mackenzie2002"></a>MacKenzie, I. S., Soukoreff, R. W. "Text entry for
    mobile computing: models and methods, theory and practice." *Human-Computer
    Interaction* 17(2–3), 2002. doi:10.1207/S15327051HCI172&3_2 — *secondary*
46. <a id="ref-soukoreff"></a>Soukoreff, R. W., MacKenzie, I. S. "Metrics for text entry
    research: an evaluation of MSD and KSPC, and a new unified error metric."
    *CHI '03*, 2003.
    [doi:10.1145/642611.642632](https://doi.org/10.1145/642611.642632) — *secondary*
47. <a id="ref-wobbrock2016"></a>Wobbrock, J. O., Kientz, J. A. "Research contributions
    in human-computer interaction." *Interactions* 23(3), 2016.
    [doi:10.1145/2907069](https://doi.org/10.1145/2907069) — *secondary*
48. <a id="ref-cockburn"></a>Cockburn, A., Gutwin, C., Dix, A. "HARK no more: on the
    preregistration of CHI experiments." *CHI '18*, 2018.
    [doi:10.1145/3173574.3173715](https://doi.org/10.1145/3173574.3173715) — *secondary*
