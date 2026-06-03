import subprocess
import sys
import time
from pathlib import Path

_SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]


def _ssh(host: str, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", *_SSH_OPTS, host, cmd],
        stdout=subprocess.PIPE, text=True,
    )


def _ssh_fm(host: str, cmd: str) -> tuple[str, int]:
    r = subprocess.run(
        ["ssh", *_SSH_OPTS, host, cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return r.stdout or "", r.returncode


def _ensure_ssh_key(host: str) -> None:
    key_path = Path.home() / ".ssh" / "id_ed25519"
    pub_path = key_path.with_suffix(".pub")

    if not key_path.exists():
        print("  Chiave SSH non trovata — la genero...")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True,
        )
        print(f"  Chiave creata: {key_path}")

    r = subprocess.run(
        ["ssh", *_SSH_OPTS, "-o", "BatchMode=yes", host, "exit"],
        capture_output=True,
    )
    if r.returncode == 0:
        return

    pub_key = pub_path.read_text(encoding="utf-8").strip()
    escaped = pub_key.replace("'", "'\\''")
    print("  Chiave SSH non configurata sul server.")
    print("  Inserire la password una sola volta per copiarla:")
    r2 = subprocess.run(
        ["ssh", *_SSH_OPTS, host,
         f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qF '{escaped}' ~/.ssh/authorized_keys 2>/dev/null"
         f" || echo '{escaped}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"],
    )
    if r2.returncode == 0:
        print("  Chiave copiata — i prossimi accessi non richiederanno la password.")
    else:
        print("  [ATTENZIONE] Copia chiave fallita — verrà richiesta la password ad ogni operazione.")


def cmd_sync(local_dir: Path, host: str, remote_base: str) -> None:
    if not local_dir.is_dir():
        sys.exit(f"[ERRORE] Cartella locale non trovata: {local_dir}")

    _ensure_ssh_key(host)

    local_files = sorted(f.name for f in local_dir.glob("*.mp4"))
    if not local_files:
        print("  Nessun file .mp4 nella cartella locale.")
        return

    print(f"  File locali  : {len(local_files)}")

    remote_dir = f"{remote_base}/{local_dir.name}"

    r = _ssh(host, f"mkdir -p '{remote_dir}'")
    if r.returncode != 0:
        sys.exit("[ERRORE] Impossibile creare cartella remota su Gengar (vedi errore sopra)")

    r = _ssh(host, f"ls '{remote_dir}' 2>/dev/null")
    if r.returncode != 0:
        sys.exit("[ERRORE] Impossibile creare cartella remota su Gengar (vedi errore sopra)")

    remote_files = set(r.stdout.strip().splitlines()) if r.stdout.strip() else set()
    print(f"  File remoti  : {len(remote_files)}  ({remote_dir})")

    missing = [f for f in local_files if f not in remote_files]

    if not missing:
        print("\n  Tutti gli episodi sono già presenti su Gengar!")
        return

    print(f"\n  Mancanti: {len(missing)}")
    for fname in missing:
        size_mb = (local_dir / fname).stat().st_size / (1024 * 1024)
        print(f"    - {fname}  ({size_mb:.1f} MB)")

    print()
    errors = 0
    for i, fname in enumerate(missing, 1):
        local_path  = local_dir / fname
        remote_path = f"{host}:{remote_dir}/{fname}"
        size_mb     = local_path.stat().st_size / (1024 * 1024)
        print(f"  [{i}/{len(missing)}] {fname}  ({size_mb:.1f} MB) ...", end="", flush=True)
        t0 = time.monotonic()
        r  = subprocess.run(["scp", *_SSH_OPTS, str(local_path), remote_path])
        elapsed = time.monotonic() - t0
        if r.returncode == 0:
            speed = size_mb / elapsed if elapsed > 0 else 0
            print(f"  OK  ({elapsed:.0f}s, {speed:.1f} MB/s)")
        else:
            print("  [ERRORE]")
            errors += 1

    if errors:
        print(f"\n  Completato con {errors} errore/i.")
    else:
        print("\n  Sincronizzazione completata.")
