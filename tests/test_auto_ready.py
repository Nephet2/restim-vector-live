import unittest
from unittest.mock import Mock, patch
from vector1a.app import VectorApp


class AutoReadyTests(unittest.TestCase):
    def app(self, enabled):
        app = object.__new__(VectorApp)
        app.automatic_ready = Mock(get=lambda: enabled)
        for name in ('auto_start_mfp', 'auto_start_restim', 'auto_start_prostate'):
            setattr(app, name, Mock(get=lambda: False))
        app.start_listener = Mock()
        app.resume = Mock()
        app.restim_host = Mock(get=lambda: '127.0.0.1')
        app.restim_port = Mock(get=lambda: 12346)
        app.restim = Mock(connected=False)
        app._automatic_ready_stop = Mock()
        app._automatic_ready_stop.is_set.return_value = False
        app._automatic_ready_stop.wait.return_value = True
        return app

    def test_enabled_starts_listener_resumes_and_connects(self):
        app = self.app(True)
        with patch('vector1a.app.threading.Thread') as thread:
            app._auto_start_session()
            app.start_listener.assert_called_once()
            app.resume.assert_called_once()
            thread.call_args.kwargs['target']()
        app.restim.connect.assert_called_once_with('127.0.0.1', 12346)

    def test_disabled_preserves_manual_startup(self):
        app = self.app(False)
        with patch('vector1a.app.threading.Thread') as thread:
            app._auto_start_session()
            thread.assert_not_called()
        app.start_listener.assert_not_called()
        app.resume.assert_not_called()
