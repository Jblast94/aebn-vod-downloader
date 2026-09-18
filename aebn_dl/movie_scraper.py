from __future__ import annotations

import logging
import math

from lxml import html

from . import utils
from .custom_session import CustomSession
from .exceptions import ScraperError
from .models import Scene

logger = logging.getLogger(__name__)

MOBILE_SCENE_XPATHS = (
    '//div[@class="scroller"]',
    '//div[contains(concat(" ", normalize-space(@class), " "), " scroller ")]',
    '//*[@data-time-start][@data-time-duration]',
)


class Movie:
    def __init__(self, url: str, session: CustomSession):
        self.input_url = url
        self._session = session
        self.url_content_type: str | None = None
        self.movie_id: str | None = None
        self.studio_name: str | None = None
        self.title: str | None = None
        self.total_duration_seconds: int | None = None
        self.performers: list | None = None
        self.scenes: list[Scene] = []
        self.cover_url_front: str | None = None
        self.cover_url_back: str | None = None
        self.scenes_boundaries = []
        for sex_pref_subdomain in ("straight", "gay"):
            self._session.cookies.set(
                name="ageGated",
                value="true",
                domain=f"{sex_pref_subdomain}.aebn.com",
                path="/",
                secure=True,
            )
        self._scrape_info()

    def _scrape_info(self):
        """Scrape movie metadata from aebn.com"""
        response = self._session.get(self.input_url)
        content = html.fromstring(response.content)

        if "dts-yoti-verification" in response.text or "Age Verification Required" in response.text:
            raise RuntimeError("Age verification (Yoti) required. Your IP appears to be from a US state that requires age verification. Use a proxy from a different location with -p/--proxy option.")

        self.url_content_type = self.input_url.split("/")[3]
        self.movie_id = self.input_url.split("/")[5]
        self.studio_name = self._extract_studio_name(content)

        titles = content.xpath('//*[@class="dts-section-page-heading-title"]/h1/text()')
        if not titles:
            raise ScraperError("Could not scrape movie title — AEBN page structure may have changed.")
        self.title = titles[0].strip()

        durations = content.xpath('//*[@class="section-detail-list-item-duration"][2]/text()')
        if not durations:
            raise ScraperError("Could not scrape movie duration — AEBN page structure may have changed.")
        total_duration_string = durations[0].strip()
        self.total_duration_seconds = utils.duration_to_seconds(total_duration_string)

        self.studio_name = utils.remove_chars(self.studio_name)
        self.title = utils.remove_chars(self.title)
        self.performers = content.xpath('//section[contains(@class, "dts-section-page-detail-info-movie")]//div[@class="dts-detail-movie-stars"]//@title')
        scene_elements = content.xpath('//section[@id[starts-with(., "scene")]]')
        for scene_element in scene_elements:
            scene_performers = scene_element.xpath('.//div[@class="dts-detail-movie-stars"]//@title')
            scene = Scene(performers=scene_performers)
            self.scenes.append(scene)

        cover_fronts = content.xpath('//*[@class="dts-movie-boxcover-front"]//img/@src')
        if not cover_fronts:
            raise ScraperError("Could not scrape front cover URL — AEBN page structure may have changed.")
        self.cover_url_front = "https:" + cover_fronts[0].strip().split("?")[0]

        cover_backs = content.xpath('//*[@class="dts-movie-boxcover-background"]//img/@src')
        if not cover_backs:
            raise ScraperError("Could not scrape back cover URL — AEBN page structure may have changed.")
        self.cover_url_back = "https:" + cover_backs[0].strip().split("?")[0]

    def _extract_studio_name(self, content) -> str:
        studio_names = content.xpath('//*[@class="section-detail-list-item-studio"]/a/text()')
        if len(studio_names) > 0:
            return studio_names[0].replace(",", "").strip()
        return ""

    def has_scene_timings(self) -> bool:
        return any(scene.start_timing is not None and scene.end_timing is not None for scene in self.scenes)

    def calculate_scenes_boundaries(self, segment_duration: float):
        """Calculate scene segment boundaries with data from m.aebn.net.

        Missing or unrecognized mobile scene markup is treated as empty: log a
        warning and continue so metadata/info and full-title downloads still work.
        """
        response = self._session.get(f"https://m.aebn.net/movie/{self.movie_id}")
        html_tree = html.fromstring(response.content)
        scene_elems = []
        for xpath in MOBILE_SCENE_XPATHS:
            scene_elems = html_tree.xpath(xpath)
            if scene_elems:
                break
        if not scene_elems:
            logger.warning("No scene data found on mobile AEBN page; continuing without scene boundaries")
            return
        if not self.scenes:
            self.scenes = [Scene(performers=[]) for _ in scene_elems]
        elif len(scene_elems) != len(self.scenes):
            logger.warning("Scene count mismatch: mobile=%s, movie=%s; using overlapping scenes only", len(scene_elems), len(self.scenes))
        for i, scene_el in enumerate(scene_elems):
            if i >= len(self.scenes):
                break
            target_scene = self.scenes[i]
            time_start = scene_el.get("data-time-start")
            time_duration = scene_el.get("data-time-duration")
            if time_start is None or time_duration is None:
                logger.warning("Scene %s is missing timing attributes; skipping", i + 1)
                continue
            target_scene.start_timing = int(time_start)
            target_scene.end_timing = target_scene.start_timing + int(time_duration)
            target_scene.start_segment = math.floor(int(target_scene.start_timing) / segment_duration)
            target_scene.end_segment = math.ceil(int(target_scene.end_timing) / segment_duration) - 1
