import unittest
from types import SimpleNamespace
from vector1a.app import VectorApp
from vector1a.passage import PassageController
from vector1a.director import DirectorBridge, DirectorRequest, DirectorServer
from vector1a.timeline import FunscriptTimeline
from vector1a.media_clock import MediaSnapshot


class PassageAPITests(unittest.TestCase):
    def setUp(self):
        self.app = VectorApp.__new__(VectorApp)
        self.app.director_bridge = DirectorBridge()
        self.app.passage = PassageController()
        self.app.engine = SimpleNamespace(control_state=lambda: {'engine_state': 'Running', 'output_enabled': True})

    def request(self, action, body):
        request = DirectorRequest('POST', '/v1/passage/'+action, body)
        self.app.director_bridge._requests.put(request)
        self.app._drain_director_requests()
        self.assertTrue(request.completed.is_set())
        return request

    def test_preview_has_no_effect_and_plan_requires_running_output(self):
        self.assertEqual(self.request('preview', {}).status, 200)
        self.assertFalse(self.app.passage.snapshot()['active'])
        self.app.engine.control_state = lambda: {'engine_state': 'Stopped', 'output_enabled': False}
        self.assertEqual(self.request('plan', {}).status, 400)
        self.assertFalse(self.app.passage.snapshot()['active'])

    def test_queue_plan_hold_resume_restore_and_invalid_numbers(self):
        p = self.request('plan', {'floor': .4}).response['passage']
        self.assertTrue(p['active']); self.assertIsNotNone(p['id'])
        self.assertTrue(self.request('hold', {}).response['passage']['held'])
        self.assertFalse(self.request('resume', {}).response['passage']['held'])
        self.assertIsNone(self.request('restore', {}).response['passage']['plan'])
        self.assertEqual(self.request('plan', {'peak': 2}).status, 400)

    def test_http_handler_admits_passage_endpoint_without_opening_a_socket(self):
        from io import BytesIO
        from vector1a.director import _Handler
        handler = _Handler.__new__(_Handler)
        handler.path = '/v1/passage/preview'
        handler.headers = {'Content-Length': '2'}
        handler.rfile = BytesIO(b'{}')
        handler.server = SimpleNamespace(bridge=SimpleNamespace(
            submit=lambda method, path, body: (lambda r: (r.status, r.response))(self.request(path.rsplit('/',1)[-1], body))))
        replies = []
        handler._send = lambda status, payload: replies.append((status, payload))
        handler.do_POST()
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(len(replies[0][1]['preview']), 101)

    def test_only_fresh_real_player_clock_can_drive_passage(self):
        now = [10.0]
        t = FunscriptTimeline(clock=lambda: now[0])
        t._clock_mode = t.CLOCK_MANUAL
        self.assertFalse(t.passage_transport()['valid'])
        t._clock_mode = t.CLOCK_MPC
        t._media_snapshot = MediaSnapshot('MPC-HC', True, state='playing', position_seconds=50)
        t._media_snapshot_received_at = 10
        t._media_clock_health = 'healthy'
        self.assertTrue(t.passage_transport()['valid'])
        now[0] = 15
        self.assertFalse(t.passage_transport()['valid'])


if __name__ == '__main__': unittest.main()
