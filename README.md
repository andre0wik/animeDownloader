# animeDownloader

Script Python per scaricare anime da **AnimeUnity** (.so / .to / .tv) e manga/manhwa da **MangaDex** su Windows, con sincronizzazione automatica su server Linux via SSH.

## Funzionalità

- Scarica episodi anime in un intervallo specificato tramite `yt-dlp`
- Scarica capitoli manga/manhwa da MangaDex (con supporto lingua italiana)
- Interfaccia TUI interattiva per cercare e accodare download
- Scarica automaticamente `ffmpeg`/`ffprobe` portatili se non presenti nel sistema
- Sincronizza gli episodi su un server Linux remoto via SSH (copia i file mancanti, gestione filesystem)
- Cronologia dei download (`history.json`) per evitare duplicati
- Configurazione persistente via `settings.json`

## Requisiti

- Python 3.9+
- [`uv`](https://github.com/astral-sh/uv) (gestione dipendenze)

Le dipendenze (`yt-dlp`, `curl-cffi`, `playwright`, `rich`, `textual`) vengono installate automaticamente da `uv`.

## Utilizzo

```bash
# Scarica gli episodi dall'1 al 10
uv run animeunity_dl.py download https://www.animeunity.so/anime/390-dragon-ball-super-ita 1 10

# Scarica i capitoli manga mancanti da MangaDex
uv run animeunity_dl.py  # avvia la TUI interattiva

# Sincronizza i file mancanti sul server SSH Linux
uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
```

Su Windows puoi usare anche il batch incluso:

```bat
scarica_dbs.bat
```

## Configurazione

Al primo avvio viene creato `settings.json` con i valori di default. Modifica il file per cambiare cartella di download, host SSH, numero di download paralleli, ecc.
