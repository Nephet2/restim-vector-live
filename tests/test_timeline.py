import json
from pathlib import Path

from vector1a.timeline import FunscriptTimeline


class FakeClock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now
    def advance(self, s): self.now += s


def make_script(path: Path):
    actions=[]
    # deliberately distinctive 20 s path
    points=[(0,10),(1000,90),(2500,20),(4000,80),(6000,30),(9000,95),(12000,15),(16000,70),(20000,40)]
    for at,pos in points: actions.append({'at':at,'pos':pos})
    path.write_text(json.dumps({'version':'1.0','inverted':False,'range':100,'actions':actions}))


def test_manual_preview_exposes_future(tmp_path):
    c=FakeClock(); path=tmp_path/'x.funscript'; make_script(path)
    t=FunscriptTimeline(clock=c)
    meta=t.load(str(path)); assert meta['actions']==9
    t.set_clock_mode(FunscriptTimeline.CLOCK_MANUAL)
    t.manual_seek(4.0)
    snap=t.snapshot()
    assert snap['synced'] is True
    assert snap['position_seconds']==4.0
    assert 'energy_band' in snap['next_10_seconds']
    assert 'energy_trend' in snap['next_30_seconds']
    assert snap['sync_confidence']==1.0


def test_manual_play_advances(tmp_path):
    c=FakeClock(); path=tmp_path/'x.funscript'; make_script(path)
    t=FunscriptTimeline(clock=c); t.load(str(path)); t.set_clock_mode(FunscriptTimeline.CLOCK_MANUAL)
    t.manual_seek(3); t.manual_play(); c.advance(2.5)
    assert abs(t.position_seconds()-5.5)<1e-6
    t.manual_pause(); c.advance(5)
    assert abs(t.position_seconds()-5.5)<1e-6


def test_mfp_pattern_sync_can_lock(tmp_path):
    c=FakeClock(); path=tmp_path/'x.funscript'; make_script(path)
    t=FunscriptTimeline(clock=c); t.load(str(path))
    # Feed interpolated samples corresponding to around script t=8..11 s.
    # Access interpolation only for deterministic test generation.
    with t._lock:
        vals=[t._interp_locked(8.0+i*0.1) for i in range(31)]
    for v in vals:
        t.observe_live(v, c())
        c.advance(0.1)
    snap=t.snapshot()
    assert snap['synced'] is True
    assert 9.0 <= snap['position_seconds'] <= 12.5
    assert snap['sync_confidence'] is not None


def test_bad_live_pattern_does_not_claim_confident_sync(tmp_path):
    c=FakeClock(); path=tmp_path/'x.funscript'; make_script(path)
    t=FunscriptTimeline(clock=c); t.load(str(path))
    # Extreme alternating pattern is intentionally unlike most of script.
    for i in range(40):
        t.observe_live(0.0 if i % 2 else 1.0, c()); c.advance(0.1)
    snap=t.snapshot()
    # It may find a loose local coincidence, but must not claim a high-confidence lock.
    assert (not snap['synced']) or (snap.get('sync_confidence') or 0) < 0.8


def test_direct_media_clock_is_authoritative_and_auto_loads(tmp_path, monkeypatch):
    from vector1a import timeline as timeline_module
    from vector1a.media_clock import MediaSnapshot

    media = tmp_path / 'Example Movie.mp4'
    media.write_bytes(b'')
    script = tmp_path / 'Example Movie.funscript'
    make_script(script)
    c = FakeClock()
    t = FunscriptTimeline(clock=c)
    t.configure_media(auto_load_script=True)
    t.set_clock_mode(FunscriptTimeline.CLOCK_VLC)

    monkeypatch.setattr(timeline_module, 'poll_vlc', lambda *a, **k: MediaSnapshot(
        'VLC', True, 'playing', 7.25, 20.0, 1.0, str(media), media.name))
    t._media_poll_worker(FunscriptTimeline.CLOCK_VLC, '127.0.0.1', 8080, '', 13579)
    snap = t.snapshot()
    assert snap['loaded'] is True
    assert snap['file'] == 'Example Movie.funscript'
    assert snap['position_seconds'] == 7.25
    assert snap['sync_confidence'] == 1.0
    assert snap['clock_authoritative'] is True
    assert snap['media_player'] == 'VLC'


