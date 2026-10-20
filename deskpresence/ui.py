"""Tk-based UI: notification popups on a chosen monitor + gaze calibration.

Tk lives on the main thread; other threads call UI methods, which are queued.
"""
import logging
import queue
import statistics
import tkinter as tk

log = logging.getLogger(__name__)

FONT = "Segoe UI"
BG, FG, SUB, ACCENT = "#1f2430", "#ffffff", "#b8c0d0", "#4f8cff"


class UI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._q = queue.Queue()
        self._popups = []
        self.root.after(100, self._pump)

    # ------------------------------------------------------------ plumbing
    def call(self, fn, *args):
        self._q.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    log.exception("UI call failed")
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def run(self):
        self.root.mainloop()

    def quit(self):
        self.call(self.root.quit)

    # ------------------------------------------------------------ popups
    def popup(self, title, body, monitor, seconds=7, source=""):
        self.call(self._popup, title, body, monitor, seconds, source)

    def _popup(self, title, body, monitor, seconds, source):
        w = 380
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        frame = tk.Frame(win, bg=BG, highlightthickness=1, highlightbackground=ACCENT)
        frame.pack(fill="both", expand=True)
        if source:
            tk.Label(frame, text=source, bg=BG, fg=ACCENT, font=(FONT, 9), anchor="e",
                     justify="right").pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(frame, text=title, bg=BG, fg=FG, font=(FONT, 11, "bold"), anchor="e",
                 justify="right", wraplength=w - 24).pack(fill="x", padx=12, pady=(6, 2))
        if body:
            tk.Label(frame, text=body, bg=BG, fg=SUB, font=(FONT, 10), anchor="e",
                     justify="right", wraplength=w - 24).pack(fill="x", padx=12, pady=(0, 12))
        win.update_idletasks()
        h = win.winfo_reqheight()

        l, t, r, b = monitor.work
        self._popups = [p for p in self._popups if p.winfo_exists()]
        y = b - 12 - h - sum(p.winfo_height() + 8 for p in self._popups)
        y = max(t + 12, y)
        win.geometry(f"{w}x{h}+{r - w - 12}+{y}")
        self._popups.append(win)

        def close(_e=None):
            if win.winfo_exists():
                win.destroy()
        for wdg in [win, frame, *frame.winfo_children()]:
            wdg.bind("<Button-1>", close)
        win.after(int(seconds * 1000), close)

    # ------------------------------------------------------------ calibration
    def calibrate(self, targets, sample_fn, on_done):
        """targets: list of (name, text, monitor). sample_fn() -> (yaw, pitch) | None."""
        self.call(self._calibrate, targets, sample_fn, on_done)

    def _calibrate(self, targets, sample_fn, on_done):
        results = {}

        def step(i):
            if i >= len(targets):
                on_done(results)
                return
            name, text, mon = targets[i]
            l, t, r, b = mon.rect
            win = tk.Toplevel(self.root, bg=BG)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.geometry(f"{r - l}x{b - t}+{l}+{t}")
            cv = tk.Canvas(win, bg=BG, highlightthickness=0)
            cv.pack(fill="both", expand=True)
            cx, cy = (r - l) // 2, (b - t) // 2
            cv.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, fill=ACCENT, outline="")
            cv.create_text(cx, cy - 80, text=text, fill=FG, font=(FONT, 26, "bold"))
            cv.create_text(cx, cy + 70, text="صورتتان را به سمت این نقطه بچرخانید و ثابت بمانید",
                           fill=SUB, font=(FONT, 14))
            info = cv.create_text(cx, cy + 120, text="آماده...", fill=SUB, font=(FONT, 12))
            cv.create_text(cx, b - t - 40, text=f"{i + 1} / {len(targets)}   (Esc = لغو)",
                           fill=SUB, font=(FONT, 10))
            samples = []
            state = {"cancel": False}

            def cancel(_e=None):
                state["cancel"] = True
            win.bind("<Escape>", cancel)
            win.focus_force()

            def collect(left_ms):
                if state["cancel"]:
                    win.destroy()
                    on_done(None)
                    return
                s = sample_fn()
                if s:
                    samples.append(s)
                cv.itemconfigure(info, text=f"در حال ثبت... {len(samples)}")
                if left_ms > 0:
                    win.after(100, collect, left_ms - 100)
                else:
                    finish()

            def finish():
                win.destroy()
                if len(samples) >= 8:
                    results[name] = [statistics.median(s[0] for s in samples),
                                     statistics.median(s[1] for s in samples)]
                else:
                    results[name] = None
                step(i + 1)

            win.after(1800, collect, 2500)

        step(0)
