import unittest
from unittest.mock import Mock, patch
from vector1a.endpoints import Endpoint, validate_output_endpoints
from vector1a.app import VectorApp

class EndpointTests(unittest.TestCase):
    def test_separate_local_ports(self):
        a,b=validate_output_endpoints('127.0.0.1',12355,'127.0.0.1',12350)
        self.assertNotEqual(a,b)

    def test_duplicate_loopback_aliases(self):
        for host in ('localhost','LOCALHOST.','127.0.0.1','127.0.0.2','::1','[::1]','::ffff:127.0.0.1'):
            with self.subTest(host=host),self.assertRaisesRegex(ValueError,'same ReStim destination'):
                validate_output_endpoints(host,12350,'127.0.0.1',12350)

    def test_hostname_normalization(self):
        self.assertEqual(Endpoint.parse(' Device.Example. ',12350),Endpoint.parse('device.example','12350'))
        self.assertNotEqual(Endpoint.parse('device-a',12350),Endpoint.parse('device-b',12350))

    def test_bad_hosts_and_ports(self):
        for host,port in (('',12350),('localhost',0),('localhost',65536),('localhost','bad'),('localhost',1.5)):
            with self.subTest(host=host,port=port),self.assertRaises(ValueError):Endpoint.parse(host,port)

class ConnectionGuardTests(unittest.TestCase):
    def app(self,duplicate=True):
        app=object.__new__(VectorApp)
        for name,value in dict(restim_host='localhost',restim_port=12350 if duplicate else 12355,
                               prostate_host='127.0.0.1',prostate_port=12350).items():
            setattr(app,name,Mock(get=Mock(return_value=value)))
        app.session_ready_status=Mock();app._set_startup_status=Mock()
        app._connection_actions={'primary':Mock(),'secondary':Mock()}
        app._startup_in_progress=False
        app.start_listener=Mock();app.resume=Mock();app.orchestrator=Mock();app._save_settings=Mock()
        return app

    def test_manual_connects_block_duplicate_without_worker_commands(self):
        for method in ('connect_restim','connect_prostate'):
            app=self.app()
            with patch('vector1a.app.messagebox.showerror') as error:
                getattr(app,method)()
                error.assert_called_once()
            for lane in app._connection_actions.values():lane.submit.assert_not_called()
            app.session_ready_status.set.assert_called_with('SESSION: CHECK OUTPUT DESTINATIONS')

    def test_auto_start_blocks_before_resume_launch_or_thread(self):
        for method in ('_auto_start_session','_launch_session_apps'):
            app=self.app()
            with patch('vector1a.app.threading.Thread') as thread,patch('vector1a.app.messagebox.showerror') as error:
                getattr(app,method)()
                thread.assert_not_called();error.assert_not_called()
            app.start_listener.assert_not_called();app.resume.assert_not_called()
            app.orchestrator.launch.assert_not_called();app._save_settings.assert_not_called()

    def test_valid_manual_destinations_preserve_original_values(self):
        app=self.app(False)
        app.connect_restim();app.connect_prostate()
        app._connection_actions['primary'].submit.assert_called_once_with('connect','localhost',12355)
        app._connection_actions['secondary'].submit.assert_called_once_with('connect','127.0.0.1',12350)

if __name__=='__main__':unittest.main()
