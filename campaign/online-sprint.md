# Running an online contribution sprint

A 90-minute video call where each person lands one merged contribution to YazSes. No venue,
no travel, no catering, no date that only suits one city.

[`sprint-kit.md`](sprint-kit.md) is the in-person version. Everything there about choosing
tasks, the agenda and the follow-up still applies; this covers what changes when the room is
a call — and why, for this project specifically, online is the better format rather than the
fallback.

## Why online is genuinely better here

The two largest task families need exactly what a single room cannot supply:

- **297 compatibility tasks** need Fedora, Arch, openSUSE, macOS on Apple silicon, Windows on
  ARM, a Raspberry Pi. A room in one city is largely one distro and one desktop. A call is
  whatever twenty people happen to own, which is the point — nobody can test these centrally,
  and that is the entire reason the tasks exist.
- **184 localization tasks** need native speakers of 23 languages. One city gives you one or
  two. A call given a timezone gives you a region.

So do not treat this as second best. For a project whose missing evidence *is* environmental
diversity, remote attendance is the feature.

## What you need

| Role | How many | Doing what |
|---|---|---|
| Host | 1 (you) | Keeps time, answers questions in the call |
| Reviewer | 1 per ~8 people | Reviews **during** the session, not after |
| Helper | 1 per ~10 people | Watches the chat for people stuck and silent |

**Do not run it without a reviewer.** Twenty PRs nobody looks at for a week teaches twenty
people that contributing here means waiting. If it is only you, cap attendance at eight.

## Platform

**Jitsi Meet** ([meet.jit.si](https://meet.jit.si)) — no account, no install, open source,
and consistent with a project whose whole claim is that your data stays yours. Asking people
to create an account to help you is a real drop-off, and recommending a telemetry-heavy
platform for a privacy tool is a bad look people will notice.

Fallbacks: Google Meet if the group already lives there; Discord if the community does — its
screen-share and persistent text channel are genuinely good for this, and the channel keeps
working after the call ends.

**Have a text channel as well as the call.** Most people will not unmute to say they are
stuck. They will type it, or say nothing at all — which is why the helper watches chat.

## Timezone: run it twice, not once

One session cannot serve India and Brazil. Pick a region per session:

| Slot (UTC) | Serves | Good for |
|---|---|---|
| 05:00–07:00 | India, SE Asia | Localization (`hi`, `bn`, `ta`, `te`, `id`, `vi`), Linux compatibility |
| 13:00–15:00 | Europe, Africa, Middle East | Broad mix; the largest Linux desktop population |
| 17:00–19:00 | Americas | macOS/Windows compatibility, app configs |
| 12:00–14:00 Sat | China (evening) | `zh-CN` localization |

Announce in **UTC with a local-time link**, not "8pm my time".

## What changes from the in-person agenda

| Time | In a room | On a call |
|---|---|---|
| 0:00–0:10 | Context and safety | Same, plus: **paste the task list link in chat immediately** — half of them are on a phone until they find it |
| 0:10–0:20 | Pick and claim | Same, but claims go in the **text channel** so nobody doubles up silently |
| 0:20–0:30 | Environment | The big one. Screen-share the Codespaces path once, for everyone at once |
| 0:30–1:00 | Work | **Mute everyone and keep the call open.** Silence with the room still there is the thing that makes this work. Helper watches chat |
| 1:00–1:12 | Open PRs | Same; paste PR links into the channel so the reviewer has a queue |
| 1:12–1:25 | Review and fix | Reviewer screen-shares one review out loud — people learn more from watching one than from receiving three |
| 1:25–1:30 | Close | Say what merged, by name |

The 0:30–1:00 block is the session. Everything else exists to protect it.

## The three online-specific failures

1. **Silent stalling.** In a room you see a frustrated face; on a call you see a muted tile.
   Ask by name at the 15-minute mark — "how's it going, anyone want a screen-share?" — rather
   than waiting for hands.
2. **The environment step eats the session.** `uv sync` fails on Linux without a C compiler
   (`evdev` publishes no wheels). Put `sudo apt install build-essential python3-dev` in the
   pre-message *and* on a slide, and push anyone still stuck at 0:30 to Codespaces rather
   than debugging their laptop while eighteen people wait.
3. **The call ends and the PRs are orphaned.** Nobody is standing next to them afterwards.
   The text channel must outlive the call, and someone must answer in it for 72 hours.

## Send this 48 hours before

> **YazSes contribution sprint — [date], [time] UTC, 90 minutes**
>
> We'll each make one real, merged improvement to an offline voice-dictation tool. Not a
> tutorial, not a toy PR — actual work the project needs.
>
> **Bring:** a laptop and a GitHub account. That's genuinely it. Most tasks are done in the
> browser; the ones that need a machine will be matched to whatever you already have.
>
> **Especially useful if you have:** a distro that isn't Ubuntu, a Mac, a Windows machine,
> unusual hardware, or a language other than English. Nobody can test those centrally, which
> is exactly why they're valuable.
>
> If you want to set up in advance (optional):
> <https://github.com/MSKazemi/yazses/blob/main/CONTRIBUTING.md>. On Linux you need a C
> compiler (`build-essential`); on macOS and Windows you need nothing.
>
> Using a coding agent is welcome — you stay the author and you're expected to read what it
> writes.
>
> Call link: [Jitsi/Meet link] · Chat: [channel link]

## The async variant: a sprint week

If a live call cannot be scheduled across the timezones you want, run the same thing over
five days. It converts worse than a live session — nobody is beside you when you stall — but
it reaches people no single hour can.

- **Monday:** post the task list and the rules; open a dedicated channel or discussion.
- **Monday–Thursday:** people claim in the channel, work when they can, open PRs.
- **Daily:** you answer every open thread once. That daily answer *is* the format; without
  it this is just an ordinary week with a poster.
- **Friday:** merge, thank everyone by what they built, invite the two or three strongest to
  review someone else's next PR.

Claims lapse automatically — 48 hours for L0/L1, seven days for L2 — so an unfinished task
returns to the pool. Check with `uv run python scripts/campaign_queue.py --claims`.

## Realistic numbers

With one reviewer, expect 8–12 attendees and 6–9 merges. That roughly doubles YazSes's
contributor count in ninety minutes, which is a real result — and it is a better first
target than an eighty-event campaign that needs reviewers you do not have yet.

Recruit your next reviewer *from* the sprint: whoever finishes early and starts helping
others is the person to ask.
