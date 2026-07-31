---
layout: default
title: Troubleshooting
---

# Troubleshooting

## Dictation stops after connecting a USB-C monitor or headset

Some monitors, docks, and headsets register an audio input and become the operating system's default microphone. When that input is silent or very quiet, YazSes can keep running but stop writing dictated text because each recording is discarded as silence.

Check which device YazSes is using:

```sh
yazses audio status
yazses audio devices
```

The mic-change guard normally detects a default-input change and switches back to the last working microphone. To prevent the operating system from changing the capture device again, pin the intended microphone using a case-insensitive part of its displayed name, then restart YazSes:

```sh
yazses audio use "Built-in Microphone"
yazses restart
```

Run `yazses audio status` again to confirm that the pinned microphone is active. To return to following the operating system default later, run:

```sh
yazses audio use --clear
yazses restart
```
