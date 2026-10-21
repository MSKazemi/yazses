# ADR-028 Phase 0 spike: a PyInstaller runtime hook for the THROWAWAY spike build only.
#
# It is never listed in packaging/windows/yazses.spec. `.github/workflows/packs-spike.yml`
# writes a separate spec with `scripts/build-packs.py spike-spec`, which puts this file
# first in `runtime_hooks`, freezes that copy, and runs the result once per pack with
# YAZSES_PACK_SPIKE_REQUEST pointing at a JSON request. Without that variable the hook
# returns immediately and the app starts normally.
#
# With it, the hook is the "hand-written mount in a test entry point" the spec asks for:
# it mounts one extracted pack the way ADR-028 §2 describes (append to sys.path, keep
# os.add_dll_directory handles, invalidate caches), measures the four open risks, writes
# the result JSON and exits before YazSes' own entry point runs.
#
#   (a) stdlib modules the pack needs that the frozen app did not collect
#   (b) importlib.metadata over the pack's dist-info and the base's distributions
#   (c) submodules of base packages that PyInstaller pruned
#   (d) which file a colliding DLL basename (onnxruntime.dll) actually loaded from, and
#       for a pack whose pack.json `bind_to_base` lists it: that, with the base's copy
#       preloaded by full path, the pack's code binds to it, the base's onnxruntime
#       reports the version the base froze, and both an onnxruntime session and the
#       pack's own native session (sherpa-onnx's silero VAD) build and run
#
# The hook imports onnxruntime only when a pack binds to the base, and onnxruntime is
# already in the frozen base, so it adds nothing PyInstaller would not collect anyway.
#
# Standard library only, apart from the bind probe's onnxruntime and the pack's own
# sherpa_onnx (both imported only when a request names `bind_to_base`). Every exception
# is caught and recorded: the job reads the JSON.

# ruff: noqa
# mypy: ignore-errors

import os


