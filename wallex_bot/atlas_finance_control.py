"""Original local research control over Atlas frozen study and lease.

No arbitrary command/path, key discovery, live ARM or financial request.
Public network is used only after explicit Shadow Start.
"""
import threading
import time
from . import atlas_finance as finance


class FinanceControl:
    def __init__(self,root):
        self.root=root;self.lock=threading.Lock();self.worker=None
        self.stop=threading.Event();self.last={'status':'IDLE'}

    def state(self):
        return {**self.last,'running_in_this_server':bool(self.worker and self.worker.is_alive())}

    def command(self,action):
        if action not in ('start','stop','backtest'):raise ValueError('RESEARCH_ACTION_NOT_ALLOWED')
        with self.lock:
            if action=='stop':
                result=finance.stop_shadow(self.root);self.stop.set();return result
            if self.worker and self.worker.is_alive():raise ValueError('RESEARCH_ALREADY_RUNNING')
            if action=='backtest':return finance.backtest(self.root)
            finance.prepare_shadow(self.root)
            self.stop=threading.Event();self.last={'status':'STARTING','started_epoch':time.time()}
            def work():
                try:
                    finance.run_shadow(self.root,seconds=120,resume=True,stop=self.stop)
                    self.last={'status':'STOPPED','finished_epoch':time.time()}
                except Exception as exc:
                    self.last={'status':'BLOCKED','error_type':type(exc).__name__,'finished_epoch':time.time()}
            self.worker=threading.Thread(target=work,name='console-shadow',daemon=False)
            self.worker.start();return self.state()

    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=30)
