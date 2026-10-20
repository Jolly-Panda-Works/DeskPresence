"""A small always-on-top widget: status, water / break / sitting timers and quick buttons.

- drag it anywhere by its title bar or any empty spot (the position is remembered)
- "–" shrinks it to a one-line bar, "×" closes it (tray menu -> Show widget brings it back)
- transparency: right-click -> Transparency, Ctrl + mouse wheel, or Settings -> General;
  it turns fully opaque while the mouse is over it
"""
import logging
import tkinter as tk

from . import winapi
from .i18n import is_rtl, language, t
from .ui import BORDER, FAINT_TEXT, FG, FONT, MUTED, ON_ORANGE, ORANGE, ORANGE_H, PANEL, PANEL_H, TOOLBAR

log = logging.getLogger(__name__)

DOT = {"present": "#4ADE80", "away": "#FBBF24", "break": "#60A5FA", "paused": "#A99B8E", "error": "#F87171"}
OPACITY_STEPS = (100, 85, 70, 55, 40)
MIN_OPACITY = 30


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
        self._hover = False
        self._alpha = None
        self._lang = None

    # ------------------------------------------------------------ settings
    def _get(self, key, default):
        return self.cfg["widget"].get(key, default)

    def _put(self, **values):
        w = dict(self.cfg["widget"])
        w.update(values)
        self.cfg.set("widget", w)

    @property
    def opacity(self):
        return max(MIN_OPACITY, min(100, int(self._get("opacity", 90))))

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
        self._put(enabled=visible)
        self.ui.call(self.show if visible else self.hide)

    def rebuild(self):
        """After a language change or switching between full and minimized."""
        if self.win is not None and self.win.winfo_exists():
            self.hide()
            self._build()

    def language_changed(self):
        """Rebuild only when the language changed (other settings are picked up live)."""
        if self._lang is not None and self._lang != language():
            self.rebuild()

    def _close(self):
        self.set_visible(False)
        self.ctrl.popup(t("widget.closed.title"), t("widget.closed.body"), seconds=6)

    def _toggle_minimized(self):
        self._put(minimized=not self._get("minimized", False))
        self.rebuild()

    # ------------------------------------------------------------ building
    def _small_button(self, parent, text, command, primary=False, flat=False):
        bg = ORANGE if primary else (parent["bg"] if flat else PANEL_H)
        hover = ORANGE_H if primary else BORDER
        b = tk.Label(parent, text=text, bg=bg, fg=ON_ORANGE if primary else FG,
                     font=(FONT, 9, "bold" if primary else "normal"), padx=7, pady=1, cursor="hand2")
        b.bind("<Button-1>", lambda _e: command())
        b.bind("<Enter>", lambda _e: b.configure(bg=hover))
        b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        b._is_button = True
        return b

    def _build(self):
        rtl = is_rtl()
        self._lang = language()
        self.anchor = "e" if rtl else "w"
        self.side_a, self.side_b = ("right", "left") if rtl else ("left", "right")
        win = self.win = tk.Toplevel(self.ui.root, bg=BORDER)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self._alpha = None
        box = tk.Frame(win, bg=PANEL)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.water = self.brk = self.sit = self.status = self.cam_btn = self.eye_btn = None

        if self._get("minimized", False):
            self._build_compact(box)
        else:
            self._build_full(box)

        self._bind_all(win)
        x, y = self._get("x", None), self._get("y", None)
        monitors = winapi.list_monitors()
        if x is None or y is None or not any(m.contains(x + 10, y + 10) for m in monitors):
            l, t_, r_, b = winapi.pick_monitor(monitors, self.cfg["notification_monitor"]).work
            x, y = r_ - self.W - 16, t_ + 16
        self._refresh()  # fills in the texts before the size is decided
        win.update_idletasks()
        if self._get("minimized", False):
            win.geometry(f"+{x}+{y}")  # the one-line bar sizes itself to its text
        else:
            win.geometry(f"{self.W}x{win.winfo_reqheight()}+{x}+{y}")

    def _build_full(self, box):
        side_a, side_b, anchor = self.side_a, self.side_b, self.anchor

        # title bar: drag handle + minimize / close
        bar = tk.Frame(box, bg=TOOLBAR)
        bar.pack(fill="x")
        tk.Label(bar, text="⠿  DeskPresence", bg=TOOLBAR, fg=FAINT_TEXT, font=(FONT, 8), cursor="fleur").pack(
            side=side_a, padx=8, pady=3)
        self._small_button(bar, "×", self._close, flat=True).pack(side=side_b, padx=(0, 2) if not is_rtl() else (2, 0))
        self._small_button(bar, "–", self._toggle_minimized, flat=True).pack(side=side_b)

        def row(pady=(0, 6)):
            r = tk.Frame(box, bg=PANEL)
            r.pack(fill="x", padx=12, pady=pady)
            return r

        top = row((8, 8))
        self.dot = tk.Canvas(top, width=10, height=10, bg=PANEL, highlightthickness=0)
        self.dot.pack(side=side_a, padx=(0, 6) if side_a == "left" else (6, 0))
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=DOT["present"], outline="")
        self.status = tk.Label(top, text="", bg=PANEL, fg=FG, font=(FONT, 10, "bold"), anchor=anchor)
        self.status.pack(side=side_a, fill="x", expand=True)
        self._small_button(top, "⚙", self.open_settings).pack(side=side_b)
        self.eye_btn = self._small_button(top, "👁", self._toggle_eyes)
        self.eye_btn.pack(side=side_b, padx=4)

        r = row()
        self.water = tk.Label(r, text="", bg=PANEL, fg=FG, font=(FONT, 10), anchor=anchor)
        self.water.pack(side=side_a, fill="x", expand=True)
        self._small_button(r, t("water.drank"), self._drank, primary=True).pack(side=side_b)

        r = row()
        self.brk = tk.Label(r, text="", bg=PANEL, fg=FG, font=(FONT, 10), anchor=anchor)
        self.brk.pack(side=side_a, fill="x", expand=True)

        r = row((0, 10))
        self.sit = tk.Label(r, text="", bg=PANEL, fg=MUTED, font=(FONT, 9), anchor=anchor)
        self.sit.pack(side=side_a, fill="x", expand=True)
        self.cam_btn = self._small_button(r, "", self._toggle_camera)
        self.cam_btn.pack(side=side_b)

    def _build_compact(self, box):
        side_a, side_b = self.side_a, self.side_b
        r = tk.Frame(box, bg=PANEL)
        r.pack(fill="x", padx=(8, 4), pady=4)
        tk.Label(r, text="⠿", bg=PANEL, fg=FAINT_TEXT, font=(FONT, 9), cursor="fleur").pack(side=side_a)
        self.dot = tk.Canvas(r, width=10, height=10, bg=PANEL, highlightthickness=0)
        self.dot.pack(side=side_a, padx=6)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=DOT["present"], outline="")
        self.compact = tk.Label(r, text="", bg=PANEL, fg=FG, font=(FONT, 9))
        self.compact.pack(side=side_a)
        self._small_button(r, "💧", self._drank, flat=True).pack(side=side_a, padx=(6, 0))
        self._small_button(r, "×", self._close, flat=True).pack(side=side_b)
        self._small_button(r, "▢", self._toggle_minimized, flat=True).pack(side=side_b)

    def _bind_all(self, widget):
        """Drag, right-click menu, Ctrl+wheel and hover on everything that is not a button."""
        if not getattr(widget, "_is_button", False):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)
        widget.bind("<Button-3>", self._menu, add="+")
        widget.bind("<Control-MouseWheel>", self._wheel, add="+")
        widget.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        widget.bind("<Leave>", self._maybe_leave, add="+")
        for child in widget.winfo_children():
            self._bind_all(child)

    # ------------------------------------------------------------ transparency
    def _apply_alpha(self):
        alpha = 1.0 if self._hover else self.opacity / 100
        if alpha != self._alpha and self.win is not None:
            try:
                self.win.attributes("-alpha", alpha)
                self._alpha = alpha
            except tk.TclError:
                pass

    def _set_hover(self, hover):
        self._hover = hover
        self._apply_alpha()

    def _maybe_leave(self, _e):
        # <Leave> also fires when moving between child widgets: check where the pointer really is
        if self.win is None:
            return
        x, y = self.win.winfo_pointerxy()
        wx, wy = self.win.winfo_rootx(), self.win.winfo_rooty()
        inside = wx <= x < wx + self.win.winfo_width() and wy <= y < wy + self.win.winfo_height()
        if not inside:
            self._set_hover(False)

    def set_opacity(self, percent):
        self._put(opacity=max(MIN_OPACITY, min(100, int(percent))))
        self._alpha = None
        self._apply_alpha()

    def _wheel(self, e):
        self.set_opacity(self.opacity + (5 if e.delta > 0 else -5))
        self._hover = False  # show the new transparency right away
        self._apply_alpha()

    # ------------------------------------------------------------ live values
    def _refresh(self):
        if self.win is None or not self.win.winfo_exists():
            return
        try:
            self._update()
            self._apply_alpha()  # picks up a change made in the settings window
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

        if tm["break_active"]:
            s = int(tm["break_remaining"] or 0)
            brk_short = f"{s // 60:02d}:{s % 60:02d}"
        else:
            brk_short = _mins(tm["break_left"]) if tm["break_left"] is not None else "—"
        if self.status is None:  # minimized
            water = _mins(tm["water_left"]) if tm["water_left"] is not None else "—"
            self.compact.configure(text=f"💧 {water}   ☕ {brk_short}")
            return

        self.status.configure(text=t("status." + ctrl.status))
        self.water.configure(text="💧 " + (t("widget.water", left=_mins(tm["water_left"]))
                                          if tm["water_left"] is not None else t("set.off")))
        if tm["break_active"]:
            self.brk.configure(text="☕ " + t("widget.on_break", left=brk_short), fg=ORANGE)
        elif tm["break_left"] is not None:
            self.brk.configure(text="☕ " + t("widget.break", left=brk_short), fg=FG)
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
        m.add_command(label=t("widget.expand") if self._get("minimized", False) else t("widget.minimize"),
                      command=self._toggle_minimized)
        sub = tk.Menu(m, tearoff=0, bg=PANEL, fg=FG, activebackground=PANEL_H, activeforeground=ORANGE,
                      font=(FONT, 10))
        current = tk.IntVar(value=min(OPACITY_STEPS, key=lambda p: abs(p - self.opacity)))
        for p in OPACITY_STEPS:
            sub.add_radiobutton(label=f"{p}%", variable=current, value=p, command=lambda p=p: self.set_opacity(p))
        m.add_cascade(label=t("widget.opacity"), menu=sub)
        m.add_separator()
        m.add_command(label=t("widget.hide"), command=self._close)
        m.tk_popup(event.x_root, event.y_root)
        return "break"

    def _start_drag(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _on_drag(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_drag(self, _e):
        if self._drag:
            self._drag = None
            self._put(x=self.win.winfo_x(), y=self.win.winfo_y())
