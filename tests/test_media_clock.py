from pathlib import Path
from vector1a.media_clock import find_matching_funscript, _file_uri_to_path, _parse_clock_value


def test_script_resolver_prefers_media_sibling(tmp_path):
    media = tmp_path/'Movie.mp4'; media.write_bytes(b'')
    script = tmp_path/'Movie.funscript'; script.write_text('{}')
    lib = tmp_path/'library'; lib.mkdir(); (lib/'Movie.funscript').write_text('{}')
    assert find_matching_funscript(str(media), [str(lib)]) == str(script.resolve())


def test_script_resolver_searches_library_recursively(tmp_path):
    media_dir = tmp_path/'media'; media_dir.mkdir(); media = media_dir/'Movie.mp4'; media.write_bytes(b'')
    lib = tmp_path/'library'; nested = lib/'nested'; nested.mkdir(parents=True)
    script = nested/'Movie.funscript'; script.write_text('{}')
    assert find_matching_funscript(str(media), [str(lib)]) == str(script.resolve())


def test_clock_string_parser():
    assert _parse_clock_value('01:02:03') == 3723.0
    assert _parse_clock_value('02:30') == 150.0
    assert _parse_clock_value('12.5') == 12.5


def test_mpc_numeric_variables_are_milliseconds(monkeypatch):
    from vector1a import media_clock as mc
    html = '''<html><body>
    <p id="filepath">C:\\Media\\Example.mp4</p>
    <p id="state">2</p><p id="statestring">Playing</p>
    <p id="position">8922383</p><p id="positionstring">02:28:42</p>
    <p id="duration">10000000</p><p id="durationstring">02:46:40</p>
    <p id="playbackrate">1</p></body></html>'''
    monkeypatch.setattr(mc, '_http_text', lambda *a, **k: html)
    snap = mc.poll_mpc()
    assert snap.connected is True
    assert snap.state == 'playing'
    assert abs(snap.position_seconds - 8922.383) < 1e-9
    assert abs(snap.duration_seconds - 10000.0) < 1e-9
    assert snap.raw_position == '8922383'
    assert snap.position_source == 'position_ms'


def test_mpc_state_uses_numeric_code_when_statestring_is_localized(monkeypatch):
    from vector1a import media_clock as mc
    html = '''<html><body>
    <p id="state">2</p><p id="statestring">Wiedergabe</p>
    <p id="position">1000</p><p id="duration">2000</p>
    </body></html>'''
    monkeypatch.setattr(mc, '_http_text', lambda *a, **k: html)
    snap = mc.poll_mpc()
    assert snap.state == 'playing'
