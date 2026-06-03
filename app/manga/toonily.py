from .madara import MadaraPlatform


class ToonillyPlatform(MadaraPlatform):
    id         = "toonily"
    name       = "Toonily"
    base_url   = "https://toonily.com"
    dl_subdir  = "Toonily"
    manga_path = "serie"   # Toonily usa /serie/ non /manga/

    supported_filters    = {"status", "genres"}
    supports_empty_search = True
    genres = [
        ("Action",         "action"),
        ("Adult",          "adult"),
        ("Adventure",      "adventure"),
        ("Comedy",         "comedy"),
        ("Drama",          "drama"),
        ("Fantasy",        "fantasy"),
        ("Harem",          "harem"),
        ("Horror",         "horror"),
        ("Josei",          "josei"),
        ("Martial Arts",   "martial-arts"),
        ("Mature",         "mature"),
        ("Mystery",        "mystery"),
        ("Psychological",  "psychological"),
        ("Romance",        "romance"),
        ("School Life",    "school-life"),
        ("Sci-Fi",         "sci-fi"),
        ("Seinen",         "seinen"),
        ("Shounen",        "shounen"),
        ("Slice of Life",  "slice-of-life"),
        ("Sports",         "sports"),
        ("Supernatural",   "supernatural"),
        ("Thriller",       "thriller"),
        ("Webtoons",       "webtoons"),
    ]
