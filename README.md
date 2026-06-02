# animeDownloader

Script Python per scaricare episodi da **AnimeUnity** (.so / .to / .tv) e sincronizzarli su un server SSH.

## Funzionalità

- Scarica episodi in un intervallo specificato tramite `yt-dlp`
- Scarica automaticamente `ffmpeg`/`ffprobe` portatili se non presenti nel sistema
- Sincronizza gli episodi su un server remoto via SSH (copia i file mancanti)
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

# Sincronizza i file mancanti sul server SSH
uv run animeunity_dl.py sync --local "D:/downloader/Dragon Ball Super Ita"
```

Su Windows puoi usare anche il batch incluso:

```bat
scarica_dbs.bat
```

## Configurazione

Al primo avvio viene creato `settings.json` con i valori di default. Modifica il file per cambiare cartella di download, host SSH, numero di download paralleli, ecc.
