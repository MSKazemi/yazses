# Launchpad PPA Setup (One-Time)

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
