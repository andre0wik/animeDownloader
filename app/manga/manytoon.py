from .madara import MadaraPlatform


class ManytoonPlatform(MadaraPlatform):
    id        = "manytoon"
    name      = "Manytoon"
    base_url  = "https://manytoon.com"
    dl_subdir = "Manytoon"

    supported_filters = {"status", "genres"}
    genres = [
        ("Action",        "action"),
        ("Adult",         "adult"),
        ("Adventure",     "adventure"),
        ("Comedy",        "comedy"),
        ("Drama",         "drama"),
        ("Fantasy",       "fantasy"),
        ("Harem",         "harem"),
        ("Horror",        "horror"),
        ("Manhwa",        "manhwa"),
        ("Martial Arts",  "martial-arts"),
        ("Mature",        "mature"),
        ("Mystery",       "mystery"),
        ("Romance",       "romance"),
        ("School Life",   "school-life"),
        ("Seinen",        "seinen"),
        ("Shounen",       "shounen"),
        ("Slice of Life", "slice-of-life"),
        ("Supernatural",  "supernatural"),
    ]
