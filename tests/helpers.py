from __future__ import annotations

from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MOVIE_URL = "https://straight.aebn.com/straight/movies/309021/fixture-title"


class FakeCookies:
    def set(self, **_kwargs: Any) -> None:
        return None


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("utf-8")


class FakeSession:
    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.cookies = FakeCookies()

    def get(self, url: str, **_kwargs: Any) -> FakeResponse:
        for key, content in self.pages.items():
            if key in url:
                return FakeResponse(content)
        raise AssertionError(f"unexpected url: {url}")


def load_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def session_for(
    desktop_name: str = "desktop_movie.html",
    mobile_name: str = "mobile_no_scenes.html",
) -> FakeSession:
    return FakeSession(
        {
            MOVIE_URL: load_fixture(desktop_name),
            "m.aebn.net/movie/309021": load_fixture(mobile_name),
        }
    )
