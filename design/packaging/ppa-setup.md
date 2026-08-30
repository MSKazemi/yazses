# Launchpad PPA Setup (One-Time)

> **Status as of 2026-08-30: not done, and nothing here has been executed.**
> `https://launchpad.net/~mskazemi/+archive/ubuntu/yazses` answers 404, and so does
> the Launchpad person `~mskazemi` -- the account in step 1 has never been created.
> `PPA_GPG_PRIVATE_KEY` and `PPA_GPG_KEY_ID` are not set, and
> `.github/workflows/ppa.yml` has never run: it triggers on `v0.*` tags only and this
> project passed v1.0.0 long ago.
>
> This mattered outside the packaging plan. The release-notes template in
> `release.yml` carried the snippet in §5 as a live install instruction, so every
> GitHub release since v1.0.0 told Ubuntu users to add a PPA that does not exist. The
> section has been removed and `tests/test_release_notes_channels_are_real.py` now
> fails the build if the notes advertise a channel nothing publishes. Restore the
> section in the same change that finishes the steps below -- not before.

## 1. Create a Launchpad account

Register at https://launchpad.net/+login

## 2. Create the PPA

Go to https://launchpad.net/~<your-username> → Create a new PPA:
- Name: `yazses`
- Display name: YazSes

## 3. Upload your GPG key to Launchpad

```bash
# Get your key fingerprint
gpg --list-secret-keys --keyid-format LONG <your-email>

# Upload to Ubuntu keyserver (required by Launchpad)
gpg --send-keys --keyserver keyserver.ubuntu.com <KEY_ID>

# Then go to Launchpad and add your key fingerprint:
# https://launchpad.net/~/+editpgpkeys
```

## 4. Add GitHub Secrets

Go to https://github.com/MSKazemi/yazses/settings/secrets/actions and add:

| Secret name | Value |
|---|---|
| `PPA_GPG_PRIVATE_KEY` | `gpg --armor --export-secret-keys <KEY_ID>` |
| `PPA_GPG_KEY_ID` | 16-char key ID (e.g. `ABCDEF1234567890`) |

## 5. After setup, users install with

```bash
sudo add-apt-repository ppa:mskazemi/yazses
sudo apt update
sudo apt install yazses
```
