"""Connection responsiveness trial: WebSocket connects allowed; axis output blocked."""
from pathlib import Path
import os
import sys
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'dependencies')]
os.environ['LOCALAPPDATA']=str(ROOT/'profile')
from unittest.mock import patch
from contextlib import ExitStack,redirect_stdout,redirect_stderr
import tkinter as tk
from vector1a.app import VectorApp


def main():
    logs=ROOT/'profile/Vector1A/logs';logs.mkdir(parents=True,exist_ok=True)
    with open(os.devnull,'w') as quiet,(logs/'connection-preview-errors.log').open('a',encoding='utf-8',buffering=1) as errors,redirect_stdout(quiet),redirect_stderr(errors),ExitStack() as guards:
        guards.enter_context(patch('vector1a.network.ReStimWebSocketClient._send_message',return_value=False))
        for name in ('_auto_start_session','_auto_start_director','show_setup_guide'):
            guards.enter_context(patch.object(VectorApp,name,lambda self:None))
        for name in ('XInputController.start','FunscriptTimeline.request_media_poll','MFPListener.start'):
            guards.enter_context(patch('vector1a.app.'+name))
        guards.enter_context(patch('vector1a.civet.Civet.connect'))
        root=tk.Tk();app=VectorApp(root)
        root.title('Vector connection test — MOTION OUTPUT DISABLED')
        if '--smoke-test' in sys.argv:root.after(1000,app.close)
        root.mainloop()

if __name__=='__main__':main()
