# Incident and spam response

For the failure modes a contributor drive brings that ordinary maintenance does not.
[`SECURITY.md`](../SECURITY.md) covers vulnerabilities and
[`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) covers behaviour; this covers the rest.

**The governing bias: act on the contribution, not the person.** Almost every "bad" first
pull request is a misunderstanding, a language barrier, or a badly written task — ours, not
theirs. Reserve the language of bad faith for evidence of bad faith, because using it on
someone who was merely confused ends their involvement in open source, not just here.

## Fabricated evidence

A compatibility report, benchmark or hardware measurement that was not observed — usually
an agent generating a plausible-looking record nobody ran.

**Signs:** an environment key that does not exist (a distro/desktop pairing that is not
shipped), `yazses doctor` output with impossible version combinations, numbers with no
variance across "different" machines, identical prose across several submissions.

**Response:** ask one neutral question first — "which machine did you run this on?" Genuine
contributors answer immediately and specifically. Do not accuse in public. If the answer
confirms it was generated, close the PR with the reason stated plainly and without insult,
and remove any merged record it produced: **an unverifiable record in the corpus is worse
than an absent one**, because product decisions get made on it.

## Plagiarised contributions

Code or prose copied from another project without attribution or a compatible licence.

**Response:** do not merge, and if already merged, revert promptly — this is a licensing
exposure for every downstream user, not a style problem. State the specific source. Where
the underlying work is genuinely useful and the licence permits it, help them attribute it
properly rather than discarding the contribution.

## Pull-request floods and reward gaming

Many low-value PRs from one account or a coordinated group — typically whitespace, typo, or
list-of-names changes timed around an event.

**Response:** close them with a link to the task inventory, in one batch, with one
explanation. Do not merge a valueless change to be kind; it teaches that the bar is nothing
and the next hundred arrive. If the volume is coordinated, report it to GitHub — this is
what their Acceptable Use Policies exist for and it is not a judgement call you have to make
alone. Then **pause promotion** until the queue drains
(`uv run python scripts/campaign_stats.py` prints the stop-rule status).

Never run a leaderboard or prize by PR count. It manufactures exactly this.

## Coordinated inauthentic activity

Sockpuppet accounts, purchased stars, star-for-star rings, or mass unsolicited promotion of
YazSes by someone claiming to help.

**Response:** report to GitHub; do not retaliate or engage publicly. Ask the person to stop
if they are identifiable and appear well-meaning — some of this is enthusiasm, not malice.
**Never reciprocate**, even once. The project's own rule is absolute: no bought stars, no
star-for-star, no fake accounts, no gaming Trending. A single verifiable instance would
discredit every real number the project has.

## A contributor's data leaked into the repository

Someone pastes a home path, hostname, email or token into a PR or a merged file.

**Response, in order:**

1. If it is a credential, tell them to **revoke it first** — removal from git does not
   un-leak it, and forks and caches persist.
2. Remove it from the current tree immediately.
3. Rewriting published history is destructive and needs the owner's explicit decision;
   for a low-sensitivity path or hostname it is usually not warranted.
4. Fix the class: if preflight missed it, add the pattern to `PERSONAL_DATA` in
   `scripts/campaign_preflight.py` with a test, so the next one is caught automatically.

Never quote the leaked value in a public comment while asking them to remove it.

## Harassment

Follow [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md). Two additions that matter during a
campaign: the target decides how public the response is, never the maintainer's
convenience; and a reviewer receiving abuse is removed from that thread immediately and
without having to ask.

## When to pause everything

Stop promotion, publicly and without apology, if the review queue exceeds 25, if median
first response passes 48 hours, if more than 30% of a cohort is submitting unusable work,
or if any incident above is ongoing. A quiet week costs far less than a queue of people
who concluded nobody was listening.

## What to write down

Keep a private note per incident: what happened, what was done, what changed so it cannot
recur. Publish only aggregate counts. Naming individuals in a public postmortem invites a
pile-on and deters people who were never involved.
