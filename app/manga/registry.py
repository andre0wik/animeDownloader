from .base import MangaPlatform
from .mangadex    import MangaDexPlatform
from .toonily     import ToonillyPlatform
from .manhwatop   import ManhwatopPlatform
from .webtoon     import WebtoonPlatform
from .tapas       import TapasPlatform
from .mangaworld  import MangaWorldPlatform

PLATFORMS: dict[str, MangaPlatform] = {
    p.id: p for p in [
        MangaDexPlatform(),
        ToonillyPlatform(),
        ManhwatopPlatform(),
        WebtoonPlatform(),
        TapasPlatform(),
        MangaWorldPlatform(),
    ]
}

PLATFORM_LIST: list[MangaPlatform] = list(PLATFORMS.values())
