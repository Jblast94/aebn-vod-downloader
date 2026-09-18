from __future__ import annotations

import logging

from aebn_dl.exceptions import ScraperError
from aebn_dl.movie_scraper import Movie
from tests.helpers import MOVIE_URL, session_for


def test_calculate_scenes_boundaries_warns_when_mobile_html_has_no_scenes(caplog):
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_no_scenes.html"))
    assert movie.title == "Fixture Title"
    assert len(movie.scenes) == 2

    with caplog.at_level(logging.WARNING, logger="aebn_dl.movie_scraper"):
        movie.calculate_scenes_boundaries(segment_duration=2.0)

    assert movie.scenes[0].start_timing is None
    assert movie.scenes[0].end_timing is None
    assert "scene" in caplog.text.lower()


def test_calculate_scenes_boundaries_parses_legacy_scroller_divs():
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_scrollers.html"))
    movie.calculate_scenes_boundaries(segment_duration=2.0)

    assert movie.scenes[0].start_timing == 0
    assert movie.scenes[0].end_timing == 600
    assert movie.scenes[0].start_segment == 0
    assert movie.scenes[0].end_segment == 299
    assert movie.scenes[1].start_timing == 600
    assert movie.scenes[1].end_timing == 1200


def test_calculate_scenes_boundaries_parses_data_time_attributes_without_scroller_class():
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_data_time_attrs.html"))
    movie.calculate_scenes_boundaries(segment_duration=2.0)

    assert movie.scenes[0].start_timing == 0
    assert movie.scenes[0].end_timing == 300
    assert movie.scenes[1].start_timing == 300
    assert movie.scenes[1].end_timing == 1200


def test_missing_mobile_scenes_do_not_raise_scraper_error():
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_no_scenes.html"))
    try:
        movie.calculate_scenes_boundaries(segment_duration=2.0)
    except ScraperError as exc:
        raise AssertionError("missing scene data must not raise ScraperError") from exc
