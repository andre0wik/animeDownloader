from .madara import MadaraPlatform


class ManhwatopPlatform(MadaraPlatform):
    id        = "manhwatop"
    name      = "Manhwatop"
    base_url  = "https://manhwatop.com"
    dl_subdir = "Manhwatop"

    supported_filters    = {"status", "genres"}
    supports_empty_search = True
    genres = [
        ("Action",        "action"),
        ("Adventure",     "adventure"),
        ("Comedy",        "comedy"),
        ("Drama",         "drama"),
        ("Fantasy",       "fantasy"),
        ("Harem",         "harem"),
        ("Historical",    "historical"),
        ("Horror",        "horror"),
        ("Martial Arts",  "martial-arts"),
        ("Mature",        "mature"),
        ("Mecha",         "mecha"),
        ("Mystery",       "mystery"),
        ("Psychological", "psychological"),
        ("Romance",       "romance"),
        ("School Life",   "school-life"),
        ("Sci-Fi",        "sci-fi"),
        ("Seinen",        "seinen"),
        ("Slice of Life", "slice-of-life"),
        ("Sports",        "sports"),
        ("Supernatural",  "supernatural"),
        ("Thriller",      "thriller"),
    ]
