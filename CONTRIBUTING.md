# Contributing to YazSes

Thank you for your interest in contributing. The shipping product is the **Python implementation** on the `main` branch — that's where almost all contributions should go. An early-stage **Rust HCI exploration** is paused on the `archive/rust-hci-v1` branch (not built, installed, or maintained); see the "Two versions of YazSes" section in the README.

## Getting started (Python — the active product)

```sh
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync
uv run python -m pytest tests/ -v   # run the test suite
uv run ruff check src tests         # lints
uv run mypy src                     # type checking
```

### Rust HCI exploration (archived)

Only relevant if you are exploring the paused agent prototype:

```sh
git checkout archive/rust-hci-v1
cargo build && cargo test --workspace
cargo clippy --workspace
```

Optional Rust feature flags: `--features whisper`, `--features moonshine`, `--features llama-cpp`, `--features ollama`, `--features silero`.

## Before opening a pull request

- Run the test suite and confirm it passes.
- For new features, add tests.
- Keep PRs focused — one concern per PR.
- Describe the *why* in the PR body, not just the *what*.

## Reporting bugs

Open an issue at https://github.com/MSKazemi/yazses/issues and include:
- OS and version
- `yazses --version` output
- Steps to reproduce
- Relevant lines from `yazses logs`

## Platform support

If you are adding support for a new platform or injection backend, implement all relevant Protocol interfaces and add a test. See `src/yazses/platform/base.py` for the interface contracts (the archived Rust branch has its own under `crates/yazses-inputs/src/protocol.rs`).

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
