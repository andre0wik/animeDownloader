import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from ..config import MANGADEX_API

_LOG = Path(__file__).parent.parent.parent / "mangadex_debug.log"


def _get(url: str, params: dict, timeout: int = 15) -> dict:
    qs = urllib.parse.urlencode(params, doseq=True).replace("%5B", "[").replace("%5D", "]")
    full_url = f"{url}?{qs}"
    req = urllib.request.Request(full_url, headers={"User-Agent": "downloader/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
        data = json.loads(raw)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[OK] {full_url}\n")
            f.write(f"     total={data.get('total')}  items={len(data.get('data', []))}\n")
        return data
    except Exception as e:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[ERR] {full_url}\n")
            f.write(f"      {type(e).__name__}: {e}\n")
        raise

_MDX_GENRES = [
    ("Action",        "391b0423-d847-456f-aff0-8b0cfc03066b"),
    ("Adventure",     "87cc87cd-a395-47af-b27a-93258283bbc6"),
    ("Comedy",        "4d32cc48-9f00-4cca-9b5a-a839f0764984"),
    ("Drama",         "b9af3a63-f058-46de-a9a0-e0c13906197a"),
    ("Fantasy",       "cdc58593-87dd-415e-bbc0-2ec27bf404cc"),
    ("Historical",    "33771934-028e-4cb3-8744-691e866a923e"),
    ("Horror",        "cdad7e68-1419-41dd-bdce-27753074a640"),
    ("Isekai",        "ace04997-f6bd-436e-b261-779182193d3d"),
    ("Martial Arts",  "799c202e-7daa-44eb-9cf7-8a3b0441094e"),
    ("Mecha",         "e89d6967-3c39-4a57-9bba-0c8cde53b6ae"),
    ("Mystery",       "ee968100-4191-4968-93d3-f82d72be7e46"),
    ("Psychological", "3b60b75c-a2d7-4860-ab56-05f391bb889c"),
    ("Romance",       "423e2eae-a7a2-4a8b-ac03-a8351462d71d"),
    ("School Life",   "caaa44eb-cd40-4177-b930-79d3ef2efa74"),
    ("Sci-Fi",        "256c8bd9-4904-4360-bf4f-508a76d67183"),
    ("Slice of Life", "e5301a23-ebd9-49dd-a0cb-2add944c7fe9"),
    ("Sports",        "69964a64-2f90-4d33-beeb-f3ed2875eb4c"),
    ("Supernatural",  "eabc5b4c-6aff-42f3-b657-3e90cbd00b75"),
    ("Thriller",      "07251805-a27e-4d59-b488-f0bfbec15168"),
    ("Harem",         "aafb99c1-7f60-43fa-89a6-39fbf3b90ccd"),
]

_MDX_LANG_OPTS = [
    ("Italiano",  "it"),
    ("Inglese",   "en"),
    ("Spagnolo",  "es"),
    ("Francese",  "fr"),
]

_MDX_ORIGIN_OPTS = [
    ("Manga (JP)",  "ja"),
    ("Manhwa (KR)", "ko"),
    ("Manhua (CN)", "zh"),
]

_MDX_STATUS_OPTS = [
    ("In corso",   "ongoing"),
    ("Completato", "completed"),
    ("Hiatus",     "hiatus"),
    ("Cancellato", "cancelled"),
]

_MDX_DEMO_OPTS = [
    ("Shounen", "shounen"),
    ("Shoujo",  "shoujo"),
    ("Seinen",  "seinen"),
    ("Josei",   "josei"),
]

_MDX_RATING_OPTS = [
    ("Safe",       "safe"),
    ("Suggestivo", "suggestive"),
    ("Adulti",     "erotica"),
]

_MDX_ORDER_OPTS = [
    ("Più seguiti",       "followedCount"),
    ("Rilevanza",         "relevance"),
    ("Ultimi aggiornati", "latestUploadedChapter"),
    ("Più recenti",       "createdAt"),
]


def search_mangadex(
    title: str = "",
    translated_lang: str = "it",
    original_lang: str = "",
    status: str = "",
    demographic: str = "",
    content_rating: str = "",
    included_tags: list | None = None,
    order: str = "followedCount",
) -> list[dict]:
    params: dict = {
        "limit": 40,
        "includes[]": "cover_art",
    }
    if title:
        params["title"] = title

    if content_rating == "erotica":
        params["contentRating[]"] = ["erotica"]
    else:
        params["contentRating[]"] = ["safe", "suggestive"]

    if translated_lang:
        params["availableTranslatedLanguage[]"] = [translated_lang]
    if original_lang:
        params["originalLanguage[]"] = [original_lang]
    if status:
        params["status[]"] = [status]
    if demographic:
        params["publicationDemographic[]"] = [demographic]
    if included_tags:
        params["includedTags[]"] = included_tags

    order_map = {
        "followedCount":         ("followedCount",         "desc"),
        "relevance":             ("relevance",             "desc"),
        "latestUploadedChapter": ("latestUploadedChapter", "desc"),
        "createdAt":             ("createdAt",             "desc"),
    }
    field, direction = order_map.get(order, ("followedCount", "desc"))
    params[f"order[{field}]"] = direction

    data = _get(f"{MANGADEX_API}/manga", params)
    results = []
    for item in data.get("data", []):
        attrs  = item.get("attributes", {})
        titles = attrs.get("title", {})
        name   = (
            titles.get("en") or titles.get("ja-ro") or
            titles.get("ja") or next(iter(titles.values()), "?")
        )
        genre_tags = [
            t["attributes"]["name"].get("en", "")
            for t in attrs.get("tags", [])
            if t.get("attributes", {}).get("group") == "genre"
        ][:3]
        results.append({
            "manga_id":       item["id"],
            "title":          name,
            "status":         attrs.get("status", ""),
            "demographic":    attrs.get("publicationDemographic") or "",
            "content_rating": attrs.get("contentRating", ""),
            "original_lang":  attrs.get("originalLanguage", ""),
            "year":           str(attrs.get("year", "") or ""),
            "genres":         ", ".join(genre_tags),
            "languages":      ", ".join(attrs.get("availableTranslatedLanguages") or []),
        })
    return results


def fetch_manga_chapters(manga_id: str, translated_lang: str = "it") -> list[dict]:
    all_chapters: list[dict] = []
    offset = 0
    while True:
        try:
            data  = _get(f"{MANGADEX_API}/manga/{manga_id}/feed", {
                "translatedLanguage[]": [translated_lang],
                "order[chapter]": "asc",
                "limit": 500,
                "offset": offset,
            }, timeout=20)
            items = data.get("data", [])
            if not items:
                break
            for item in items:
                attrs = item.get("attributes", {})
                all_chapters.append({
                    "id":     item["id"],
                    "volume": attrs.get("volume") or "",
                    "number": attrs.get("chapter") or "?",
                    "title":  attrs.get("title") or "",
                    "pages":  attrs.get("pages", 0),
                    "lang":   attrs.get("translatedLanguage", ""),
                })
            total   = data.get("total", 0)
            offset += len(items)
            if offset >= total:
                break
            time.sleep(0.4)
        except Exception:
            break

    seen: dict[str, dict] = {}
    for ch in all_chapters:
        num = ch["number"]
        if num not in seen or ch["pages"] > seen[num]["pages"]:
            seen[num] = ch

    def _num_key(n: str) -> float:
        try:
            return float(n)
        except ValueError:
            return float("inf")

    return sorted(seen.values(), key=lambda c: _num_key(c["number"]))
