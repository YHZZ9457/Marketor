"""Deliver worker results on Tk's main thread, only while their owner exists."""
from queue import Empty, SimpleQueue
import sys
from typing import Any, Callable


class UIQueue:
    def __init__(self, root: Any):
        self.root = root
        self.pending: SimpleQueue = SimpleQueue()
        self.closed = False
        self.timer = root.after(40, self.drain)
        root.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event: Any) -> None:
        if event.widget is self.root:
            self.closed = True
            self.root.after_cancel(self.timer)

    def post(self, callback: Callable, *args: Any, owner: Any = None) -> None:
        # Workers must never call Tk, even root.after/winfo_exists.
        if not self.closed:
            self.pending.put((callback, args, owner))

    def drain(self) -> None:
        if self.closed:
            return
        for _ in range(100):
            try:
                callback, args, owner = self.pending.get_nowait()
            except Empty:
                break
            try:
                if owner is None or owner.winfo_exists():
                    callback(*args)
            except Exception:
                self.root.report_callback_exception(*sys.exc_info())
        if not self.closed:
            self.timer = self.root.after(40, self.drain)
