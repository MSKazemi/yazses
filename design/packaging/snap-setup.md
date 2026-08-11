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
