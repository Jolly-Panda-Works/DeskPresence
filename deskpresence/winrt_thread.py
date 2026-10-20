"""One thread for all WinRT calls (media sessions, Bluetooth).

WinRT objects belong to the COM apartment of the thread that created them. Calling them from
the tray thread, the Tk thread and worker threads mixed apartments and made DeskPresence hang
or crash (RPC_E_WRONG_THREAD, 0x8001010e). So every WinRT coroutine runs on this single
thread (multi-threaded apartment, its own event loop); other threads only submit work and wait.
"""
import asyncio
import ctypes
import logging
import threading

log = logging.getLogger(__name__)

_loop = None
_ready = threading.Event()
_lock = threading.Lock()


def _main():
    global _loop
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    except Exception:
        pass
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.call_soon(_ready.set)
    _loop.run_forever()


def _ensure():
    with _lock:
        if _loop is None:
            threading.Thread(target=_main, daemon=True, name="winrt").start()
    _ready.wait(5)


def on_winrt_thread():
    return _loop is not None and threading.current_thread().name == "winrt"


def run(coro_factory, timeout=15):
    """Runs coro_factory() on the WinRT thread and returns its result (raises on error/timeout)."""
    _ensure()
    if on_winrt_thread():
        raise RuntimeError("winrt_thread.run() called from the WinRT thread itself")
    future = asyncio.run_coroutine_threadsafe(coro_factory(), _loop)
    try:
        return future.result(timeout)
    except TimeoutError:
        future.cancel()
        raise


async def guarded(awaitable, timeout):
    """Awaits a WinRT operation for at most `timeout` seconds.

    Windows sometimes never finishes an operation (the media-control service can stop answering).
    asyncio.wait_for() would then try to cancel it, and that cancellation never finishes either,
    so instead the operation is left running and a TimeoutError is raised.
    """
    task = asyncio.ensure_future(awaitable)
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task not in done:
        raise TimeoutError("Windows did not answer in time")
    return task.result()


def submit(coro_factory):
    """Starts coro_factory() on the WinRT thread without waiting for it."""
    _ensure()
    return asyncio.run_coroutine_threadsafe(coro_factory(), _loop)
