import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import QueueItem

_DL_PROGRESS_RE = re.compile(
    r'\[download\]\s+([\d.]+)%.*?at\s+([\d.]+)([\w/]+)\s+ETA\s+(\S+)'
)


def _parse_last_progress(log_path: Path) -> tuple[float, str, float, str]:
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            m = _DL_PROGRESS_RE.search(line)
            if m:
                pct        = float(m.group(1))
                speed_val  = float(m.group(2))
                speed_unit = m.group(3)
                eta        = m.group(4)
                su = speed_unit.upper()
                if "GIB" in su or "GB" in su:
                    mib = speed_val * 1024
                elif "KIB" in su or "KB" in su:
                    mib = speed_val / 1024
                elif su.startswith("B/"):
                    mib = speed_val / 1_048_576
                else:
                    mib = speed_val
                return mib, f"{speed_val:.1f} {speed_unit}", pct, eta
    except Exception:
        pass
    return 0.0, "", 0.0, ""


def _queue_status_text(queue: list) -> str:
    active  = [i for i in queue if i.status == "downloading"]
    pending = sum(1 for i in queue if i.status == "pending")
    done    = sum(1 for i in queue if i.status == "done")
    errors  = sum(1 for i in queue if i.status == "error")

    if not queue:
        return "[dim]Coda vuota  (Ctrl+D per aprirla)[/dim]"

    total_mib  = 0.0
    best_eta   = ""
    best_secs  = 0

    for item in active:
        if item.log_path:
            mib, _, _, eta = _parse_last_progress(item.log_path)
            total_mib += mib
            if eta:
                try:
                    p    = eta.split(":")
                    secs = int(p[-1]) + int(p[-2]) * 60 + (int(p[-3]) * 3600 if len(p) > 2 else 0)
                    if secs > best_secs:
                        best_secs, best_eta = secs, eta
                except Exception:
                    pass

    parts: list[str] = []
    if active:
        spd     = f"{total_mib:.1f} MiB/s" if total_mib > 0 else "..."
        eta_str = f"  ETA {best_eta}" if best_eta else ""
        parts.append(f"[yellow]>> {len(active)} in corso  {spd}{eta_str}[/yellow]")
    if pending:
        parts.append(f"[dim]{pending} in attesa[/dim]")
    if done:
        parts.append(f"[green]{done} completati[/green]")
    if errors:
        parts.append(f"[red]{errors} errori[/red]")

    hint = "  [dim](Ctrl+D: coda)[/dim]" if (active or pending) else ""
    return "  |  ".join(parts) + hint
