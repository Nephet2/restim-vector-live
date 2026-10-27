import threading,time
from types import SimpleNamespace as NS
from unittest.mock import Mock
from vector1a.network import ReStimWebSocketClient
from vector1a.connection_actions import ConnectionActions
from vector1a.app import VectorApp


def test_health_never_waits_for_inflight_socket_attempt():
    client=ReStimWebSocketClient(lambda text:None)
    client._closed.set()
    entered=threading.Event();release=threading.Event()
    def hold():
        with client._locked():
            entered.set();release.wait(2)
    worker=threading.Thread(target=hold);worker.start()
    try:
        assert entered.wait(1)
        start=time.monotonic();health=client.health();duration=time.monotonic()-start
        assert duration<.1
        assert health['connected'] is False
    finally:
        release.set();worker.join(1);client.close()


def test_connect_click_reads_tk_values_on_caller_and_returns_while_attempt_blocks():
    entered=threading.Event();release=threading.Event();caller=threading.get_ident();seen=[]
    class Var:
        def __init__(self,value):self.value=value
        def get(self):
            assert threading.get_ident()==caller
            return self.value
    def connect(host,port):
        seen.append((host,port));entered.set();release.wait(2)
    actions=ConnectionActions(NS(connect=connect,disconnect=lambda:None),lambda text:None,'test')
    app=object.__new__(VectorApp);app._connection_actions={'primary':actions}
    app.restim_host=Var('127.0.0.1');app.restim_port=Var(12368)
    try:
        start=time.monotonic();app.connect_restim();assert time.monotonic()-start<.1
        assert entered.wait(1);assert seen==[('127.0.0.1',12368)]
    finally:release.set();actions.close();actions._worker.join(1)


def test_latest_pending_endpoint_wins_and_disconnect_cancels_retries():
    entered=threading.Event();release=threading.Event();done=threading.Event();calls=[]
    def connect(host,port):
        calls.append(('connect',port))
        if port==1:entered.set();release.wait(2)
        else:done.set()
    def disconnect():calls.append(('disconnect',None));done.set()
    actions=ConnectionActions(NS(connect=connect,disconnect=disconnect),lambda text:None,'test')
    try:
        actions.submit('connect','localhost',1);assert entered.wait(1)
        actions.submit('connect','localhost',2);actions.submit('connect','localhost',3)
        release.set();assert done.wait(1)
        assert calls==[('connect',1),('connect',3)]
        done.clear();actions.submit('disconnect');assert done.wait(1)
        assert calls[-1]==('disconnect',None)
    finally:release.set();actions.close();actions._worker.join(1)


def test_pending_connect_is_discarded_on_close():
    entered=threading.Event();release=threading.Event();calls=[]
    def connect(host,port):calls.append(port);entered.set();release.wait(2)
    actions=ConnectionActions(NS(connect=connect),lambda text:None,'test')
    actions.submit('connect','localhost',1);assert entered.wait(1)
    actions.submit('connect','localhost',2);actions.close();release.set();actions._worker.join(1)
    assert calls==[1]


def test_closed_client_cannot_reopen_from_a_late_ui_command():
    client=ReStimWebSocketClient(lambda text:None)
    client.close()
    client._connect_now=Mock()
    try:client.connect('127.0.0.1',12368)
    except OSError:pass
    else:raise AssertionError('Closed client accepted a connection')
    client._connect_now.assert_not_called()


def test_session_startup_handshake_runs_off_ui_thread_before_ready():
    from unittest.mock import patch
    caller=threading.get_ident();entered=threading.Event();release=threading.Event();finished=threading.Event();callbacks=[]
    class Var:
        def __init__(self,value):self.value=value
        def get(self):
            assert threading.get_ident()==caller
            return self.value
        def set(self,value):self.value=value
    app=object.__new__(VectorApp);app._startup_in_progress=False
    for key,value in dict(auto_start_mfp=False,auto_start_restim=True,auto_start_prostate=False,
                          mfp_launch_target='',restim_launch_target='',prostate_launch_target='',
                          restim_host='127.0.0.1',prostate_host='127.0.0.1',restim_port=12368,prostate_port=12350,
                          session_ready_status='SESSION: MANUAL').items():setattr(app,key,Var(value))
    def connect(host,port):
        assert threading.get_ident()!=caller
        entered.set();release.wait(2)
    def after(delay,callback):callbacks.append(callback);finished.set()
    app.restim=NS(connected=False,connect=connect);app.prostate_restim=NS(connected=False)
    app.root=NS(after=after);app._set_startup_status=Mock();app._save_settings=Mock()
    try:
        with patch('vector1a.app.port_is_open',return_value=True):
            start=time.monotonic();app._launch_session_apps();assert time.monotonic()-start<.1
            assert entered.wait(1);assert app.session_ready_status.value=='SESSION: STARTING'
            assert not finished.is_set();release.set();assert finished.wait(1)
        callbacks[0]();assert app.session_ready_status.value=='SESSION: READY'
    finally:release.set()
