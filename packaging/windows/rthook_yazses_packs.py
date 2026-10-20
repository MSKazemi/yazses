# PyInstaller runtime hook: mount installed add-on packs before YazSes starts (ADR-028 §2).
#
# Runs before the entry script in every process of the frozen app (multiprocessing
# children included). It appends each verified pack's site/ to sys.path, keeps the
# os.add_dll_directory handles alive, and imports nothing from any pack. It mounts
# nothing in an elevated process, with YAZSES_NO_PACKS=1, or when the embedded index
# does not belong to this build -- all decided in yazses.packs.mount.
#
# A pack must never be able to stop YazSes from starting, so every exception is
# swallowed here as well as inside mount_at_startup.
try:
    from yazses.packs.mount import mount_at_startup

    mount_at_startup()
except Exception:  # noqa: BLE001
    pass
