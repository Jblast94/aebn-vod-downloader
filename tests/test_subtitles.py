from aebn_dl.subtitles import _shift_srt, extract_srt, format_timestamp, segments_to_srt


def test_format_timestamp_boundaries():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.234) == "00:00:01,234"
    assert format_timestamp(3661.5) == "01:01:01,500"


def test_extract_srt_from_segments():
    srt = extract_srt({"segments": [{"start": 0, "end": 1.5, "text": "Hello"}, {"start": 2, "end": 3, "text": "World"}]})
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello" in srt
    assert "2\n00:00:02,000 --> 00:00:03,000\nWorld" in srt


def test_shift_srt_offsets_timestamps():
    shifted = _shift_srt("1\n00:00:01,000 --> 00:00:02,000\nText", 60)
    assert shifted == "1\n00:01:01,000 --> 00:01:02,000\nText"


def test_segments_to_srt_skips_empty_segments():
    srt = segments_to_srt([{"start": 0, "end": 1, "text": ""}, {"start": 1, "end": 2, "text": "Kept"}])
    assert srt == "2\n00:00:01,000 --> 00:00:02,000\nKept"
