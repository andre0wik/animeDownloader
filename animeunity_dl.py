#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "yt-dlp",
#     "curl-cffi",
#     "playwright",
#     "rich",
#     "textual",
#     "zlibrary",
#     "playwright",
# ]
# ///

"""
Downloader + sync per AnimeUnity (.so / .to / .tv) e MangaDex.

Subcomandi:
  download  Scarica episodi da AnimeUnity (default)
  missing   Scarica episodi mancanti o parziali
  sync      Verifica e copia gli episodi mancanti su un server SSH

Esempi:
  uv run animeunity_dl.py download https://www.animeunity.so/anime/390-dragon-ball-super-ita 1 10
  uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
"""

import argparse
import sys
from pathlib import Path


def main() -> None:
    from app.config import _CFG, _anime_dl_dir
    from app.animeunity.api import parse_anime_url, fetch_episodes
    from app.animeunity.download import local_complete_eps, run_episode_list
    from app.sync.ssh import cmd_sync
    from app.tui.app import AnimeUnityApp

    parser = argparse.ArgumentParser(
        description="AnimeUnity downloader + sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    dl = sub.add_parser("download", help="Scarica episodi da AnimeUnity")
    dl.add_argument("url")
    dl.add_argument("start",  nargs="?", type=int, default=1)
    dl.add_argument("end",    nargs="?", type=int, default=None)
    dl.add_argument("--out",  default=None)
    dl.add_argument("--ytdlp-args", nargs=argparse.REMAINDER, default=[])

    ms = sub.add_parser("missing", help="Scarica episodi mancanti o parziali")
    ms.add_argument("url")
    ms.add_argument("--start", type=int, default=1,    help="Primo episodio (default: 1)")
    ms.add_argument("--end",   type=int, default=9999, help="Ultimo episodio (default: tutti)")
    ms.add_argument("--out",   default=None)
    ms.add_argument("--ytdlp-args", nargs=argparse.REMAINDER, default=[])

    sy = sub.add_parser("sync", help="Verifica e copia episodi mancanti su Gengar")
    sy.add_argument("--local",       default=None,                    help="Cartella locale")
    sy.add_argument("--host",        default=_CFG["ssh_host"],        help="SSH host")
    sy.add_argument("--remote-base", default=_CFG["ssh_remote_base"], help="Percorso base remoto")

    args = parser.parse_args()

    if not args.cmd:
        AnimeUnityApp().run()
        return

    if args.cmd == "missing":
        base_url, anime_id, slug = parse_anime_url(args.url)
        title   = slug.replace("-", " ").title()
        out_dir = Path(args.out) if args.out else _anime_dl_dir() / title
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nAnime  : {title}")
        print(f"Sito   : {base_url}")
        print(f"Output : {out_dir}")

        print("\nScansione episodi locali...")
        have = local_complete_eps(out_dir, title)
        print(f"  Completi in locale : {sorted(have) or 'nessuno'}")

        print("\nFetch lista episodi da AnimeUnity...")
        all_eps = fetch_episodes(base_url, anime_id, args.start, args.end)
        if not all_eps:
            print("[ATTENZIONE] Nessun episodio restituito dall'API.")
            sys.exit(1)

        to_dl = [
            ep for ep in all_eps
            if str(ep.get("number", "")).isdigit()
            and int(ep["number"]) not in have
        ]

        if not to_dl:
            print("\nNessun episodio mancante — tutto aggiornato!")
            return

        missing_nums = sorted(int(ep["number"]) for ep in to_dl)
        print(f"\nEpisodi mancanti ({len(to_dl)}): {missing_nums}\n")

        run_episode_list(
            to_dl, base_url, anime_id, slug, title, out_dir, args.ytdlp_args,
            auto_sync=bool(_CFG.get("auto_sync")),
        )
        return

    if args.cmd == "sync":
        local_dir = Path(args.local) if args.local else Path(_CFG["download_dir"])
        print(f"\nSync: {local_dir}")
        print(f"  → {args.host}:{args.remote_base}\n")
        cmd_sync(local_dir, args.host, args.remote_base)
        return

    # download
    start_ep = args.start
    end_ep   = args.end if args.end is not None else start_ep + 9

    base_url, anime_id, slug = parse_anime_url(args.url)
    title = slug.replace("-", " ").title()

    print(f"\nAnime  : {title}")
    print(f"Sito   : {base_url}")
    print(f"Range  : episodi {start_ep} – {end_ep}")

    print("\nRecupero lista episodi...")
    episodes = fetch_episodes(base_url, anime_id, start_ep, end_ep)
    if not episodes:
        print("[ATTENZIONE] Nessun episodio trovato.")
        sys.exit(1)
    print(f"Trovati {len(episodes)} episodi")

    out_dir = Path(args.out) if args.out else _anime_dl_dir() / title
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output : {out_dir}\n")

    run_episode_list(
        episodes, base_url, anime_id, slug, title, out_dir, args.ytdlp_args,
        auto_sync=bool(_CFG.get("auto_sync")),
    )


if __name__ == "__main__":
    main()
