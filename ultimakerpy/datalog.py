import csv
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

from .client import FutureResult, UMClient
from .timer import Timer


class DataLogger:

    def __init__(
            self, client: 'UMClient', output_csv: str,
            update_interval: float = 1.0, logging_interval: float = 1.0,
            timer_timeout: float = 600.) -> None:
        self._client = client
        self.output_csv = output_csv
        self.update_interval = update_interval
        self.logging_interval = logging_interval
        self._callbacks = []
        self.__valdict = None
        self.__thread_upd = None
        self.__loop_alive = False

        self.funcs = {'timestamp': lambda: datetime.now().timestamp()}
        self._timer = Timer(self, timeout=timer_timeout)

    def register(self, funcs: Callable[[], Any]) -> None:
        self.funcs.update(funcs)

    def get(self, *names: str) -> Any:
        self._timer.wait_for(lambda: self.__valdict is not None)
        valdict = self.__valdict.copy()
        if len(names) > 1:
            return tuple(valdict[name] for name in names)
        return valdict[names[0]]

    def get_all(self) -> Tuple[Any]:
        self._timer.wait_for(lambda: self.__valdict is not None)
        return tuple(self.__valdict.copy().values())

    @contextmanager
    def loop(self) -> None:
        try:
            f = open(self.output_csv, 'a', newline='')
            self.__writer = csv.writer(f)
            self.__writer.writerow(self.funcs.keys())

            self.__thread_upd = threading.Thread(target=self._update_loop)
            self.__thread_log = threading.Thread(target=self._logging_loop)
            self.__loop_alive = True
            self.__thread_upd.start()
            self.__thread_log.start()
            yield
        finally:
            self.__loop_alive = False
            self.__thread_upd.join()
            self.__thread_log.join()
            f.flush()
            f.close()

    def _update_loop(self) -> None:
        def main():
            with self._client.batch_mode():
                rets = [f() for f in self.funcs.values()]

            valdict = {}
            for ret, name in zip(rets, self.funcs.keys()):
                t = type(ret)
                if t in (list, tuple):
                    val = t((r.get() if type(r) == FutureResult else r \
                             for r in ret))
                else:
                    val = ret.get() if t == FutureResult else ret
                valdict[name] = val
            self.__valdict = valdict

            for cb in self._callbacks:
                cb()

        while self.__loop_alive:
            t1 = time.perf_counter()
            main()
            t2 = time.perf_counter()
            time.sleep(max(0, self.update_interval-(t2-t1)))

    def _logging_loop(self):
        def main():
            self.__writer.writerow(self.get_all())

        while self.__loop_alive:
            t1 = time.perf_counter()
            main()
            t2 = time.perf_counter()
            time.sleep(max(0, self.logging_interval-(t2-t1)))

    def get_timer(self) -> 'Timer':
        return self._timer

    def add_callback(self, func: Callable) -> None:
        self._callbacks.append(func)
