from __future__ import annotations

from types import SimpleNamespace

from aebn_dl.downloader import Downloader
from aebn_dl.exceptions import ScraperError
from aebn_dl.movie_scraper import Movie
from tests.helpers import MOVIE_URL, session_for


def _downloader(tmp_path, **kwargs) -> Downloader:
    return Downloader(
        url=MOVIE_URL,
        output_dir=str(tmp_path / "downloads"),
        work_dir=str(tmp_path / "work"),
        show_progress=False,
        **kwargs,
    )


def test_downloader_uses_env_dirs_instead_of_cwd(monkeypatch, tmp_path):
    output_dir = tmp_path / "configured-downloads"
    work_dir = tmp_path / "configured-work"
    monkeypatch.setenv("AEBNDL_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("AEBNDL_WORK_DIR", str(work_dir))
    monkeypatch.chdir(tmp_path)

    downloader = Downloader(url=MOVIE_URL, show_progress=False)

    assert downloader.output_dir == str(output_dir)
    assert downloader.work_dir == str(work_dir)


def test_scene_boundaries_only_required_when_user_requests_splits(tmp_path):
    assert _downloader(tmp_path)._scene_boundaries_required() is False
    assert _downloader(tmp_path, split_scenes=True)._scene_boundaries_required() is True
    assert _downloader(tmp_path, scene_n=1)._scene_boundaries_required() is True
    assert _downloader(tmp_path, no_metadata=False)._scene_boundaries_required() is False


def test_print_info_succeeds_when_mobile_scene_data_is_missing(monkeypatch, capsys, tmp_path):
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_no_scenes.html"))
    downloader = _downloader(tmp_path)
    monkeypatch.setattr(downloader, "_initialize_download", lambda: None)
    monkeypatch.setattr(downloader, "_scrape_movie_info", lambda: movie)

    def fake_process(scraped_movie, requires_scene_boundaries):
        downloader.manifest = SimpleNamespace(available_resolutions=[720], segment_duration=2.0)
        scraped_movie.calculate_scenes_boundaries(2.0)

    monkeypatch.setattr(downloader, "_process_manifest", fake_process)
    downloader.print_info()
    output = capsys.readouterr().out
    assert "Fixture Title" in output
    assert "Fixture Studio" in output


def test_process_manifest_does_not_raise_for_basic_download_without_scenes(monkeypatch, tmp_path):
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_no_scenes.html"))
    downloader = _downloader(tmp_path)
    downloader.session = movie._session

    class FakeManifest:
        segment_duration = 2.0

        def __init__(self, *_args, **_kwargs):
            return None

        def process_manifest(self):
            return None

    monkeypatch.setattr("aebn_dl.downloader.Manifest", FakeManifest)
    downloader._process_manifest(movie, requires_scene_boundaries=downloader._scene_boundaries_required())


def test_process_manifest_raises_when_split_scenes_requested_without_scene_data(monkeypatch, tmp_path):
    movie = Movie(MOVIE_URL, session_for(mobile_name="mobile_no_scenes.html"))
    downloader = _downloader(tmp_path, split_scenes=True)
    downloader.session = movie._session

    class FakeManifest:
        segment_duration = 2.0

        def __init__(self, *_args, **_kwargs):
            return None

        def process_manifest(self):
            return None

    monkeypatch.setattr("aebn_dl.downloader.Manifest", FakeManifest)
    try:
        downloader._process_manifest(movie, requires_scene_boundaries=True)
    except ScraperError:
        return
    raise AssertionError("split scenes without scene data should raise ScraperError")
