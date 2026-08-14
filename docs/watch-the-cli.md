# Watch the CLI

A real recording of the YazSes command line — `-h`, `about`, `quickstart`,
`features`, `status` — playing in your browser. It is about 32 KB of text, the
output is selectable, and you can copy any command straight out of it.

<link rel="stylesheet" href="assets/asciinema/asciinema-player.css">
<div id="yazses-cast" style="max-width:100%;overflow-x:auto"></div>
<script src="assets/asciinema/asciinema-player.min.js"></script>
<script>
  AsciinemaPlayer.create(
    'demo/yazses-cli.cast',
    document.getElementById('yazses-cast'),
    { cols: 100, rows: 30, idleTimeLimit: 2, fit: 'width', terminalFontSize: '14px' }
  );
</script>

Prefer your own terminal? The cast is a plain file in the repository:

```bash
asciinema play docs/demo/yazses-cli.cast
```

## What this does and does not show

It is the terminal half of YazSes, and only that. **Dictation itself cannot
appear in a terminal recording** — the interesting part is a key held down, a
voice, and words arriving in another application, none of which a cast can
capture. For that, see the [demo reel](https://www.youtube.com/watch?v=nn8WUKsCvZ4).

`doctor` is deliberately absent. Its output contains the recording machine's
real config and model-cache paths, and baking one machine's filesystem into a
committed recording is not a trade worth making for a demo.

## How it is generated

The cast is not hand-typed and not hand-edited:

```bash
uv run python scripts/gen-terminal-demo.py
```

Every byte of output comes from running the installed CLI for real. The script
points stdout at a wrapper that reports `isatty() == True`, because both Click
and Rich check that and fall back to plain text otherwise — so without it the
recording would lose exactly the colour and the box-drawing panels that make
`--help` and `features` worth showing. Timing is synthetic: a short "typed"
prompt, the output, a pause.

Re-run it after any change to the CLI surface, the same as the man page and the
generated config reference.

## The player is served from this site

`assets/asciinema/` holds asciinema-player 3.17.0 (Apache-2.0, licence
alongside it). It is **not** loaded from a CDN, and neither is anything else on
this site: a privacy tool whose documentation reports every reader's IP address
to a third party would be making a liar of itself.
