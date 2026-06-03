import datetime
import json
import subprocess
import threading
from pathlib import Path

from ..config import SYNC_QUEUE_FILE
from .ssh import _SSH_OPTS

_SYNC_RETRY_INTERVAL = 60
_sync_stop_event     = threading.Event()


def _server_reachable(host: str) -> bool:
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
         host, "exit"],
        capture_output=True,
    )
    return r.returncode == 0


def _load_sync_queue() -> list[dict]:
    try:
        return json.loads(SYNC_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_sync_queue(items: list[dict]) -> None:
    SYNC_QUEUE_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _enqueue_pending_sync(local_path: Path, host: str, remote_base: str) -> None:
    items = _load_sync_queue()
    key = str(local_path)
    if not any(i["local_path"] == key for i in items):
        items.append({
            "local_path":  key,
            "host":        host,
            "remote_base": remote_base,
            "added_at":    datetime.datetime.now().isoformat(timespec="seconds"),
        })
        _save_sync_queue(items)


def _sync_file_to_server(local_path: Path, host: str, remote_base: str) -> bool:
    remote_dir = f"{remote_base}/{local_path.parent.name}"
    r = subprocess.run(
        ["ssh", *_SSH_OPTS, host, f"mkdir -p '{remote_dir}'"],
        capture_output=True,
    )
    if r.returncode != 0:
        return False
    remote_path = f"{host}:{remote_dir}/{local_path.name}"
    r = subprocess.run(
        ["scp", *_SSH_OPTS, str(local_path), remote_path],
        capture_output=True,
    )
    return r.returncode == 0


def _try_auto_sync(local_path: Path, host: str, remote_base: str) -> bool:
    if _server_reachable(host) and _sync_file_to_server(local_path, host, remote_base):
        return True
    _enqueue_pending_sync(local_path, host, remote_base)
    return False


def _flush_sync_queue() -> int:
    items = _load_sync_queue()
    if not items:
        return 0

    by_host: dict[str, list[dict]] = {}
    for item in items:
        by_host.setdefault(item["host"], []).append(item)

    synced = 0
    remaining: list[dict] = []
    for host, host_items in by_host.items():
        if not _server_reachable(host):
            remaining.extend(host_items)
            continue
        for item in host_items:
            p = Path(item["local_path"])
            if not p.exists():
                continue
            if _sync_file_to_server(p, item["host"], item["remote_base"]):
                synced += 1
            else:
                remaining.append(item)

    _save_sync_queue(remaining)
    return synced


def _start_sync_retry_thread() -> threading.Thread:
    def _loop() -> None:
        while not _sync_stop_event.wait(timeout=_SYNC_RETRY_INTERVAL):
            try:
                _flush_sync_queue()
            except Exception:
                pass

    t = threading.Thread(target=_loop, name="sync-retry", daemon=True)
    t.start()
    return t
