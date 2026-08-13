# The offline-inference challenge

YazSes transcribes on your own machine. This page is how you check that claim
yourself, in about ten minutes, and report what you saw.

!!! info "What this demonstrates, and what it does not"

    This is an **offline-inference demonstration**: it shows that transcription
    keeps working with networking disabled. That is a strong, checkable claim and
    it is the one we make.

    It is **not** proof of perfect privacy, and it is not proof that no software
    on your computer ever talks to the network. A single run on one machine
    cannot establish either. If you want the stronger claim, read the code and
    the [privacy statement](../privacy-statement.md) — and audit the traffic
    yourself with `tcpdump` or Little Snitch rather than taking this page's word
    for it.

The split that makes the demonstration meaningful: **installing and downloading a
model needs the network; transcribing does not.** Step 1 is deliberately online,
and everything after step 3 is deliberately offline. Conflating the two is the
usual way this kind of demo becomes misleading.

## 1. While online: install and pre-download the model

```bash
pipx install yazses          # or: uv tool install yazses
yazses setup                 # system packages, input group, injector
```

Download the speech model **now**, while you still have a network. Nothing later
will fetch it, and a first run with no model and no network fails for a boring
reason that has nothing to do with the claim being tested:

```bash
yazses doctor                # confirms which model is configured
yazses transcribe --help     # loading the CLI is enough to trigger the fetch path
```

If `doctor` reports the model is not cached, run one dictation or one
`yazses transcribe <file>` while online to pull it, then re-check.

## 2. Record what you are testing

Please capture these before going offline — a report without them cannot be
compared with anyone else's:

```bash
yazses --version
yazses doctor            # model, backend, session type, injector
python3 -VV
uname -a                 # or: systeminfo (Windows), sw_vers (macOS)
```

`yazses report` collects most of this into one local bundle. It redacts paths and
identifiers and never uploads anything — read it before you paste it.

## 3. Disable networking (reversibly)

Pick **one**, and note which you used. Each is reversible with the command beside
it. Prefer the airplane-mode or interface method over firewall rules if you are
not comfortable restoring them.

| Method | Disable | Restore |
|---|---|---|
| Desktop toggle | Airplane mode / turn Wi-Fi off in your OS settings | toggle back |
| Linux (NetworkManager) | `nmcli networking off` | `nmcli networking on` |
| macOS | `networksetup -setairportpower en0 off` | `... on` |
| Windows (admin) | `Disable-NetAdapter -Name "Wi-Fi"` | `Enable-NetAdapter -Name "Wi-Fi"` |
| Unplug | remove the Ethernet cable | plug it back in |

Confirm you are actually offline — an unplugged cable with Wi-Fi still up is the
classic false result:

```bash
curl -sS --max-time 5 https://pypi.org > /dev/null && echo "STILL ONLINE" || echo "offline"
```

## 4. Run the two things that matter

**A dictation.** Start the daemon, hold your hotkey, say a sentence you are happy
to publish, release:

```bash
yazses restart
yazses status            # state should reach idle
```

**A file transcription**, which exercises the same engine without a microphone:

```bash
yazses transcribe path/to/some-audio.wav
```

No sample handy? `scripts/download-sample.py` fetches one — but run it in step 1,
while you still have a network.

## 5. Record the result

Note, for each of the two runs: what you expected, what you got, how long it
took, and anything in `yazses logs` that looked wrong.

!!! warning "Do not paste your dictated text if it is private"

    We never need your words to diagnose this. Timings, the model name, the
    daemon state and the log's metadata lines are enough. Use a sentence you
    chose for publication, or describe the result without quoting it.

## 6. Restore networking

Undo step 3 using the matching command in the table, then confirm:

```bash
curl -sS --max-time 5 https://pypi.org > /dev/null && echo "back online" || echo "still offline"
```

## 7. Report it

Open an [offline-inference report](https://github.com/MSKazemi/yazses/issues/new?template=offline_challenge.yml).
The template asks for exactly the fields above and nothing else.

**Negative results are the valuable ones.** If transcription failed with the
network off, that is a bug worth more than a hundred confirmations, and it is
precisely what this exercise is for. Report it the same way.
