"""Tk-based UI: notification popups, the break screen, gaze calibration and About.

Tk lives on the main thread; other threads call UI methods, which are queued.
Colours match the dark + orange palette of Image Format Converter and SnapshotAll.
"""
import logging
import os
import queue
import statistics
import sys
import time
import tkinter as tk
import webbrowser

from . import APP_AUTHOR, APP_NAME, APP_REPO, APP_VERSION, APP_WEBSITE
from .i18n import is_rtl, t

log = logging.getLogger(__name__)

# Palette (same values as SnapshotAll / Image Format Converter)
BG = "#110D0A"
TOOLBAR = "#16110D"
PANEL = "#1F1813"
PANEL_H = "#2B221B"
BORDER = "#3A2E24"
FG = "#F5EEE8"
MUTED = "#A99B8E"
ORANGE = "#F97316"
ORANGE_H = "#FB923C"
ON_ORANGE = "#1A0E05"
DANGER = "#F87171"
FAINT_TEXT = "#6E6259"
FONT = "Segoe UI"


def asset_path(name):
    for base in (getattr(sys, "_MEIPASS", ""), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
        p = os.path.join(base, "assets", name)
        if os.path.exists(p):
            return p
    return None


def _align():
    """(anchor, justify) for the current language direction."""
    return ("e", "right") if is_rtl() else ("w", "left")


def style_titlebar(win, color=None, text=FG):
    """Paint the native title bar in the app's color (Windows 11), as in SnapshotAll."""
    color = color or TOOLBAR
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()

        def colorref(hex_color):  # COLORREF is 0x00BBGGRR
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
            return r | (g << 8) | (b << 16)

        def set_attr(attr, value):
            v = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        set_attr(20, 1)                  # DWMWA_USE_IMMERSIVE_DARK_MODE
        set_attr(34, colorref(color))    # DWMWA_BORDER_COLOR
        set_attr(35, colorref(color))    # DWMWA_CAPTION_COLOR
        set_attr(36, colorref(text))     # DWMWA_TEXT_COLOR
    except Exception:
        pass


class UI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        # errors in button handlers etc. go to log.txt (a windowed exe has no console to print to)
        self.root.report_callback_exception = lambda *exc: log.error("UI error", exc_info=exc)
        self._q = queue.Queue()
        self._popups = []
        self._break_wins = []
        self._fade = []  # [(window, canvas, monitor)] of the away countdown
        self._break_time_labels = []
        self._break_status_labels = []
        self._skip_armed_at = 0.0
        self._about = None
        self._logo = None
        ico = asset_path("icon.ico")
        if ico:
            try:
                self.root.iconbitmap(default=ico)
            except tk.TclError:
                pass
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
        anchor, justify = _align()
        win = tk.Toplevel(self.root, bg=BORDER)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(frame, bg=ORANGE, height=3).pack(fill="x")
        tk.Label(frame, text=(source or APP_NAME).upper(),
                 bg=PANEL, fg=ORANGE, font=(FONT, 8, "bold"), anchor=anchor,
                 justify=justify).pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(frame, text=title, bg=PANEL, fg=FG, font=(FONT, 11, "bold"), anchor=anchor,
                 justify=justify, wraplength=w - 28).pack(fill="x", padx=14, pady=(4, 2))
        if body:
            tk.Label(frame, text=body, bg=PANEL, fg=MUTED, font=(FONT, 10), anchor=anchor,
                     justify=justify, wraplength=w - 28).pack(fill="x", padx=14, pady=(0, 12))
        else:
            tk.Frame(frame, bg=PANEL, height=8).pack()
        win.update_idletasks()
        h = win.winfo_reqheight()

        l, t_, r, b = monitor.work
        self._popups = [p for p in self._popups if p.winfo_exists()]
        y = b - 12 - h - sum(p.winfo_height() + 8 for p in self._popups)
        y = max(t_ + 12, y)
        win.geometry(f"{w}x{h}+{r - w - 12}+{y}")
        self._popups.append(win)

        def close(_e=None):
            if win.winfo_exists():
                win.destroy()

        def bind_all(widget):
            widget.bind("<Button-1>", close)
            for c in widget.winfo_children():
                bind_all(c)
        bind_all(win)
        win.after(int(seconds * 1000), close)

    # ------------------------------------------------------------ question box
    def ask(self, title, body, yes_text, no_text, callback, monitor, timeout=45):
        """Small topmost question on `monitor`; callback(True / False, or None when not answered in time)."""
        self.call(self._ask, title, body, yes_text, no_text, callback, monitor, timeout)

    def _ask(self, title, body, yes_text, no_text, callback, monitor, timeout):
        anchor, justify = _align()
        w = 420
        win = tk.Toplevel(self.root, bg=BORDER)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(frame, bg=ORANGE, height=3).pack(fill="x")
        tk.Label(frame, text=APP_NAME.upper(), bg=PANEL, fg=ORANGE, font=(FONT, 8, "bold"),
                 anchor=anchor).pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(frame, text=title, bg=PANEL, fg=FG, font=(FONT, 12, "bold"), anchor=anchor,
                 justify=justify, wraplength=w - 32).pack(fill="x", padx=16, pady=(4, 2))
        tk.Label(frame, text=body, bg=PANEL, fg=MUTED, font=(FONT, 10), anchor=anchor,
                 justify=justify, wraplength=w - 32).pack(fill="x", padx=16, pady=(0, 12))
        row = tk.Frame(frame, bg=PANEL)
        row.pack(fill="x", padx=16, pady=(0, 14))
        done = {"v": False}

        def answer(value):
            if done["v"]:
                return
            done["v"] = True
            if win.winfo_exists():
                win.destroy()
            callback(value)

        side = "left" if is_rtl() else "right"
        tk.Button(row, text=yes_text, command=lambda: answer(True), bg=ORANGE, fg=ON_ORANGE,
                  activebackground=ORANGE_H, activeforeground=ON_ORANGE, relief="flat", bd=0,
                  font=(FONT, 10, "bold"), padx=16, pady=6, cursor="hand2").pack(side=side)
        tk.Button(row, text=no_text, command=lambda: answer(False), bg=PANEL_H, fg=FG,
                  activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                  font=(FONT, 10), padx=16, pady=6, cursor="hand2").pack(side=side, padx=8)
        win.update_idletasks()
        h = win.winfo_reqheight()
        l, t_, r, b = monitor.work
        win.geometry(f"{w}x{h}+{r - w - 12}+{b - h - 12}")
        win.after(int(timeout * 1000), lambda: answer(None))

    # ------------------------------------------------------------ away countdown + fade to black
    def away_countdown(self, seconds_left, darkness, monitors):
        """Countdown on every monitor; darkness 0..1 dims the screens toward black."""
        self.call(self._away_countdown, seconds_left, darkness, monitors)

    def away_countdown_hide(self):
        self.call(self._away_countdown_hide)

    @staticmethod
    def _click_through(win):
        """Let clicks and typing pass through the overlay to the windows below."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE =                 -20, 0x80000, 0x20, 0x80, 0x08000000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                  style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        except Exception:
            log.debug("click-through failed", exc_info=True)

    def _away_countdown(self, seconds_left, darkness, monitors):
        if not self._fade:
            for mon in monitors:
                l, t_, r, b = mon.rect
                win = tk.Toplevel(self.root, bg="black")
                win.overrideredirect(True)
                win.attributes("-topmost", True)
                win.attributes("-alpha", 0.0)
                win.geometry(f"{r - l}x{b - t_}+{l}+{t_}")
                cv = tk.Canvas(win, bg="black", highlightthickness=0)
                cv.pack(fill="both", expand=True)
                cx, cy = (r - l) // 2, (b - t_) // 2
                cv.create_oval(cx - 90, cy - 90, cx + 90, cy + 90, outline=ORANGE, width=4, tags="ring")
                cv.create_text(cx, cy, text="", fill=FG, font=(FONT, 72, "bold"), tags="num")
                cv.create_text(cx, cy - 140, text="", fill=FG, font=(FONT, 20, "bold"), tags="title")
                cv.create_text(cx, cy + 140, text=t("countdown.hint"), fill=MUTED, font=(FONT, 13))
                win.update_idletasks()
                self._click_through(win)
                self._fade.append((win, cv, (cx, cy)))
        n = max(0, int(seconds_left + 0.999))
        # the countdown stays readable while the screen behind it fades toward black
        alpha = max(0.35, min(0.95, 0.35 + darkness * 0.6))
        for win, cv, (cx, cy) in self._fade:
            try:
                win.attributes("-alpha", alpha)
                win.attributes("-topmost", True)
                cv.itemconfigure("num", text=str(n))
                cv.itemconfigure("title", text=t("countdown.title", n=n))
                # the ring empties as the time runs out
                cv.delete("arc")
                if darkness < 1:
                    cv.create_arc(cx - 90, cy - 90, cx + 90, cy + 90, start=90, extent=-360 * (1 - darkness),
                                  style="arc", outline=ORANGE, width=8, tags="arc")
            except tk.TclError:
                pass

    def _away_countdown_hide(self):
        for win, _cv, _c in self._fade:
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._fade = []

    # ------------------------------------------------------------ forced break cover
    def break_show(self, monitors, allow_skip, on_skip):
        self.call(self._break_show, monitors, allow_skip, on_skip)

    def break_update(self, seconds_left, counting):
        self.call(self._break_update, seconds_left, counting)

    def break_hide(self):
        self.call(self._break_hide)

    def _break_show(self, monitors, allow_skip, on_skip):
        if self._break_wins:
            return
        for m in monitors:
            l, t_, r, b = m.rect
            win = tk.Toplevel(self.root, bg=BG)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.geometry(f"{r - l}x{b - t_}+{l}+{t_}")
            win.protocol("WM_DELETE_WINDOW", lambda: None)  # ignore Alt+F4
            box = tk.Frame(win, bg=BG)
            box.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(box, text=t("break.title"), bg=BG, fg=FG, font=(FONT, 34, "bold")).pack(pady=(0, 10))
            tk.Label(box, text=t("break.hint"), bg=BG, fg=MUTED, font=(FONT, 15)).pack()
            tl = tk.Label(box, text="", bg=BG, fg=ORANGE, font=(FONT, 76, "bold"))
            tl.pack(pady=20)
            sl = tk.Label(box, text="", bg=BG, fg=MUTED, font=(FONT, 14))
            sl.pack()
            self._break_time_labels.append(tl)
            self._break_status_labels.append(sl)
            if allow_skip and on_skip and m.primary:
                btn = tk.Button(box, text=t("break.skip"), font=(FONT, 10), bg=PANEL, fg=FAINT_TEXT,
                                activebackground=PANEL_H, activeforeground=FG, relief="flat",
                                bd=0, padx=14, pady=6, cursor="hand2")
                btn.configure(command=lambda b_=btn: self._skip_click(b_, on_skip))
                btn.pack(pady=(48, 0))
            self._break_wins.append(win)
        self._break_keep_on_top()

    def _skip_click(self, btn, on_skip):
        now = time.monotonic()
        if now - self._skip_armed_at <= 4:
            on_skip()
        else:
            self._skip_armed_at = now
            btn.configure(text=t("break.skip_confirm"), fg=DANGER)

    def _break_update(self, seconds_left, counting):
        s = max(0, int(seconds_left + 0.999))
        text = f"{s // 60:02d}:{s % 60:02d}"
        status = t("break.counting") if counting else t("break.waiting")
        for tl in self._break_time_labels:
            tl.configure(text=text, fg=ORANGE if counting else FAINT_TEXT)
        for sl in self._break_status_labels:
            sl.configure(text=status)

    def _break_keep_on_top(self):
        if not self._break_wins:
            return
        for w in self._break_wins:
            try:
                w.attributes("-topmost", True)
                w.lift()
            except tk.TclError:
                pass
        self.root.after(1000, self._break_keep_on_top)

    def _break_hide(self):
        for w in self._break_wins:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._break_wins, self._break_time_labels, self._break_status_labels = [], [], []
        self._skip_armed_at = 0.0

    # ------------------------------------------------------------ about
    def about(self):
        self.call(self._show_about)

    def _show_about(self):
        if self._about is not None and self._about.winfo_exists():
            self._about.deiconify()
            self._about.lift()
            self._about.focus_force()
            return
        win = self._about = tk.Toplevel(self.root, bg=BG)
        win.title(APP_NAME)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        for ms in (0, 60, 300):
            win.after(ms, lambda: style_titlebar(win))

        anchor, justify = _align()
        card = tk.Frame(win, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        logo = asset_path("logo_64.png")
        if logo:
            try:
                self._logo = tk.PhotoImage(file=logo)
                tk.Label(card, image=self._logo, bg=PANEL).pack(pady=(20, 6))
            except tk.TclError:
                pass
        tk.Label(card, text=APP_NAME, bg=PANEL, fg=FG, font=(FONT, 18, "bold")).pack()
        tk.Label(card, text=t("about.version", v=APP_VERSION), bg=PANEL, fg=MUTED, font=(FONT, 10)).pack()
        tk.Label(card, text=t("about.tagline"), bg=PANEL, fg=FG, font=(FONT, 11),
                 wraplength=360).pack(pady=(12, 4), padx=20)
        tk.Label(card, text=t("about.by", a=APP_AUTHOR), bg=PANEL, fg=FG,
                 font=(FONT, 10, "bold")).pack(pady=(8, 0))

        def link(text, url):
            lbl = tk.Label(card, text=text, bg=PANEL, fg=ORANGE, font=(FONT, 10, "underline"), cursor="hand2")
            lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))
            lbl.pack()
        link(APP_WEBSITE.split("://", 1)[-1].rstrip("/"), APP_WEBSITE)
        link(APP_REPO.split("://", 1)[-1], APP_REPO)

        tk.Label(card, text=t("about.license"),
                 bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(pady=(12, 0))
        tk.Label(card, text=t("about.privacy"), bg=PANEL, fg=FAINT_TEXT, font=(FONT, 9),
                 wraplength=360, justify=justify, anchor=anchor).pack(pady=(6, 0), padx=20)
        tk.Button(card, text=t("about.close"), command=win.destroy, bg=ORANGE, fg=ON_ORANGE,
                  activebackground=ORANGE_H, activeforeground=ON_ORANGE, relief="flat", bd=0,
                  font=(FONT, 10, "bold"), padx=24, pady=6, cursor="hand2").pack(pady=(16, 20))

        win.update_idletasks()
        w, h = max(420, win.winfo_reqwidth()), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        win.focus_force()

    # ------------------------------------------------------------ eye calibration
    def calibrate_points(self, points, sample_fn, on_done):
        """points: [(monitor, x, y)] in screen pixels. sample_fn() -> features | None.
        on_done([(features, (x, y)), ...]) or on_done(None) when cancelled."""
        self.call(self._calibrate_points, points, sample_fn, on_done)

    def _calibrate_points(self, points, sample_fn, on_done):
        samples = []
        wins = {}
        state = {"cancel": False}

        def cancel(_e=None):
            state["cancel"] = True

        # one dark cover per monitor, the dot moves between them
        for mon in {id(p[0]): p[0] for p in points}.values():
            l, t_, r, b = mon.rect
            win = tk.Toplevel(self.root, bg=BG)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.geometry(f"{r - l}x{b - t_}+{l}+{t_}")
            cv = tk.Canvas(win, bg=BG, highlightthickness=0)
            cv.pack(fill="both", expand=True)
            win.bind("<Escape>", cancel)
            wins[id(mon)] = (win, cv, mon)
        first = next(iter(wins.values()))
        first[1].create_text((first[2].rect[2] - first[2].rect[0]) // 2, 60, text=t("eyes.cal_hint"),
                             fill=MUTED, font=(FONT, 14), tags="hint")
        first[0].focus_force()

        def finish(result):
            for win, _cv, _m in wins.values():
                if win.winfo_exists():
                    win.destroy()
            on_done(result)

        def show(i):
            if state["cancel"]:
                finish(None)
                return
            if i >= len(points):
                finish(samples)
                return
            mon, x, y = points[i]
            for _w, cv, _m in wins.values():
                cv.delete("dot")
            win, cv, _ = wins[id(mon)]
            cx, cy = x - mon.rect[0], y - mon.rect[1]
            cv.create_oval(cx - 22, cy - 22, cx + 22, cy + 22, outline=ORANGE, width=2, tags="dot")
            cv.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, fill=ORANGE, outline="", tags="dot")
            cv.create_text(cx, cy + 44 if cy < 200 else cy - 44, text=f"{i + 1}/{len(points)}",
                           fill=FAINT_TEXT, font=(FONT, 10), tags="dot")
            win.after(1100, collect, i, 1300)

        def collect(i, left_ms):
            if state["cancel"]:
                finish(None)
                return
            s = sample_fn()
            if s is not None:
                samples.append((s, (points[i][1], points[i][2])))
            if left_ms > 0:
                self.root.after(80, collect, i, left_ms - 80)
            else:
                show(i + 1)

        self.root.after(1500, show, 0)

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
            l, t_, r, b = mon.rect
            win = tk.Toplevel(self.root, bg=BG)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.geometry(f"{r - l}x{b - t_}+{l}+{t_}")
            cv = tk.Canvas(win, bg=BG, highlightthickness=0)
            cv.pack(fill="both", expand=True)
            cx, cy = (r - l) // 2, (b - t_) // 2
            cv.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, outline=ORANGE, width=2)
            cv.create_oval(cx - 14, cy - 14, cx + 14, cy + 14, fill=ORANGE, outline="")
            cv.create_text(cx, cy - 90, text=text, fill=FG, font=(FONT, 26, "bold"))
            cv.create_text(cx, cy + 70, text=t("cal.hint"), fill=MUTED, font=(FONT, 14))
            info = cv.create_text(cx, cy + 120, text=t("cal.ready"), fill=MUTED, font=(FONT, 12))
            cv.create_text(cx, b - t_ - 40, text=f"{i + 1} / {len(targets)}   ({t('cal.cancel_hint')})",
                           fill=FAINT_TEXT, font=(FONT, 10))
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
                cv.itemconfigure(info, text=t("cal.recording", n=len(samples)), fill=ORANGE)
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
