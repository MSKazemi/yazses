# Snap Store Setup (One-Time)

## 1. Create a Snap Store account

Register at https://snapcraft.io/account

## 2. Register the snap name

```bash
sudo snap install snapcraft --classic
snapcraft login
snapcraft register yazses
```

## 3. Apply for classic confinement

YazSes needs classic confinement to access `/dev/input` keyboard events via evdev.
Strict confinement has no interface that grants keyboard `/dev/input/event*` access.

Apply in the Snap Store dashboard → Your snap → Request classic confinement.
Explain: "YazSes reads keyboard events via `/dev/input/event*` using the Python
evdev library. The `joystick` interface only covers joystick devices, not keyboards.
No strict interface provides this access."

Canonical reviews these manually (typically 1–2 weeks).

## 4. Get store credentials for CI

```bash
snapcraft export-login --snaps=yazses --channels=stable credentials.txt
cat credentials.txt
```

Add the full credentials output as GitHub Secret `SNAPCRAFT_STORE_CREDENTIALS`.

## 5. After classic is approved

Users install with:
```bash
sudo snap install yazses --classic
```

To set up auto-start:
```bash
mkdir -p ~/.config/systemd/user
curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/contrib/yazses.service \
  -o ~/.config/systemd/user/yazses.service
systemctl --user enable --now yazses.service
```

## 6. CI publishing contract

The `snap.yml` workflow publishes `amd64` and `arm64` independently. A successful
build is not a successful release: each job must upload its snap, resolve the
store revision for that exact version and architecture, release that revision to
`stable,edge`, and read `latest/stable` back from the store. The job remains red
unless the read-back matches.

Snap Store review can leave `snapcraft upload` printing `Status: processing`
past the workflow's upload timeout even though the store has already accepted
the revision. The workflow therefore treats the command status as advisory,
queries `snapcraft revisions`, and issues `snapcraft release` as a **separate
call**. That separate call is the mechanism the contract depends on, and it is
the half that has been observed to publish.

The upload also passes `--release=stable,edge`, as a belt-and-braces hint rather
than a mechanism. Whether the store records those channels and applies them once
review passes is **plausible and unverified here**: revisions 388/389 show only
that omitting the flag leaves no channel, which does not establish that including
it defers one. Nothing may depend on a deferred release, and no log line or
message may tell a reader that one is pending.

What actually unblocked this area was neither flag: the snapcraft.io build service
was building every commit to `main`, wedging the store's review queue. It has been
disconnected, which makes `snap.yml` the only publisher — and leaves no fallback if
it breaks.

Revision output is captured completely before it is parsed: do
not pipe the live command into a consumer that exits after its first match,
because Snapcraft reports the resulting closed stdout pipe as exit 120 under
`set -o pipefail`.

When a publish fails, distinguish the two cases in the job log:

- `the store holds no revision` means the upload or credentials failed.
- A found revision followed by `resource-not-ready: Revision ... is not approved`
  means the upload succeeded but store review has not finished. The job correctly
  remains red until the channel read-back matches. Re-run the release once review
  clears; do not assume the upload's channel hint will publish it for you.
- Any other release or channel read-back failure means the upload succeeded, but
  the store did not make that revision available on the requested channel.
