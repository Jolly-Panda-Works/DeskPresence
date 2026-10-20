"""A small always-on-top widget: status, water / break / sitting timers and quick buttons.

Drag it anywhere (its position is remembered); right-click for more.
"""
import logging
import tkinter as tk

from .i18n import is_rtl, t
from .ui import BORDER, FAINT_TEXT, FG, FONT, MUTED, ON_ORANGE, ORANGE, ORANGE_H, PANEL, PANEL_H
from . import winapi

log = logging.getLogger(__name__)

DOT = {"present": "#4ADE80", "away": "#FBBF24", "break": "#60A5FA", "paused": "#A99B8E", "error": "#F87171"}


def _mins(seconds):
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    if m >= 60:
        return f"{m // 60}:{m % 60:02d}"
    return t("widget.min", n=max(0, m))


class Widget:
    W = 250

    def __init__(self, ui, ctrl, cfg, open_settings):
        self.ui, self.ctrl, self.cfg, self.open_settings = ui, ctrl, cfg, open_settings
        self.win = None
        self._drag = None

    # ------------------------------------------------------------ show / hide (Tk thread)
    def show(self):
        if self.win is not None and self.win.winfo_exists():
            return
        self._build()

    def hide(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None

    def set_visible(self, visible):
        w = dict(self.cfg["widget"])
        w["enabled"] = visible
        self.cfg.set("widget", w)
        self.ui.call(self.show if visible else self.hide)

    def rebuild(self):
        """After a language change."""
        if self.win is not None and self.win.winfo_exists():
            self.hide()
            self._build()

    def _build(self):
        rtl = is_rtl()
        anchor = "e" if rtl else "w"
        side_a, side_b = ("right", "left") if rtl else ("left", "right")
        win = self.win = tk.Toplevel(self.ui.root, bg=BORDER)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        box = tk.Frame(win, bg=PANEL)
        box.pack(fill="both", expand=True, padx=1, pady=1)

        def row(pady=(0, 6)):
            r = tk.Frame(box, bg=PANEL)
            r.pack(fill="x", padx=12, pady=pady)
            return r

        def small_button(parent, text, command, primary=False):
            b = tk.Label(parent, text=text, bg=ORANGE if primary else PANEL_H, fg=ON_ORANGE if primary else FG,
                         font=(FONT, 9, "bold" if primary else "normal"), padx=8, pady=2, cursor="hand2")
            b.bind("<Button-1>", lambda _e: command())
            b.bind("<Enter>", lambda _e: b.configure(bg=ORANGE_H if primary else BORDER))
            b.bind("<Leave>", lambda _e: b.configure(bg=ORANGE if primary else PANEL_H))
            return b

        top = row((10, 8))
        self.dot = tk.Canvas(top, width=10, height=10, bg=PANEL, highlightthickness=0)
        self.dot.pack(side=side_a, padx=(0, 6) if not rtl else (6, 0))
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=DOT["present"], outline="")
        self.status = tk.Label(top, text="", bg=PANEL, fg=FG, font=(FONT, 10, "bold"), anchor=anchor)
        self.status.pack(side=side_a, fill="x", expand=True)
        gear = small_button(top, "⚙", self.open_settings)
        gear.pack(side=side_b)
        self.eye_btn = small_button(top, "👁", self._toggle_eyes)
        self.eye_btn.pack(side=side_b, padx=4)

        r = row()
        self.water = tk.Label(r, text="", bg=PANEL, fg=FG, font=(FONT, 10), anchor=anchor)
        self.water.pack(side=side_a, fill="x", expand=True)
        small_button(r, t("water.drank"), self._drank, primary=True).pack(side=side_b)

        r = row()
        self.brk = tk.Label(r, text="", bg=PANEL, fg=FG, font=(FONT, 10), anchor=anchor)
        self.brk.pack(side=side_a, fill="x", expand=True)

        r = row((0, 10))
        self.sit = tk.Label(r, text="", bg=PANEL, fg=MUTED, font=(FONT, 9), anchor=anchor)
        self.sit.pack(side=side_a, fill="x", expand=True)
        self.cam_btn = small_button(r, "", self._toggle_camera)
        self.cam_btn.pack(side=side_b)

        for w in (win, box, top, self.status, self.water, self.brk, self.sit):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)
            w.bind("<Button-3>", self._menu)

        win.update_idletasks()
        h = win.winfo_reqheight()
        pos = self.cfg["widget"]
        x, y = pos.get("x"), pos.get("y")
        monitors = winapi.list_monitors()
        if x is None or y is None or not any(m.contains(x + 10, y + 10) for m in monitors):
            l, t_, r_, b = winapi.pick_monitor(monitors, self.cfg["notification_monitor"]).work
            x, y = r_ - self.W - 16, t_ + 16
        win.geometry(f"{self.W}x{h}+{x}+{y}")
        self._refresh()

    # ------------------------------------------------------------ live values
    def _refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        try:
            self._update()
        except Exception:
            log.debug("widget refresh failed", exc_info=True)
        self.win.after(1000, self._refresh)

    def _update(self):
        ctrl = self.ctrl
        tm = ctrl.timers()
        if ctrl.paused:
            key = "paused"
        elif ctrl.status == "camera_error":
            key = "error"
        elif ctrl.break_active:
            key = "break"
        else:
            key = ctrl.state
        self.dot.itemconfigure(self.dot_id, fill=DOT.get(key, DOT["present"]))
        self.status.configure(text=t("status." + ctrl.status))
        self.water.configure(text="💧 " + (t("widget.water", left=_mins(tm["water_left"]))
                                          if tm["water_left"] is not None else t("set.off")))
        if tm["break_active"]:
            s = int(tm["break_remaining"] or 0)
            self.brk.configure(text="☕ " + t("widget.on_break", left=f"{s // 60:02d}:{s % 60:02d}"), fg=ORANGE)
        elif tm["break_left"] is not None:
            self.brk.configure(text="☕ " + t("widget.break", left=_mins(tm["break_left"])), fg=FG)
        else:
            self.brk.configure(text="☕ " + t("set.off"), fg=FAINT_TEXT)
        self.sit.configure(text="🪑 " + t("widget.sitting", n=_mins(tm["sitting"])))
        eyes_on = self.cfg["mouse_mode"] == "eyes"
        self.eye_btn.configure(bg=ORANGE if eyes_on else PANEL_H, fg=ON_ORANGE if eyes_on else FG)
        lent = ctrl.camera_lent_to is not None
        self.cam_btn.configure(text=t("widget.cam_take") if lent else t("widget.cam_give"))

    # ------------------------------------------------------------ actions
    def _drank(self):
        self.ctrl.drank_water()
        self._update()

    def _toggle_eyes(self):
        self.ctrl.set_eye_follow(self.cfg["mouse_mode"] != "eyes")
        self._update()

    def _toggle_camera(self):
        if self.ctrl.camera_lent_to is not None:
            self.ctrl.take_camera_back()
        else:
            self.ctrl.release_camera()
        self._update()

    def _menu(self, event):
        m = tk.Menu(self.win, tearoff=0, bg=PANEL, fg=FG, activebackground=PANEL_H, activeforeground=ORANGE,
                    font=(FONT, 10))
        m.add_command(label=t("menu.open_settings"), command=self.open_settings)
        m.add_command(label=t("widget.hide"), command=lambda: self.set_visible(False))
        m.tk_popup(event.x_root, event.y_root)

    def _start_drag(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _on_drag(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_drag(self, _e):
        if self._drag:
            self._drag = None
            w = dict(self.cfg["widget"])
            w["x"], w["y"] = self.win.winfo_x(), self.win.winfo_y()
            self.cfg.set("widget", w)
