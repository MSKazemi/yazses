# Candidate author roster — YazSes paper v2

**Purpose:** seed the all-contributors authorship invitation process.  
**Seed date:** 2026-09-23  
**Seed source:** public contributor metadata in .all-contributorsrc and CONTRIBUTORS.md on current main, commit 247913a5f7cdf4a48035ac77aa4f179144b89c33.  
**Seed count:** 29 people.

The seed is pinned to a commit so its staleness is checkable rather than assumed. Re-derive the
current count with:

```sh
python -c "import json; print(len(json.load(open('.all-contributorsrc'))['contributors']))"
```

If that prints more than the seed count above, people have been added since the seed and the
roster must be re-seeded before invitations go out — an omitted contributor is the one failure
this process cannot correct after publication.

This is a **candidate roster, not a final byline**. Every person below must explicitly opt in before their name can appear as an author. Preferred publication name, affiliation, ORCID, private contact email, author order, and final approval must be collected directly from the person; do not infer them from GitHub.

Private email addresses and individual consent evidence must not be added to this public file.

| # | GitHub | Current public name | Public contribution categories |
|---:|---|---|---|
| 1 | @MSKazemi | Mohsen Seyedkazemi Ardebili | maintenance, code, documentation |
| 2 | @lntutor | lntutor | documentation |
| 3 | @HeaTTap | HeaTTap | code |
| 4 | @jackie-cqz | jackie-cqz | code |
| 5 | @Parinitha-26 | Parinitha-26 | documentation |
| 6 | @AshSgDe29071999 | AshSgDe29071999 | code, documentation |
| 7 | @Maqbool61 | Maqbool Ahmed | code |
| 8 | @waterlemonnn | Renji | code, testing, documentation, security, infrastructure |
| 9 | @slegarraga | Sebastian Legarraga | code, user testing, platform validation |
| 10 | @YossiMH | YossiMH | ideas, bug finding, research |
| 11 | @Prithvi4904 | Prithvi4904 | translation |
| 12 | @4nmus | 4nmus | translation |
| 13 | @Mr-Neutr0n | hari | documentation |
| 14 | @mercael91 | mercael | infrastructure, documentation |
| 15 | @happytester-funbugs | Tanya Martin-McClellan | user testing, bug finding, platform validation |
| 16 | @AtmanActive | AtmanActive | bug finding, user testing |
| 17 | @hoti-code | hoti-code | user testing, bug finding, platform validation |
| 18 | @jayavandhiniMK | Jayavandhini M K | documentation |
| 19 | @visheshbpatel | Vishesh Patel | documentation, user testing, bug finding |
| 20 | @fall-water-zxc | fall-water-zxc | documentation, user testing, bug finding, platform validation |
| 21 | @greatlord | Magnus Olsen | bug finding, ideas |
| 22 | @Akgithub2028 | Aayaann Kausar | documentation, user testing |
| 23 | @auroraxo | Aurora | code, testing, platform validation |
| 24 | @YuuGR1337 | Elkero | documentation, translation, bug finding |
| 25 | @Guruharishb | Guruharishb | translation |
| 26 | @vortsghost2025 | DeliberateEnsemble | code |
| 27 | @doeil1614-ops | doeil1614-ops | translation |
| 28 | @musabustun | Musab Yusuf Üstün | translation |
| 29 | @sameer8945 | sameer | documentation / Windows showcase |

## Roster reconciliation procedure

Before sending invitations:

1. Set AUTHORSHIP_CUTOFF_SHA to the actual manuscript/evidence freeze commit.
2. Read .all-contributorsrc at that SHA.
3. Read CONTRIBUTORS.md at that SHA.
4. Compare the two sets.
5. Review merged contributions between 2026-09-23 and the cutoff so a newly added contributor is not accidentally omitted.
6. Resolve aliases/renames by asking the person; do not assume two accounts are the same individual.
7. Recalculate N and update this file if the frozen roster differs from the seed roster.
8. Record the final roster digest in the approval manifest.

If the manuscript later moves to a commit that includes additional contributors, the roster must be reopened and Gate 1 repeated for the new N.

## Information to collect from every candidate

Collect the following privately:

| Field | Required? | Publication default |
|---|---|---|
| Preferred author name | yes | public in byline |
| GitHub handle | yes for coordination | optional in paper |
| Contact email | yes for coordination | private unless opted in |
| Email publication permission | yes/no | no by default |
| Affiliation | yes, may be “Independent” or none | public as supplied |
| ORCID | optional | public only if supplied |
| CRediT roles | yes | public contribution statement |
| Funding/conflict statement | yes, “none” is valid | public if relevant |
| Authorship opt-in | yes | recorded privately |
| Author-order agreement | yes before freeze | reflected in byline |
| Final manuscript approval | yes | recorded against fingerprint |

## Important interpretation

The current public names above are discovery aids only. They may be usernames, nicknames, incomplete names, or names the person does not want used in a publication.

Do not turn this table directly into the manuscript byline.

The final byline exists only after each candidate has supplied or confirmed their preferred publication name and explicitly opted in.
