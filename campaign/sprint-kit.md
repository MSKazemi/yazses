# 90-minute contribution sprint kit

Everything needed to run a session where a room of people each land one real, merged
contribution to YazSes. Written so someone who has never spoken to the maintainer can run
it.

**Do not run this without a reviewer.** A sprint that produces 20 pull requests nobody
reviews for a week is worse than no sprint: it teaches 20 people that contributing here
means waiting. If you cannot get a reviewer, run it for 6 people instead of 20.

## What you need

| Role | How many | Doing what |
|---|---|---|
| Organizer | 1 | Room, timing, follow-up afterwards |
| Facilitator | 1 per ~10 people | Unblocking installs and git |
| Reviewer | 1 per ~8 people | Reviewing during the session, not after |

Participants need a GitHub account and **that is genuinely all** for most tasks. Do not
require a clone, a Discord, a mailing list, a CLA, or a sign-off line — YazSes asks for
none of them. Opening the pull request is the whole contract.

## Send this 48 hours before

> Bring a laptop and a GitHub account. That's it.
>
> Nothing to install beforehand — most tasks are done in the browser, and the ones that
> need a machine will be matched to whatever you already have. If you want to set up
> anyway: <https://github.com/MSKazemi/yazses/blob/main/.github/CONTRIBUTING.md>. On Linux you
> need a C compiler (`build-essential`), on macOS and Windows you need nothing.
>
> If you use a coding agent, bring it. It's welcome — you stay the author.

## Choosing tasks before the day

Open [`generated/open-tasks.md`](generated/open-tasks.md) and pick per person, from the
column that matches what they actually have:

| Who is coming | Give them | Why |
|---|---|---|
| Browser only, 15 min | `MIC-*`, `COMPAT-*`, `VEC-*` | One file, no clone |
| Speaks another language | `I18N-*` | The lede + Quick Start is a complete PR |
| Uses a specific editor or terminal | `APP-*` | They already have the app |
| Comfortable with Python | `WIRE-*`, `QA-*` | Real code, bounded |
| Has unusual hardware or an unusual distro | `COMPAT-*`, `PKG-*` | Nobody else can produce this evidence |

**Reserve 3 tasks per person.** Some will be finished in 20 minutes and some will stall.

Two failure modes to avoid: giving everyone the same task family (you get 20 duplicate
compatibility records for the same laptop model), and giving a hardware or translation task
to someone who cannot personally produce the evidence. A coding agent generating a
compatibility record it did not observe is a fabricated contribution and will be rejected.

## The 90 minutes

| Time | What |
|---|---|
| 0:00–0:10 | What YazSes is, why offline matters, and what will be merged today |
| 0:10–0:20 | Everyone picks a task and comments on the umbrella issue to claim it |
| 0:20–0:30 | Environment: browser editor for most, Codespaces for code tasks |
| 0:30–1:00 | Work. Facilitators circulate. Reviewer starts reviewing the first finishers |
| 1:00–1:12 | Open PRs. Nothing to sign — the PR itself is the whole contract |
| 1:12–1:25 | Reviews land; contributors fix in the room while help is beside them |
| 1:25–1:30 | Close: what got merged, where credit appears, what to do next if they want |

The 0:30–1:00 block is the session. Everything else exists to protect it.

## The three things that go wrong

1. **`uv sync` fails on Linux** — missing C compiler. `evdev` publishes no wheels.
   `sudo apt install build-essential python3-dev`. Have this on a slide; it is the single
   most common stall and it looks like the project is broken.
2. **A first-timer's checks sit in "waiting for approval"** — GitHub holds workflow runs on
   a fork's first pull request until a maintainer approves them. It is not their mistake and
   nothing they can fix. Have someone with write access watching the Actions tab and clearing
   these within the session, or the room stalls on a check that never started.
3. **Two people take the same task** — that is a scheduling failure, not theirs. Reserve
   one as independent verification, or hand them a held-back task. Never make someone redo
   an evening's work.

## Afterwards, within 72 hours

- Every PR gets a human response. This is the promise the session made.
- Anything not merged gets a specific reason and a named next step.
- Thank people by what they produced, not by count.
- Ask the two or three strongest to review someone else's next PR — that is how a sprint
  adds capacity instead of consuming it.

## What to report back

Open an issue with: how many attended, how many opened a PR, how many merged, which task
families worked, and **what wasted people's time**. The last one is the valuable part. Task
descriptions that confused a room of 20 will confuse everyone who reads them afterwards.

## What not to do

- No leaderboards or prizes by PR count. It produces the submissions you least want.
- No empty commits, no adding names to lists purely to raise a number.
- Do not tell people this is about reaching a contributor count. It is about a room of
  people each making one real improvement, which is both truthful and more motivating.
