{
  # YazSes — offline voice dictation, packaged for Nix.
  #
  #   nix run   github:MSKazemi/yazses          # run without installing
  #   nix shell github:MSKazemi/yazses          # drop it into a shell
  #   nix profile install github:MSKazemi/yazses
  #
  # STATUS: evaluated. `nix flake check` passes for x86_64-linux — run it yourself
  # without installing Nix:
  #
  #     docker run --rm -v "$PWD:/host:ro" nixos/nix /host/packaging/nix/build-and-test.sh
  #
  # That first evaluation found two real defects, which is exactly why a manifest
  # should not ship unevaluated: the version was pinned at 2.17.0 while the project
  # had moved on, and `yazses-desktop` used `overrideAttrs`, which sees the
  # derivation AFTER buildPythonApplication has consumed `dependencies` — so
  # `old.dependencies` did not exist and evaluation failed outright.
  #
  # Still NOT verified: aarch64 and Darwin (the check omits incompatible systems),
  # and installing from a real NixOS machine rather than a container.
  #
  # See packaging/README.md for why this repo distinguishes "authored" from "published"
  # so pedantically: it already shipped three manifests that looked finished and
  # installed nobody, two of them pointing at releases that never existed.

  description = "Offline, on-device voice dictation and speech-to-text — hold a key, speak, release";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;

        yazses = python.pkgs.buildPythonApplication rec {
          pname = "yazses";
          version = "2.18.2";
          pyproject = true;
          src = ./.;

          build-system = [ python.pkgs.hatchling ];

          # Mirrors [project.dependencies] in pyproject.toml. PySide6 is deliberately
          # absent: it is the `desktop` extra (648 MB of Qt for the overlay and tray),
          # exposed as the separate `yazses-desktop` package below.
          dependencies = with python.pkgs; [
            faster-whisper
            sounddevice
            numpy
            typer
            platformdirs
            cryptography
            onnx-asr
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            evdev
            python-xlib
          ];

          # The suite is fully offline and mocks audio and models, so it is safe to run
          # in the sandbox — no microphone, no network, no Whisper weights required.
          nativeCheckInputs = with python.pkgs; [ pytestCheckHook pytest-mock ];

          # These need real hardware or a real desktop, neither of which exists in a
          # build sandbox.
          disabledTestPaths = [
            "tests/test_install_preflight.py"
          ];

          pythonImportsCheck = [ "yazses" "yazses.core.daemon" ];

          meta = with pkgs.lib; {
            description = "Offline voice dictation — hold a key, speak, release; runs on your own CPU";
            longDescription = ''
              YazSes transcribes speech locally with faster-whisper and types it into the
              focused window. No cloud, no API key, no account, no subscription and no
              telemetry; after the speech model is downloaded once it needs no network at
              all. It also transcribes recordings with optional speaker labels, and
              captures whole meetings into a labelled transcript.

              Dictation on Linux additionally needs the `input` group (to read the
              hold-to-talk key) and an injection backend — ydotool on Wayland, xdotool on
              X11. `yazses transcribe` needs neither.
            '';
            homepage = "https://mskazemi.com/yazses/";
            changelog = "https://github.com/MSKazemi/yazses/releases/tag/v${version}";
            license = licenses.asl20;
            mainProgram = "yazses";
            platforms = platforms.unix ++ platforms.windows;
          };
        };
      in
      {
        packages = {
          default = yazses;
          inherit yazses;

          # The desktop build: adds Qt for the voice-activity overlay and the tray icon.
          # overridePythonAttrs, NOT overrideAttrs: `dependencies` is an argument to
          # buildPythonApplication, which consumes it and turns it into
          # propagatedBuildInputs. overrideAttrs sees the derivation AFTER that, so
          # `old.dependencies` does not exist there — the first evaluation of this
          # flake failed with exactly that ("attribute 'dependencies' missing").
          yazses-desktop = yazses.overridePythonAttrs (old: {
            pname = "yazses-desktop";
            dependencies = (old.dependencies or [ ]) ++ [ python.pkgs.pyside6 ];
          });
        };

        apps.default = flake-utils.lib.mkApp { drv = yazses; };

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.uv python pkgs.ydotool pkgs.xdotool pkgs.wl-clipboard pkgs.xclip ];
          shellHook = ''
            echo "YazSes dev shell — 'uv sync' then 'uv run python -m pytest tests/ -q'"
          '';
        };
      });
}
