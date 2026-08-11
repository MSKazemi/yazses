# Setting up Windows code signing via SignPath

[SignPath.io](https://signpath.io) provides **free Authenticode code signing
for OSS projects** through their Foundation programme. Once your project is
approved, the `build-windows.yml` workflow automatically signs the `.exe`
on every release — eliminating the SmartScreen *"unrecognized app"* warning
that today blocks adoption.

The workflow is already structured for this — it auto-detects whether the
secrets below are present and falls back to an unsigned dev preview if any
are missing. **Just paste the four secrets and the next push to a `v*` tag
(or manual dispatch) produces a signed `.exe`.**

## 1. Apply to the SignPath Foundation programme

1. Go to https://about.signpath.io/foundation.
2. Click **Apply for Free Code Signing**.
3. Fill in the form. You'll need:
   - The repo URL: https://github.com/MSKazemi/yazses
   - License: Apache-2.0 (qualifies)
   - A short description (the README's pitch is fine)
4. Approval typically takes 1–3 business days. SignPath emails when the
   project is created in your dashboard.

## 2. Create an API token + signing policy

After approval, sign in at https://app.signpath.io.

1. **Organisations** → click your org → note the **Organization ID** (UUID).
2. **Projects** → click `yazses` → **Settings** → **Signing Policies**.
   - The default `release-signing` policy is fine for the first run; or
     create a stricter one (review-required, etc.).
   - Note the **slug** (e.g. `release-signing`).
3. **Account** (top right) → **API Tokens** → **Create API Token**.
   - Scope: limit to your project + signing-request permissions.
   - Copy the generated token; you can't view it again.

## 3. Set the four repo secrets

Go to *Settings → Secrets and variables → Actions → New repository secret*
and add **all four**:

| Secret name | Value |
|---|---|
| `SIGNPATH_API_TOKEN` | The token from step 2 |
| `SIGNPATH_ORGANIZATION_ID` | The UUID from step 2 |
| `SIGNPATH_PROJECT_SLUG` | `yazses` (or whatever SignPath assigned) |
| `SIGNPATH_SIGNING_POLICY` | `release-signing` (or your policy slug) |

## 4. Verify

Trigger the workflow manually:

```sh
gh workflow run build-windows.yml --ref main
```

The "Detect signing presence" step prints
`"Signing via SignPath will run."` when all four are set. The signed
installer's signature is verified at the end of the run via
`Get-AuthenticodeSignature`. The same `.exe` is then attached to the
GitHub Release on the next tag push.

## Reputation curve

SignPath's certificate is OV-class, not EV. SmartScreen builds reputation
based on how many distinct users run the signed binary; for the first
~200–500 installs of a new identity you may still see SmartScreen warnings,
but they downgrade quickly once enough users hit "Run anyway". An EV cert
would skip this curve but costs ~$200/yr and isn't free for OSS.

## Updating

API tokens are revocable from SignPath's account page. If you rotate the
token, only `SIGNPATH_API_TOKEN` needs updating in repo secrets — the other
three stay the same.

If you ever migrate off SignPath (e.g. to a self-managed signtool flow),
delete the four secrets and the workflow's "Detect signing presence" step
flips back to producing an unsigned dev preview.
