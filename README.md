# animeDownloader

Python script to download anime from **AnimeUnity** and manga/manhwa/webtoons from multiple platforms on Windows, with automatic sync to a remote Linux server via SSH.

## Features

- Download anime episodes in a specified range via `yt-dlp`
- Download manga/manhwa chapters from **7 platforms** as CBZ (optionally converted to PDF)
- Download ebooks from **Anna's Archive** and **Z-Library**
- Interactive TUI to search, browse and queue downloads
- Automatically downloads portable `ffmpeg`/`ffprobe` if not present
- Syncs downloaded files to a remote Linux server via SSH
- Download history (`history.json`) to avoid duplicates
- Persistent configuration via `settings.json`

## Supported platforms

### Anime
| Platform | Language |
|---|---|
| [AnimeUnity](https://www.animeunity.so) | Italian |

### Manga / Manhwa / Webtoon
| Platform | Content | Language |
|---|---|---|
| [MangaDex](https://mangadex.org) | Manga, manhwa, manhua | Multi-language |
| [MangaWorld](https://www.mangaworld.mx) | Manga, manhwa | Italian |
| [Toonily](https://toonily.com) | Manhwa | English |
| [Manhwatop](https://manhwatop.com) | Manhwa | English |
| [LINE Webtoon](https://www.webtoons.com) | Webtoon | English |
| [Tapas](https://tapas.io) | Webtoon / comic | English |

### Ebooks
| Platform | Notes |
|---|---|
| [Anna's Archive](https://annas-archive.org) | Aggregator (requires API key) |
| [Z-Library](https://z-lib.id) | Requires API key |

## Requirements

- Python 3.9+
- [`uv`](https://github.com/astral-sh/uv) (dependency management)

Dependencies (`yt-dlp`, `curl-cffi`, `playwright`, `rich`, `textual`) are installed automatically by `uv`.

## Usage

### Interactive TUI

Launch the TUI to search and download from any supported platform:

```bash
uv run animeunity_dl.py
```

From the TUI you can:
- Search anime, manga, manhwa, webtoons and ebooks by title
- Filter by language, genre, status, demographic, content rating and sort order
- Select individual chapters/episodes to download
- Queue multiple series in parallel
- Monitor download progress in real time

### AnimeUnity (CLI)

```bash
# Download episodes 1 to 10
uv run animeunity_dl.py download https://www.animeunity.so/anime/390-dragon-ball-super-ita 1 10

# Download missing/partial episodes
uv run animeunity_dl.py missing https://www.animeunity.so/anime/390-dragon-ball-super-ita

# Sync missing files to a remote SSH server
uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
```

On Windows you can also use the included batch file:

```bat
scarica_dbs.bat
```

## Configuration

On first launch `settings.json` is created with default values. Edit it to change the download folder, SSH host, number of parallel downloads, API keys, etc.