def test_direct_media_seek_updates_without_pattern_reacquire(tmp_path, monkeypatch):
    from vector1a import timeline as timeline_module
    from vector1a.media_clock import MediaSnapshot
    media = tmp_path / 'Example Movie.mp4'; media.write_bytes(b'')
    script = tmp_path / 'Example Movie.funscript'; make_script(script)
    positions = iter([2.0, 16.0])
    monkeypatch.setattr(timeline_module, 'poll_vlc', lambda *a, **k: MediaSnapshot(
        'VLC', True, 'playing', next(positions), 20.0, 1.0, str(media), media.name))
    t = FunscriptTimeline(clock=FakeClock())
    t.configure_media(auto_load_script=True)
    t.set_clock_mode(FunscriptTimeline.CLOCK_VLC)
    t._media_poll_worker(FunscriptTimeline.CLOCK_VLC, '127.0.0.1', 8080, '', 13579)
    assert t.position_seconds() == 2.0
    t._media_poll_worker(FunscriptTimeline.CLOCK_VLC, '127.0.0.1', 8080, '', 13579)
    assert t.position_seconds() == 16.0


def test_direct_media_clock_extrapolates_between_polls(tmp_path, monkeypatch):
    from vector1a import timeline as timeline_module
    from vector1a.media_clock import MediaSnapshot
    media = tmp_path / 'Example Movie.mp4'; media.write_bytes(b'')
    script = tmp_path / 'Example Movie.funscript'; make_script(script)
    c = FakeClock()
    monkeypatch.setattr(timeline_module, 'poll_vlc', lambda *a, **k: MediaSnapshot(
        'VLC', True, 'playing', 5.0, 20.0, 1.0, str(media), media.name))
    t = FunscriptTimeline(clock=c)
    t.configure_media(auto_load_script=True)
    t.set_clock_mode(FunscriptTimeline.CLOCK_VLC)
    t._media_poll_worker(FunscriptTimeline.CLOCK_VLC, '127.0.0.1', 8080, '', 13579)
    assert t.position_seconds() == 5.0
    c.advance(2.5)
    assert abs(t.position_seconds() - 7.5) < 1e-6


def test_paused_direct_media_clock_does_not_extrapolate(tmp_path, monkeypatch):
    from vector1a import timeline as timeline_module
    from vector1a.media_clock import MediaSnapshot
    media = tmp_path / 'Example Movie.mp4'; media.write_bytes(b'')
    script = tmp_path / 'Example Movie.funscript'; make_script(script)
    c = FakeClock()
    monkeypatch.setattr(timeline_module, 'poll_vlc', lambda *a, **k: MediaSnapshot(
        'VLC', True, 'paused', 5.0, 20.0, 1.0, str(media), media.name))
    t = FunscriptTimeline(clock=c)
    t.configure_media(auto_load_script=True)
    t.set_clock_mode(FunscriptTimeline.CLOCK_VLC)
    t._media_poll_worker(FunscriptTimeline.CLOCK_VLC, '127.0.0.1', 8080, '', 13579)
    c.advance(4.0)
    assert t.position_seconds() == 5.0


def test_direct_clock_marks_repeated_playing_position_stale(tmp_path, monkeypatch):
    from vector1a import timeline as timeline_module
    from vector1a.media_clock import MediaSnapshot
    media = tmp_path / 'Example Movie.mp4'; media.write_bytes(b'')
    script = tmp_path / 'Example Movie.funscript'; make_script(script)
    c = FakeClock()
    monkeypatch.setattr(timeline_module, 'poll_mpc', lambda *a, **k: MediaSnapshot(
        'MPC', True, 'playing', 5.0, 20.0, 1.0, str(media), media.name,
        raw_position='5000', raw_duration='20000', position_source='position_ms'))
    t = FunscriptTimeline(clock=c)
    t.configure_media(auto_load_script=True)
    t.set_clock_mode(FunscriptTimeline.CLOCK_MPC)
    t._media_poll_worker(FunscriptTimeline.CLOCK_MPC, '127.0.0.1', 8080, '', 13579)
    c.advance(1.0)
    t._media_poll_worker(FunscriptTimeline.CLOCK_MPC, '127.0.0.1', 8080, '', 13579)
    assert t.metadata()['media_clock_health'] in {'checking', 'live'}
    c.advance(1.2)
    t._media_poll_worker(FunscriptTimeline.CLOCK_MPC, '127.0.0.1', 8080, '', 13579)
    snap = t.snapshot()
    assert snap['media_clock_health'] == 'stale'
    assert snap['clock_authoritative'] is False


def test_sample_position_reads_authored_future_without_moving_clock(tmp_path):
    import json
    from vector1a.timeline import FunscriptTimeline
    path = tmp_path / "tempo.funscript"
    path.write_text(json.dumps({"actions": [
        {"at": 0, "pos": 0}, {"at": 1000, "pos": 100}, {"at": 2000, "pos": 0}
    ]}), encoding="utf-8")
    tl = FunscriptTimeline(clock=lambda: 10.0)
    tl.load(str(path))
    assert abs(tl.sample_position(0.5) - 0.5) < 1e-9
    assert abs(tl.sample_position(1.5) - 0.5) < 1e-9
    assert tl.sample_position(99.0) == 0.0
