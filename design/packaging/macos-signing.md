# Setting up macOS code signing + notarisation

Once you've enrolled in the **Apple Developer Program** ($99/yr), this guide
walks through wiring up CI to produce a signed + notarised `.dmg` so users
no longer see Gatekeeper's *"unidentified developer"* warning.

The `build-macos.yml` workflow is already structured for this — it auto-detects
whether the secrets below are present and falls back to an unsigned dev
preview if any are missing. **Just paste the six secrets and the next push
to a `v*` tag (or manual dispatch) produces a signed `.dmg`.**

## 1. Generate a Developer ID Application certificate

On your Mac, open **Keychain Access**:

1. *Keychain Access → Certificate Assistant → Request a Certificate from a
   Certificate Authority…*
2. Email: your Apple ID email; Common Name: anything; **Saved to disk**.
3. Sign in to https://developer.apple.com/account → *Certificates, IDs &
   Profiles*.
4. *Certificates → +* → **Developer ID Application**.
5. Upload the CSR you just saved; download the resulting `.cer`.
6. Double-click the `.cer` to install it into Keychain Access. It pairs
   with the private key from step 1–2.
7. In Keychain Access, find the certificate (it shows as
   *"Developer ID Application: <Your Name> (TEAMID)"*). Right-click →
   **Export** → save as `developerid.p12`. Pick a strong password; you'll
   paste this password as `MACOS_CERTIFICATE_PWD`.

## 2. Generate an app-specific password for notarytool

1. Sign in to https://appleid.apple.com/account/manage.
2. *Sign-In and Security → App-Specific Passwords → Generate*.
3. Label: `yazses notarytool`. Save the password — you can't view it
   again.

## 3. Find your team ID

Go to https://developer.apple.com/account → *Membership Details*.
The 10-character alphanumeric code is `MACOS_NOTARY_TEAM_ID`.

## 4. Find your signing identity string

```sh
security find-identity -v -p codesigning
```

Look for the line that starts with the SHA1 then has
`"Developer ID Application: <Your Name> (TEAMID)"`. Copy the full
quoted string (without the surrounding quotes) — that's
`MACOS_SIGNING_IDENTITY`.

## 5. Encode the .p12 for GitHub

```sh
base64 -i developerid.p12 -o developerid.p12.b64
cat developerid.p12.b64 | pbcopy   # copies to clipboard
```

## 6. Set the six repo secrets

Go to *Settings → Secrets and variables → Actions → New repository secret*
and add **all six**:

| Secret name | Value |
|---|---|
| `MACOS_CERTIFICATE` | The base64 string from step 5 (paste; long single line) |
| `MACOS_CERTIFICATE_PWD` | The .p12 password from step 1 |
| `MACOS_NOTARY_APPLE_ID` | The Apple ID email |
| `MACOS_NOTARY_PASSWORD` | The app-specific password from step 2 |
| `MACOS_NOTARY_TEAM_ID` | The 10-char team ID from step 3 |
| `MACOS_SIGNING_IDENTITY` | The full identity string from step 4 |

## 7. Verify

Trigger the workflow manually:

```sh
gh workflow run build-macos.yml --ref main
```

Watch the run. The "Detect signing presence" step prints
`"Signing + notarisation will run."` when all six are set. Failure modes:

- *"errSecInternalComponent"* → the keychain isn't unlocked or partition
  list isn't set; usually a `MACOS_CERTIFICATE_PWD` mismatch.
- *"Invalid notarisation"* / *"submission rejected"* → the entitlements
  in `packaging/macos/entitlements.plist` are missing something Apple wants;
  read the `xcrun notarytool log <submission-id>` output linked in the run.
- *"The Developer ID Application identity is not valid for signing"* → the
  `.p12` exported only the public part of the cert. Re-export from
  Keychain Access selecting **both** the certificate and its private key.

Once the run goes green, the `.dmg` attached to the GitHub Release is
signed + notarised. Users no longer need the right-click → Open dance.

## Updating

The signing certificate is valid for **5 years**. Renew via the Apple
Developer portal when it expires; export a fresh `.p12` and update only
the `MACOS_CERTIFICATE` and `MACOS_CERTIFICATE_PWD` secrets.

App-specific passwords don't expire but are revocable from
appleid.apple.com if compromised.
