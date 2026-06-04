# animeDownloader

Multi-source media downloader with an interactive terminal UI (TUI) and CLI. Downloads anime from **AnimeUnity**, manga/manhwa/webtoons from **6 platforms**, and ebooks from **Anna's Archive** and **Z-Library**. Optionally syncs downloads to a remote Linux server via SSH.

## Features

### Anime
- Download episodes in a specified range via `yt-dlp`
- Detects and skips already-complete episodes; re-downloads partials
- Filters: type, year, status, season, genre (26 genres), Italian dub only
- Auto-sync downloaded episodes to SSH server

### Manga / Manhwa / Webtoon
- Downloads chapters as **CBZ** archives; optional auto-conversion to **PDF**
- Supports 6 platforms with platform-specific filters (language, genre, status, rating, demographic, sort)
- Detects locally downloaded chapters and highlights gaps
- "Select Missing" auto-selects undownloaded chapters

### Ebooks
- Search across Anna's Archive and Z-Library simultaneously
- Filters: language, format (EPUB, PDF, MOBI, FB2), source
- Z-Library: persistent login via Playwright

### General
- Interactive TUI with real-time download queue and progress
- Parallel downloads (configurable, default 2)
- Download history to avoid duplicates
- SSH File Manager: browse, delete, move, and create folders on remote server
- Persistent settings via `settings.json`

---

## Supported platforms

### Anime
| Platform | Language |
|---|---|
| [AnimeUnity](https://www.animeunity.so) | Italian |

### Manga / Manhwa / Webtoon
| Platform | Content | Language | Filters |
|---|---|---|---|
| [MangaDex](https://mangadex.org) | Manga, manhwa, manhua | 27 languages | Language, origin, status, demographic, rating, order, genres |
| [MangaWorld](https://www.mangaworld.mx) | Manga, manhwa | Italian | Status, genres, order |
| [Toonily](https://toonily.com) | Manhwa | English | Status, genres |
| [Manhwatop](https://manhwatop.com) | Manhwa | English | Status, genres |
| [LINE Webtoon](https://www.webtoons.com) | Webtoon | Multi-language | Language, genres |
| [Tapas](https://tapas.io) | Webtoon, comic | English | Genres |

### Ebooks
| Platform | Notes |
|---|---|
| [Anna's Archive](https://annas-archive.org) | Open-source aggregator |
| [Z-Library](https://z-lib.id) | Requires account (email + password in settings) |

---

## Requirements

- Python 3.9+
- [`uv`](https://github.com/astral-sh/uv) — dependency management

All other dependencies (`yt-dlp`, `curl-cffi`, `playwright`, `beautifulsoup4`, `textual`, `rich`) are installed automatically by `uv`.

---

## Usage

### Interactive TUI

```bash
uv run animeunity_dl.py
```

The TUI opens on the main menu with 6 sections:

| Section | Description |
|---|---|
| **Anime / Film** | Search and download anime episodes from AnimeUnity |
| **Manga / Manhwa** | Search and download chapters across 6 platforms |
| **Ebook** | Search and download ebooks from Anna's Archive / Z-Library |
| **Download queue** | Monitor all active, pending, and completed downloads |
| **Settings** | Edit all configuration options |
| **SSH File Manager** | Browse and manage files on the remote server |

**Keyboard shortcuts**

| Key | Action |
|---|---|
| `Q` | Quit |
| `Ctrl+D` | Open download queue |
| `Escape` / `Ctrl+B` | Back to previous screen |
| `F5` | Refresh (file manager) |

---

### CLI — AnimeUnity

```bash
# Download episodes 1–10
uv run animeunity_dl.py download https://www.animeunity.so/anime/390-dragon-ball-super-ita 1 10

# Download only missing/partial episodes
uv run animeunity_dl.py missing https://www.animeunity.so/anime/390-dragon-ball-super-ita

# Sync a local folder to the remote SSH server
uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
```

**`download` options**

| Flag | Description |
|---|---|
| `url` | AnimeUnity series URL |
| `start` | First episode to download (default: 1) |
| `end` | Last episode to download (default: start + 9) |
| `--out` | Custom output directory |
| `--ytdlp-args` | Extra arguments passed to yt-dlp |

**`missing` options**

| Flag | Description |
|---|---|
| `url` | AnimeUnity series URL |
| `--start` | First episode to check (default: 1) |
| `--end` | Last episode to check (default: all) |
| `--out` | Custom output directory |
| `--ytdlp-args` | Extra arguments passed to yt-dlp |

**`sync` options**

| Flag | Description |
|---|---|
| `--local` | Local folder to sync (default: download_dir) |
| `--host` | SSH host string `user@host` (default: from settings) |
| `--remote-base` | Remote base path (default: from settings) |

---

## Output structure

```
downloads/
├── AnimeUnity/
│   └── Dragon Ball Super/
│       ├── Dragon Ball Super - Ep001.mp4
│       └── Dragon Ball Super - Ep002.mp4
├── MangaDex/
│   └── Dragon Ball/
│       ├── Ch 0001.cbz
│       └── Ch 0001.pdf        ← if cbz_to_pdf is enabled
├── MangaWorld/
├── Toonily/
├── Webtoon/
├── Tapas/
└── Ebook/
```

---

## Configuration

On first launch `settings.json` is created with defaults. All options are also editable from the **Settings** screen in the TUI.

| Key | Default | Description |
|---|---|---|
| `download_dir` | `./downloads` | Base folder for all downloaded files |
| `max_concurrent` | `2` | Number of parallel downloads (1–8) |
| `cbz_to_pdf` | `false` | Auto-convert CBZ manga archives to PDF |
| `auto_sync` | `false` | Automatically sync to SSH server after each anime download |
| `ssh_host` | — | SSH connection string `user@host` |
| `ssh_remote_base` | — | Remote base path for SSH sync |
| `animeunity_base` | `https://www.animeunity.so` | AnimeUnity domain (changes when domain rotates) |
| `toonily_user` | — | Toonily username (optional, for adult content) |
| `toonily_pass` | — | Toonily password |
| `zlib_email` | — | Z-Library account email |
| `zlib_password` | — | Z-Library account password |

---

## SSH setup

The sync feature uses `scp` over SSH. On first use, an ED25519 key pair is generated automatically and added to `authorized_keys` on the remote server (requires password login once). Subsequent syncs use key authentication.