def _spike(request_path):
    import importlib
    import importlib.metadata
    import json
    import pkgutil
    import sys
    import traceback

    with open(request_path, encoding="utf-8") as fh:
        req = json.load(fh)
    result = {
        "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": getattr(sys, "_MEIPASS", None),
        "sys_path_before": list(sys.path),
    }
    stdlib = set(sys.stdlib_module_names)
    base_modules = {m.lower() for m in req.get("base_modules", [])}

    # --- mount, exactly as ADR-028 §2 steps 4-6 ---------------------------------------
    handles = []
    for p in [req["site"], *req.get("extra_paths", [])]:
        sys.path.append(p)
    result["dll_dir_errors"] = []
    for d in req.get("native_dirs", []):
        try:
            handles.append(os.add_dll_directory(d))
        except Exception as exc:
            result["dll_dir_errors"].append(f"{d}: {exc!r}")
    importlib.invalidate_caches()
    result["sys_path_after"] = list(sys.path)

    # --- bind_to_base: load the base's copy by full path BEFORE the pack's code -------
    # pack.json's `bind_to_base` names DLLs the build dropped from the pack (sherpa-onnx-
    # core's own onnxruntime.dll). The pack's .pyd still asks for them by basename, and
    # Windows answers a by-name request from the loaded-module list, so the base's copy
    # must already be loaded. This is what the runtime does before an entry import.
    bind = {"pack_root": os.path.dirname(req["site"]), "preloaded": {},
            "preload_errors": {}, "expected_ort_version": req.get("expected_ort_version")}
    result["bind"] = bind
    for name, paths in sorted((req.get("bind_to_base") or {}).items()):
        if not paths:
            bind["preload_errors"][name] = "the base ships no copy"
            continue
        try:
            import ctypes

            # Absolute: the loader reports loaded modules by absolute path, and the
            # first windows-latest run compared that with a relative request (FAIL on a
            # correct bind, run 39631811305).
            full = os.path.abspath(paths[0])
            ctypes.WinDLL(full)
            bind["preloaded"][name] = full
        except BaseException as exc:
            bind["preload_errors"][name] = repr(exc)[:300]

    def kind_of(name):
        top = (name or "").split(".", 1)[0]
        if top in stdlib:
            return "stdlib"
        if top.lower() in base_modules:
            return "base-submodule" if "." in (name or "") else "base"
        return "other"

    def try_import(name):
        try:
            mod = importlib.import_module(name)
            return {"ok": True, "file": getattr(mod, "__file__", None)}
        except BaseException as exc:
            missing = getattr(exc, "name", None) if isinstance(exc, ImportError) else None
            return {
                "ok": False,
                "module": name,
                "error": repr(exc)[:500],
                "missing": missing,
                "kind": kind_of(missing) if missing else "other",
                "trace": traceback.format_exc()[-3000:],
            }

    # --- does appending to sys.path import pack modules at all? ------------------------
    result["entry"] = {m: try_import(m) for m in req.get("entry_modules", [])}

    # --- deep sweep: every submodule of the pack's own packages ------------------------
    sweep_failures = []
    imported = 0
    for top in req.get("pack_packages", []):
        mod = sys.modules.get(top)
        if mod is None:
            r = try_import(top)
            if not r["ok"]:
                sweep_failures.append(r)
                continue
            mod = sys.modules.get(top)
        paths = getattr(mod, "__path__", None)
        if not paths:
            continue
        for info in pkgutil.walk_packages(paths, prefix=top + ".",
                                          onerror=lambda n: sweep_failures.append(
                                              {"module": n, "kind": "other",
                                               "error": "walk_packages onerror"})):
            if ".tests" in info.name or ".test." in info.name:
                continue
            r = try_import(info.name)
            if r["ok"]:
                imported += 1
            else:
                sweep_failures.append(r)
    result["sweep_imported"] = imported
    result["sweep_failures"] = sweep_failures

    # --- (a) stdlib modules the pack's code refers to ----------------------------------
    result["stdlib_checked"] = list(req.get("stdlib_candidates", []))
    result["stdlib_missing"] = [m for m in result["stdlib_checked"] if not try_import(m)["ok"]]

    # --- (c) dotted base submodules the pack's code refers to --------------------------
    result["base_submodules_checked"] = list(req.get("base_submodule_candidates", []))
    result["base_submodules_missing"] = [
        m for m in result["base_submodules_checked"] if not try_import(m)["ok"]
    ]

    # --- (b) importlib.metadata ---------------------------------------------------------
    def version_of(dist):
        try:
            return importlib.metadata.version(dist)
        except Exception:
            return None

    result["metadata"] = {
        "pack": {d: version_of(d) for d in req.get("distributions", [])},
        "base": {d: version_of(d) for d in req.get("base_requires", [])},
    }

    # --- (d) bind: does the pack's native code run on the base's ONNX Runtime? --------
    # Measured before the loaded-module list below, so a second onnxruntime.dll pulled
    # in by either session would show up there and fail the verdict.
    if req.get("bind_to_base"):
        model = req.get("session_model")
        try:
            import onnxruntime as ort

            bind["ort"] = {"version": getattr(ort, "__version__", None),
                           "file": getattr(ort, "__file__", None)}
        except BaseException as exc:
            bind["ort"] = {"version": None, "file": None, "error": repr(exc)[:300]}
        if not model:
            bind["ort_session"] = {"ok": False, "error": "no --session-model given"}
            bind["native_session"] = {"ok": False, "error": "no --session-model given"}
        else:
            try:
                import onnxruntime as ort

                sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
                bind["ort_session"] = {"ok": True,
                                       "inputs": [i.name for i in sess.get_inputs()]}
            except BaseException as exc:
                bind["ort_session"] = {"ok": False, "error": repr(exc)[:300]}
            try:
                import sherpa_onnx

                cfg = sherpa_onnx.VadModelConfig()
                cfg.silero_vad.model = model
                cfg.sample_rate = 16000
                if not cfg.validate():
                    raise RuntimeError("sherpa_onnx rejected the VAD config")
                vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=5)
                vad.accept_waveform([0.0] * 16000)  # one second of silence: real inference
                detected = getattr(vad, "is_speech_detected", lambda: None)()
                bind["native_session"] = {"ok": True, "speech_in_silence": detected,
                                          "file": getattr(sherpa_onnx, "__file__", None)}
            except BaseException as exc:
                bind["native_session"] = {"ok": False, "error": repr(exc)[:300],
                                          "trace": traceback.format_exc()[-2000:]}

    # --- (d) where each colliding DLL basename actually loaded from --------------------
    loaded = []
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32EnumProcessModules.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        arr = (wintypes.HMODULE * 4096)()
        needed = wintypes.DWORD()
        if k32.K32EnumProcessModules(k32.GetCurrentProcess(), arr, ctypes.sizeof(arr),
                                     ctypes.byref(needed)):
            buf = ctypes.create_unicode_buffer(32768)
            count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), 4096)
            for i in range(count):
                if k32.GetModuleFileNameW(arr[i], buf, 32768):
                    loaded.append(buf.value)
    except Exception as exc:
        result["loaded_error"] = repr(exc)
    collided = {b.lower() for b in req.get("collided_dlls", [])}
    by_name = {}
    for path in loaded:
        base = os.path.basename(path).lower()
        if base in collided:
            by_name.setdefault(base, []).append(path)
    result["loaded_collisions"] = by_name
    bind["loaded"] = {
        name: [p for p in loaded if os.path.basename(p).lower() == name]
        for name in (req.get("bind_to_base") or {})
    }
    result["loaded_onnxruntime"] = [p for p in loaded if "onnxruntime" in p.lower()]
    result["dll_handles_kept"] = len(handles)
    return result


_REQUEST = os.environ.get("YAZSES_PACK_SPIKE_REQUEST")
if _REQUEST:
    _code = 0
    try:
        _result = _spike(_REQUEST)
    except BaseException as _exc:  # the job must get a result, never a silent exit
        import traceback as _tb

        _result = {"crash": _tb.format_exc()[-4000:]}
        _code = 3
    try:
        import json as _json

        with open(_json.load(open(_REQUEST, encoding="utf-8"))["result"], "w",
                  encoding="utf-8") as _fh:
            _json.dump(_result, _fh, indent=2, default=repr)
    except BaseException:
        _code = 4
    os._exit(_code)
