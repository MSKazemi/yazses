# Getting Help

## Documentation

Start here:

- [Install on Linux](../docs/install-linux.md)
- [Install on macOS](../docs/macos-install.md)
- [Install on Windows](../docs/windows-install.md)
- [CLI reference](../docs/cli-reference.md)

## Diagnostics

Most issues are diagnosed by:

```sh
yazses doctor          # checks OS prerequisites, permissions, device access
yazses logs            # shows the daemon diagnostic log
yazses mic-level       # checks mic level vs VAD threshold
```

If dictation does nothing and `yazses logs` shows `Silent audio -- discarding`, run `yazses mic-level --set` to recalibrate.

## Reporting a bug

Open an issue at https://github.com/MSKazemi/yazses/issues and include:

- OS and version
- Output of `yazses --version`
- Steps to reproduce
- Relevant output from `yazses logs`

## Security issues

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md).
