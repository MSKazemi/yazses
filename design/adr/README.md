# YazSes v1.0 — Architectural Decision Records

This directory contains the 11 binding ADRs for YazSes v1.0.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adr-001.md) | Rust core + Python plugins via PyO3 | Accepted |
| [ADR-002](adr-002.md) | Dual-stack STT routing | Accepted |
| [ADR-003](adr-003.md) | LLM backend: llama.cpp + MLX | Accepted |
| [ADR-004](adr-004.md) | Grammar-constrained tool calls | Accepted |
| [ADR-005](adr-005.md) | InputBackend Protocol | Accepted |
| [ADR-006](adr-006.md) | EditorBridge Protocol | Accepted |
| [ADR-007](adr-007.md) | Personal memory: sqlite-vec + SQLCipher | Accepted |
| [ADR-008](adr-008.md) | Distribution: cargo-dist + per-distro packagers | Accepted |
| [ADR-009](adr-009.md) | Python plugin SDK via embedded PyO3 | Accepted |
| [ADR-010](adr-010.md) | Preserve v0.4 JSON-RPC 2.0 IPC contract | Accepted |
| [ADR-011](adr-011.md) | Zero telemetry, offline-default, opt-in cloud | Accepted |

These decisions are binding for v1.0 and inform v2 design. To propose a change to an accepted ADR, create a new ADR that supersedes it and open a PR.

## Other series in this directory

- `adr-012` … `adr-015`, `adr-v04-*`, `adr-v2-001..129` — the v0.4/v2 series. Internal, like this one.
- **`adr-mob-001..010` — the mobile programme. Not here: they live in `docs/mobile/adr/` and
  are deliberately PUBLIC**, because the Android app is built by contributors who need to
  read the architecture they are implementing. See `design/mobile/README.md` for why that
  exception exists and what still belongs in `design/`.
