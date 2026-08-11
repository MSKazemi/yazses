# APT Repository Setup (One-Time)

Run these commands ONCE on your local machine to generate and register the signing key.

## 1. Generate a dedicated signing key

```bash
gpg --batch --gen-key <<EOF
Key-Type: RSA
Key-Length: 4096
Name-Real: YazSes APT Repository
Name-Email: apt@mskazemi.github.io
Expire-Date: 2y
%no-passphrase
%commit
EOF
```

> **Note:** The key expires in 2 years. Before it expires, run `gpg --edit-key <KEY_ID>` and use `expire` to renew, then re-add the secret to GitHub.

## 2. Find the key ID

```bash
gpg --list-secret-keys --keyid-format LONG apt@mskazemi.github.io
# Note the 16-char ID after "rsa4096/"
```

## 3. Export the private key

```bash
gpg --armor --export-secret-keys <KEY_ID>
```

Copy the entire output (including `-----BEGIN PGP PRIVATE KEY BLOCK-----`).

## 4. Add GitHub Secrets

Go to https://github.com/MSKazemi/yazses/settings/secrets/actions and add:

| Secret name | Value |
|---|---|
| `APT_REPO_GPG_PRIVATE_KEY` | The full `--armor --export-secret-keys` output |
| `APT_REPO_GPG_KEY_ID` | The 16-char key ID |

## 5. Enable GitHub Pages

Go to https://github.com/MSKazemi/yazses/settings/pages and set:
- Source: Deploy from a branch
- Branch: `gh-pages` / `/ (root)`

After the first release, the apt repo will be live at:
`https://mskazemi.github.io/yazses/apt/`
