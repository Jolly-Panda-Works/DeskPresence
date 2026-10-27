"""The settings window (customtkinter, same look as Image Format Converter and SnapshotAll)."""
import copy
import logging
import threading
import tkinter as tk
import webbrowser

import customtkinter as ctk
from PIL import Image, ImageDraw

from . import APP_AUTHOR, APP_NAME, APP_REPO, APP_VERSION, APP_WEBSITE, exercise, network, phone, winapi
from .i18n import is_rtl, set_language, t
from .media import MODES
from .tray import autostart_enabled, set_autostart
from .ui import (BG, BORDER, FAINT_TEXT, FG, FONT, MUTED, ON_ORANGE, ORANGE, ORANGE_H, PANEL, PANEL_H, TOOLBAR,
                 asset_path, style_titlebar)

log = logging.getLogger(__name__)

SIDEBAR = "#181310"
FIELD = "#2A211A"
OK_GREEN = "#4ADE80"
DANGER = "#F87171"

SECTIONS = ("general", "presence", "phone", "actions", "health", "mouse", "laptop", "about")


def _get(data, path):
    for part in path.split("."):
        data = data[part]
    return data


def _set(data, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        data = data[part]
    data[parts[-1]] = value


class SettingsWindow:
    def __init__(self, ui, ctrl, cfg, on_saved):
        self.ui, self.ctrl, self.cfg, self.on_saved = ui, ctrl, cfg, on_saved
        ctk.set_appearance_mode("dark")
        self.fields = {}   # config path -> (tk variable, converter)
        self.media_vars = {}
        self.section = "general"
        self._save_job = None
        self.preview_img = None
        self.win = None
        self._build()

    # ------------------------------------------------------------ window
    def _build(self):
        self.rtl = is_rtl()
        win = self.win = ctk.CTkToplevel(self.ui.root, fg_color=BG)
        win.title(f"{APP_NAME} - {t('set.title')}")
        win.geometry("940x680")
        win.minsize(820, 560)
        win.protocol("WM_DELETE_WINDOW", self.close)
        ico = asset_path("icon.ico")
        if ico:
            win.after(250, lambda: win.iconbitmap(ico))
        for ms in (0, 60, 300, 900):
            win.after(ms, lambda: style_titlebar(win, TOOLBAR))

        fam = FONT
        self.f_title = ctk.CTkFont(family=fam, size=22, weight="bold")
        self.f_bold = ctk.CTkFont(family=fam, size=14, weight="bold")
        self.f_body = ctk.CTkFont(family=fam, size=13)
        self.f_small = ctk.CTkFont(family=fam, size=12)
        self.f_section = ctk.CTkFont(family=fam, size=11, weight="bold")

        win.grid_columnconfigure(0 if self.rtl else 1, weight=1)
        win.grid_rowconfigure(1, weight=1)

        # toolbar
        bar = ctk.CTkFrame(win, fg_color=TOOLBAR, corner_radius=0, height=60)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        logo = asset_path("logo_64.png")
        side = "right" if self.rtl else "left"
        if logo:
            self.logo_img = ctk.CTkImage(Image.open(logo), size=(34, 34))
            ctk.CTkLabel(bar, image=self.logo_img, text="").pack(side=side, padx=(20, 10), pady=12)
        ctk.CTkLabel(bar, text=APP_NAME, font=self.f_bold, text_color=FG).pack(side=side)
        ctk.CTkLabel(bar, text=f"v{APP_VERSION}", font=self.f_small, text_color=MUTED, fg_color=PANEL,
                     corner_radius=8, width=60, height=22).pack(side=side, padx=10)
        ctk.CTkFrame(win, height=1, fg_color=BORDER, corner_radius=0).grid(row=0, column=0, columnspan=2,
                                                                             sticky="sew")

        # sidebar
        nav = ctk.CTkFrame(win, fg_color=SIDEBAR, corner_radius=0, width=190)
        nav.grid(row=1, column=1 if self.rtl else 0, sticky="ns")
        nav.grid_propagate(False)
        self.nav_buttons = {}
        for key in SECTIONS:
            b = ctk.CTkButton(nav, text=t(f"set.sec.{key}"), anchor="e" if self.rtl else "w", height=40,
                              corner_radius=10, fg_color="transparent", hover_color=PANEL_H, text_color=FG,
                              font=self.f_body, command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=(12 if key == SECTIONS[0] else 2, 0))
            self.nav_buttons[key] = b

        # content
        self.body = ctk.CTkScrollableFrame(win, fg_color=BG, corner_radius=0, scrollbar_button_color=PANEL_H)
        self.body.grid(row=1, column=0 if self.rtl else 1, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        # footer
        foot = ctk.CTkFrame(win, fg_color=TOOLBAR, corner_radius=0, height=64)
        foot.grid(row=2, column=0, columnspan=2, sticky="ew")
        foot.grid_propagate(False)
        far = "left" if self.rtl else "right"
        self._primary(foot, t("about.close"), self.close).pack(side=far, padx=(8, 20), pady=12)
        ctk.CTkLabel(foot, text=t("set.autosave"), font=self.f_small, text_color=FAINT_TEXT).pack(
            side="right" if self.rtl else "left", padx=20)
        self.saved_lbl = ctk.CTkLabel(foot, text="", font=self.f_body, text_color=OK_GREEN)
        self.saved_lbl.pack(side=far, padx=16)

        self.show(self.section)
        self._tick()
        win.after(100, win.lift)
        win.after(150, win.focus_force)

    def show(self, key):
        self.section = key
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=PANEL_H if k == key else "transparent",
                        text_color=ORANGE if k == key else FG)
        for w in self.body.winfo_children():
            w.destroy()
        self.preview_lbl = None
        self.live = {}
        getattr(self, f"_sec_{key}")()
        try:
            self.body._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def lift(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()

    def close(self):
        self.ctrl.camera_hold = False
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def _teach_owner(self):
        self.ctrl.teach_owner()

    def _forget_owner(self):
        self.ctrl.forget_owner()

    @property
    def alive(self):
        return self.win is not None and self.win.winfo_exists()

    # ------------------------------------------------------------ widgets
    def _card(self, title, hint=None):
        card = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=16, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=22, pady=(18, 0))
        card.grid_columnconfigure(0 if self.rtl else 1, weight=1)
        card.grid_columnconfigure(1 if self.rtl else 0, weight=0)
        anchor = "e" if self.rtl else "w"
        ctk.CTkLabel(card, text=title if self.rtl else title.upper(), font=self.f_section, text_color=ORANGE,
                     anchor=anchor).grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(14, 2))
        if hint:
            ctk.CTkLabel(card, text=hint, font=self.f_small, text_color=MUTED, anchor=anchor,
                         justify="right" if self.rtl else "left", wraplength=600).grid(
                row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 4))
        card._row = 2
        return card

    def _row(self, card, label, widget_factory, hint=None):
        """A label + widget row; the widget sits on the far side for the language direction."""
        r = card._row
        anchor = "e" if self.rtl else "w"
        lab = ctk.CTkFrame(card, fg_color="transparent")
        lab.grid(row=r, column=1 if self.rtl else 0, sticky="nsew", padx=18, pady=8)
        ctk.CTkLabel(lab, text=label, font=self.f_body, text_color=FG, anchor=anchor).pack(fill="x")
        if hint:
            ctk.CTkLabel(lab, text=hint, font=self.f_small, text_color=FAINT_TEXT, anchor=anchor,
                         justify="right" if self.rtl else "left", wraplength=330).pack(fill="x")
        holder = ctk.CTkFrame(card, fg_color="transparent")
        holder.grid(row=r, column=0 if self.rtl else 1, sticky="e" if not self.rtl else "w", padx=18, pady=8)
        widget = widget_factory(holder)
        if widget is not None:
            widget.pack(side="left" if self.rtl else "right")
        card._row += 1
        return widget

    def _end(self, card):
        ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=card._row, column=0)

    def _primary(self, parent, text, command, width=120):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=38, corner_radius=12,
                             fg_color=ORANGE, hover_color=ORANGE_H, text_color=ON_ORANGE, font=self.f_bold)

    def _ghost(self, parent, text, command, width=110):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=38, corner_radius=12,
                             fg_color="transparent", hover_color=PANEL_H, border_width=1, border_color=BORDER,
                             text_color=FG, font=self.f_body)

    def _var(self, path, kind):
        if path in self.fields:
            return self.fields[path][0]
        value = _get(self.cfg.data, path)
        if kind is bool:
            var = tk.BooleanVar(value=bool(value))
        elif kind is str:
            var = tk.StringVar(value=str(value))
        else:
            var = tk.DoubleVar(value=float(value))
        self.fields[path] = (var, kind)
        var.trace_add("write", lambda *_: self._schedule_save())
        return var

    def _schedule_save(self, delay=800):
        """Every change is saved (and applied) shortly after you make it."""
        if self._save_job is not None:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(delay, self._autosave)

    def _autosave(self):
        self._save_job = None
        if self.alive:
            self.save()

    def _switch(self, card, label, path, hint=None):
        var = self._var(path, bool)
        return self._row(card, label, lambda p: ctk.CTkSwitch(
            p, text="", variable=var, onvalue=True, offvalue=False, progress_color=ORANGE,
            button_color=FG, button_hover_color=FG, fg_color=FIELD, width=46), hint)

    def _slider(self, card, label, path, lo, hi, step, kind=int, unit="", hint=None):
        var = self._var(path, kind)

        def make(p):
            box = ctk.CTkFrame(p, fg_color="transparent")
            val = ctk.CTkLabel(box, text="", font=self.f_body, text_color=FG, width=90)

            def upd(*_):
                v = var.get()
                shown = f"{v:.1f}" if kind is float else str(int(round(v)))
                val.configure(text=t("set.off") if (lo == 0 and v == 0) else f"{shown} {unit}".strip())
            s = ctk.CTkSlider(box, from_=lo, to=hi, number_of_steps=max(1, int(round((hi - lo) / step))),
                              variable=var, width=220, progress_color=ORANGE, button_color=ORANGE,
                              button_hover_color=ORANGE_H, fg_color=FIELD, command=lambda _v: upd())
            if self.rtl:
                val.pack(side="left")
                s.pack(side="left", padx=8)
            else:
                s.pack(side="left", padx=8)
                val.pack(side="left")
            upd()
            return box
        return self._row(card, label, make, hint)

    def _choice(self, card, label, path, options, hint=None, on_change=None):
        """Segmented buttons. options: [(value, text)]."""
        var = self._var(path, str)
        texts = [txt for _v, txt in options]
        to_value = {txt: v for v, txt in options}
        to_text = {v: txt for v, txt in options}

        def make(p):
            seg = ctk.CTkSegmentedButton(
                p, values=texts[::-1] if self.rtl else texts, font=self.f_body, selected_color=ORANGE,
                selected_hover_color=ORANGE_H, unselected_color=FIELD, unselected_hover_color=PANEL_H,
                fg_color=FIELD, text_color=FG, height=34,
                command=lambda txt: (var.set(to_value[txt]), on_change and on_change()))
            seg.set(to_text.get(var.get(), texts[0]))
            return seg
        return self._row(card, label, make, hint)

    def _menu(self, card, label, path, options, kind=str, hint=None):
        """Drop-down. options: [(value, text)]."""
        var = self._var(path, kind)
        to_value = {txt: v for v, txt in options}
        current = next((txt for v, txt in options if v == var.get()), options[0][1] if options else "")

        def make(p):
            m = ctk.CTkOptionMenu(p, values=[txt for _v, txt in options] or ["-"], width=240, height=34,
                                  fg_color=FIELD, button_color=PANEL_H, button_hover_color=BORDER,
                                  dropdown_fg_color=PANEL, dropdown_hover_color=PANEL_H, text_color=FG,
                                  font=self.f_body, dropdown_font=self.f_body,
                                  command=lambda txt: var.set(to_value[txt]))
            m.set(current)
            return m
        return self._row(card, label, make, hint)

    def _entry(self, card, label, path, width=240, hint=None, readonly=False, kind=str):
        var = self._var(path, str)
        self.fields[path] = (var, kind)

        def make(p):
            e = ctk.CTkEntry(p, textvariable=var, width=width, height=34, corner_radius=10, fg_color=FIELD,
                             border_color=BORDER, border_width=1, text_color=FG, font=self.f_body)
            if readonly:
                e.configure(state="readonly")
            return e
        return self._row(card, label, make, hint)

    def _info(self, card, label, key, hint=None):
        """A live, read-only value updated by _tick()."""
        lbl = self._row(card, label, lambda p: ctk.CTkLabel(p, text="", font=self.f_bold, text_color=FG), hint)
        self.live[key] = lbl
        return lbl

    # ------------------------------------------------------------ sections
    def _sec_general(self):
        c = self._card(t("set.sec.general"))
        self._choice(c, t("set.language"), "language",
                     [("auto", t("set.lang_auto")), ("fa", "فارسی"), ("en", "English")])
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self._row(c, t("menu.autostart"), lambda p: ctk.CTkSwitch(
            p, text="", variable=self.autostart_var, progress_color=ORANGE, button_color=FG,
            button_hover_color=FG, fg_color=FIELD, width=46,
            command=lambda: set_autostart(self.autostart_var.get())))
        self._switch(c, t("menu.widget"), "widget.enabled", hint=t("set.widget_hint"))
        self._slider(c, t("set.widget_opacity"), "widget.opacity", 30, 100, 5, unit="%",
                     hint=t("set.widget_opacity_hint"))
        self._choice(c, t("set.role"), "role",
                     [("desktop", t("set.role_desktop")), ("laptop", t("set.role_laptop"))],
                     hint=t("set.role_hint"))
        self._end(c)

    def _sec_presence(self):
        c = self._card(t("set.sec.presence"), t("set.presence_hint"))
        self._choice(c, t("set.source"), "presence_source",
                     [("camera", t("set.src_camera")), ("phone", t("set.src_phone")), ("both", t("set.src_both"))],
                     hint=t("set.source_hint"))
        self._end(c)

        c = self._card(t("set.camera"))
        self._menu(c, t("set.camera_index"), "camera_index",
                   [(float(i), t("set.camera_n", n=i + 1)) for i in range(5)], kind=int)
        self.preview_lbl = self._row(c, t("set.preview"), lambda p: ctk.CTkLabel(
            p, text=t("set.preview_off"), width=320, height=180, fg_color=FIELD, corner_radius=12,
            text_color=MUTED, font=self.f_small), hint=t("set.preview_hint"))
        self._info(c, t("set.camera_state"), "camera_state")
        self.cam_btn = self._row(c, "", lambda p: self._ghost(p, t("menu.cam_give"), self._toggle_camera, width=190),
                                 hint=t("set.release_hint"))
        self._choice(c, t("set.share"), "camera_share",
                     [("ask", t("set.share_ask")), ("always", t("set.share_always")), ("never", t("set.share_never"))],
                     hint=t("set.share_hint"))
        self._choice(c, t("set.camera_mode"), "camera_mode",
                     [("interval", t("set.cm_interval")), ("always", t("set.cm_always"))],
                     hint=t("set.camera_mode_hint"))
        self._slider(c, t("set.check_every"), "check_every_minutes", 1, 15, 1, unit=t("set.min"))
        self._slider(c, t("set.away_check"), "away_check_seconds", 5, 120, 5, unit=t("set.sec"),
                     hint=t("set.away_check_hint"))
        self._choice(c, t("set.presence_by"), "presence_by",
                     [("body", t("set.by_body")), ("face", t("set.by_face"))], hint=t("set.presence_by_hint"))
        self._end(c)

        c = self._card(t("set.owner"), t("set.owner_hint"))
        self._switch(c, t("set.owner_only"), "owner_only")
        self._info(c, t("set.owner_face"), "owner_state")

        def buttons(p):
            box = ctk.CTkFrame(p, fg_color="transparent")
            side = "left" if self.rtl else "right"
            self._primary(box, t("set.owner_teach"), self._teach_owner, width=150).pack(side=side, padx=8)
            self._ghost(box, t("set.owner_forget"), self._forget_owner).pack(side=side)
            return box
        self._row(c, "", buttons, hint=t("set.owner_teach_hint"))
        self._end(c)

        c = self._card(t("set.timing"))
        self._slider(c, t("set.away_seconds"), "away_seconds", 3, 60, 1, unit=t("set.sec"))
        self._slider(c, t("set.idle_guard"), "idle_guard_seconds", 0, 120, 5, unit=t("set.sec"),
                     hint=t("set.idle_guard_hint"))
        self._slider(c, t("set.idle_fallback"), "idle_fallback_minutes", 1, 30, 1, unit=t("set.min"),
                     hint=t("set.idle_fallback_hint"))
        self._switch(c, t("set.countdown"), "away_countdown", hint=t("set.countdown_hint"))
        self._slider(c, t("set.countdown_seconds"), "countdown_seconds", 3, 30, 1, unit=t("set.sec"))
        self._switch(c, t("set.wake_on_input"), "wake_on_input")
        self._end(c)

    def _sec_phone(self):
        c = self._card(t("set.sec.phone"), t("set.phone_hint"))
        self.phone_menu_holder = c
        devices = phone.paired_devices()
        options = [(d["id"], ("📱 " if d["phone"] else "") + d["name"]) for d in devices]
        if not options:
            options = [("", t("set.phone_none"))]
        else:
            options.insert(0, ("", t("set.phone_choose")))
        self._phone_names = {i: n for i, n in options}
        self._menu(c, t("set.phone_device"), "phone.device_id", options)
        self._row(c, t("set.phone_test"), lambda p: self._ghost(p, t("set.test"), self._test_phone, width=120),
                  hint=t("set.phone_test_hint"))
        self._info(c, t("set.phone_state"), "phone_test")
        self._info(c, t("set.phone_live"), "phone_live")
        self._slider(c, t("set.phone_every"), "phone.check_seconds", 3, 30, 1, unit=t("set.sec"))
        self._slider(c, t("set.phone_misses"), "phone.away_checks", 1, 6, 1, hint=t("set.phone_misses_hint"))
        self._end(c)

    def _sec_actions(self):
        c = self._card(t("set.sec.actions"))
        self._switch(c, t("set.pause_media"), "pause_media", hint=t("set.pause_media_hint"))
        self._switch(c, t("set.pause_on_call"), "pause_on_call", hint=t("set.pause_on_call_hint"))
        self._switch(c, t("set.monitors_off"), "turn_off_monitors")
        self._slider(c, t("set.lock_after"), "lock_after_away_minutes", 0, 60, 1, unit=t("set.min"))
        self._end(c)

        c = self._card(t("menu.media"), t("set.media_hint"))
        seen = self.ctrl.media.scan()
        if not seen:
            ctk.CTkLabel(c, text=t("media.scan_hint"), font=self.f_small, text_color=MUTED).grid(
                row=c._row, column=0, columnspan=2, padx=18, pady=8, sticky="e" if self.rtl else "w")
            c._row += 1
        overrides = self.cfg["media_apps"]
        for key, (name, kind) in sorted(seen.items(), key=lambda kv: kv[1][0].lower()):
            var = tk.StringVar(value=overrides.get(key, "auto"))
            var.trace_add("write", lambda *_: self._schedule_save())
            self.media_vars[key] = var
            texts = {m: t("media." + m) for m in MODES}
            back = {v: k for k, v in texts.items()}

            def make(p, var=var, texts=texts, back=back):
                m = ctk.CTkOptionMenu(p, values=list(texts.values()), width=240, height=34, fg_color=FIELD,
                                      button_color=PANEL_H, button_hover_color=BORDER, dropdown_fg_color=PANEL,
                                      dropdown_hover_color=PANEL_H, text_color=FG, font=self.f_body,
                                      dropdown_font=self.f_body, command=lambda txt: var.set(back[txt]))
                m.set(texts[var.get()])
                return m
            self._row(c, name, make, hint=t("set.media_detected", kind=t("media.kind." + kind)))
        self._end(c)

    def _sec_health(self):
        c = self._card(t("set.timers"), t("set.timers_hint"))
        self._info(c, "💧 " + t("set.water_left"), "t_water")
        self._row(c, "", lambda p: self._primary(p, t("water.drank"), self._drank, width=140))
        self._info(c, "☕ " + t("set.break_left"), "t_break")
        self._info(c, "🪑 " + t("set.sitting"), "t_sit")
        self._slider(c, t("set.reset_after"), "timer_reset_away_minutes", 1, 60, 1, unit=t("set.min"),
                     hint=t("set.reset_after_hint"))
        self._end(c)
        c = self._card(t("set.sec.health"))
        self._slider(c, t("set.water"), "water_reminder_minutes", 0, 180, 5, unit=t("set.min"))
        self._slider(c, t("set.standup"), "break_reminder_minutes", 0, 120, 5, unit=t("set.min"))
        self._end(c)

        c = self._card(t("set.exercise"), t("set.exercise_hint"))
        self._row(c, "", lambda p: self._primary(p, t("set.ex_start"), self.ctrl.start_exercise, width=150))
        self._info(c, "🤸 " + t("set.exercise_left"), "t_exercise")
        self._switch(c, t("set.ex_enabled"), "exercise.enabled")
        self._slider(c, t("set.ex_every"), "exercise.every_minutes", 15, 180, 15, unit=t("set.min"))
        self._switch(c, t("set.ex_auto"), "exercise.auto_open", hint=t("set.ex_auto_hint"))
        self._slider(c, t("set.ex_reps"), "exercise.reps", 3, 20, 1)
        for key in exercise.ORDER:
            self._switch(c, t(f"ex.name.{key}"), f"exercise.moves.{key}")
        self._end(c)
        c = self._card(t("set.forced"), t("set.forced_hint"))
        self._switch(c, t("set.forced_on"), "forced_break.enabled")
        self._slider(c, t("set.work_minutes"), "forced_break.work_minutes", 15, 180, 5, unit=t("set.min"))
        self._slider(c, t("set.break_minutes"), "forced_break.break_minutes", 1, 30, 1, unit=t("set.min"))
        self._switch(c, t("set.allow_skip"), "forced_break.allow_skip")
        self._end(c)

    def _sec_mouse(self):
        c = self._card(t("set.sec.mouse"))
        self._choice(c, t("set.mouse_mode"), "mouse_mode",
                     [("off", t("set.mouse_off")), ("monitor", t("set.mouse_monitor")), ("eyes", t("set.mouse_eyes"))],
                     hint=t("set.mouse_hint"))
        self._end(c)

        c = self._card(t("set.mouse_monitor"), t("set.monitor_hint"))
        n = len(self.cfg["calibration"])
        self._row(c, t("set.calibrate"), lambda p: self._ghost(p, t("menu.calibrate"), self._calibrate_monitors,
                                                                 width=170),
                  hint=t("set.cal_state_ok", n=n) if n >= 2 else t("set.cal_state_none"))
        self._slider(c, t("set.gaze_stable"), "gaze_stable_seconds", 0.2, 2.0, 0.1, kind=float, unit=t("set.sec"))
        self._end(c)

        c = self._card(t("set.mouse_eyes"), t("set.eyes_hint"))
        ec = self.cfg["eye_calibration"]
        state = t("set.eyes_ok", px=ec.get("error_px", "?")) if ec.get("wx") else t("set.cal_state_none")
        self._row(c, t("set.calibrate"), lambda p: self._ghost(p, t("set.eyes_cal"), self._calibrate_eyes, width=170),
                  hint=state)
        self._slider(c, t("set.eye_deadzone"), "eye_deadzone_px", 20, 300, 10, unit="px",
                     hint=t("set.eye_deadzone_hint"))
        self._slider(c, t("set.eye_pause"), "eye_pause_after_mouse_seconds", 0.5, 5.0, 0.5, kind=float,
                     unit=t("set.sec"))
        self._end(c)

    def _sec_laptop(self):
        role = self.cfg["role"]
        c = self._card(t("set.sec.laptop"), t("set.laptop_hint"))
        self._switch(c, t("set.network_on"), "network_enabled")
        self._info(c, t("set.link_state"), "link_state")
        if role == "desktop":
            addrs = "  ".join(network.local_addresses()) or "-"
            self._row(c, t("set.my_ip"), lambda p: ctk.CTkLabel(p, text=addrs, font=self.f_bold, text_color=FG),
                      hint=t("set.my_ip_hint"))
            self._entry(c, t("set.token"), "token", width=230, readonly=True, hint=t("set.token_hint"))
            self._row(c, "", self._token_buttons)
            self._info(c, t("set.firewall"), "firewall", hint=t("set.firewall_hint"))
            self._row(c, "", lambda p: self._ghost(p, t("set.firewall_allow"), self._allow_firewall, width=220))
            self._check_firewall()
        else:
            self._entry(c, t("set.desktop_ip"), "desktop_host", width=200)
            self._row(c, "", lambda p: self._ghost(p, t("set.find"), self._find_desktop, width=200),
                      hint=t("set.find_hint"))
            self._info(c, t("set.found"), "found")
            self._entry(c, t("set.token"), "token", width=230, hint=t("set.token_paste"))
            self._row(c, t("set.test_link"), lambda p: self._ghost(p, t("set.test"), self._test_link, width=120))
            self._info(c, t("set.test_result"), "link_test")
        self._entry(c, t("set.port"), "port", width=110, kind=int)
        self._end(c)

        if role == "desktop":
            c = self._card(t("set.notifs"), t("set.notifs_hint"))
            mons = winapi.list_monitors()
            opts = [(-1.0, t("set.main_display"))] + [
                (float(m.index), t("set.monitor_n", n=m.index + 1) + (" ★" if m.primary else "")) for m in mons]
            self._menu(c, t("set.notif_monitor"), "notification_monitor", opts, kind=int)
            self._end(c)
            c = self._card("Mouse Without Borders", t("set.mwb_hint"))
            self._switch(c, t("set.mwb_on"), "mwb.enabled")
            keys = [(float(i), f"Ctrl+Alt+F{i}") for i in range(1, 5)]
            self._menu(c, t("set.mwb_desktop"), "mwb.desktop_hotkey", keys, kind=int)
            self._menu(c, t("set.mwb_laptop"), "mwb.laptop_hotkey", keys, kind=int)
            self._end(c)
        else:
            c = self._card(t("set.notifs"))
            self._switch(c, t("set.forward"), "forward_notifications", hint=t("set.forward_hint"))
            self._switch(c, t("set.dismiss"), "dismiss_forwarded")
            self._switch(c, t("set.laptop_camera"), "laptop_use_camera", hint=t("set.laptop_camera_hint"))
            self._end(c)

    def _sec_about(self):
        c = ctk.CTkFrame(self.body, fg_color=PANEL, corner_radius=16, border_width=1, border_color=BORDER)
        c.pack(fill="x", padx=22, pady=18)
        logo = asset_path("logo.png")
        if logo:
            self.about_img = ctk.CTkImage(Image.open(logo), size=(96, 96))
            ctk.CTkLabel(c, image=self.about_img, text="").pack(pady=(24, 8))
        ctk.CTkLabel(c, text=APP_NAME, font=self.f_title, text_color=FG).pack()
        ctk.CTkLabel(c, text=t("about.version", v=APP_VERSION), font=self.f_body, text_color=MUTED).pack()
        ctk.CTkLabel(c, text=t("about.tagline"), font=self.f_body, text_color=FG).pack(pady=(12, 0))
        ctk.CTkLabel(c, text=t("about.by", a=APP_AUTHOR), font=self.f_bold, text_color=FG).pack(pady=(10, 0))
        for text, url in ((APP_WEBSITE.split("://", 1)[-1].rstrip("/"), APP_WEBSITE),
                          (APP_REPO.split("://", 1)[-1], APP_REPO)):
            lbl = ctk.CTkLabel(c, text=text, font=self.f_body, text_color=ORANGE, cursor="hand2")
            lbl.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
            lbl.pack()
        ctk.CTkLabel(c, text=t("about.license"), font=self.f_small, text_color=MUTED).pack(pady=(12, 0))
        ctk.CTkLabel(c, text=t("about.privacy"), font=self.f_small, text_color=FAINT_TEXT,
                     wraplength=520).pack(pady=(4, 24))

    # ------------------------------------------------------------ actions
    def _drank(self):
        self.ctrl.drank_water()
        self._flash(t("set.water_reset"))

    def _toggle_camera(self):
        if self.ctrl.camera_lent_to:
            self.ctrl.take_camera_back()
        else:
            self.ctrl.release_camera()

    def _check_firewall(self):
        from . import firewall
        self._set_live("firewall", t("set.testing"), MUTED)
        self._background(firewall.rule_exists, lambda ok: self._set_live(
            "firewall", t("set.firewall_ok") if ok else t("set.firewall_missing"), OK_GREEN if ok else ORANGE))

    def _allow_firewall(self):
        from . import firewall
        if firewall.allow():
            self.win.after(4000, self._check_firewall)

    def _token_buttons(self, p):
        box = ctk.CTkFrame(p, fg_color="transparent")
        self._ghost(box, t("set.copy"), self._copy_token, width=100).pack(side="left", padx=4)
        self._ghost(box, t("set.new_token"), self._new_token, width=130).pack(side="left", padx=4)
        return box

    def _copy_token(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.fields["token"][0].get())
        self._flash(t("set.copied"))

    def _new_token(self):
        import secrets
        self.fields["token"][0].set(secrets.token_urlsafe(16))
        self._flash(t("set.token_changed"), color=ORANGE)

    def _background(self, work, done):
        """Runs work() in a thread and done(result) back on the Tk thread."""
        def run():
            try:
                result = work()
            except Exception:
                log.exception("Background task failed")
                result = None
            self.ui.call(lambda: self.alive and done(result))
        threading.Thread(target=run, daemon=True).start()

    def _set_live(self, key, text, color=FG):
        lbl = self.live.get(key)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=text, text_color=color)

    def _find_desktop(self):
        self._set_live("found", t("set.searching"), MUTED)
        port = int(self.fields["port"][0].get())

        def done(found):
            if found:
                ip, name = found[0]
                self.fields["desktop_host"][0].set(ip)
                self._set_live("found", f"{name} ({ip})", OK_GREEN)
            else:
                self._set_live("found", t("set.not_found"), DANGER)
        self._background(lambda: network.discover(port), done)

    def _test_link(self):
        self._set_live("link_test", t("set.testing"), MUTED)
        host = self.fields["desktop_host"][0].get().strip()
        token = self.fields["token"][0].get().strip()
        port = int(self.fields["port"][0].get())
        colors = {"ok": OK_GREEN}
        self._background(lambda: network.test_connection(host, port, token),
                         lambda r: self._set_live("link_test", t(f"set.link_{r or 'unreachable'}"),
                                                  colors.get(r, DANGER)))

    def _test_phone(self):
        dev = self.fields["phone.device_id"][0].get()
        if not dev:
            self._set_live("phone_test", t("set.phone_choose"), DANGER)
            return
        self._set_live("phone_test", t("set.testing"), MUTED)
        self._background(lambda: phone.probe(dev),
                         lambda ok: self._set_live("phone_test", t("set.phone_near") if ok else t("set.phone_gone"),
                                                   OK_GREEN if ok else DANGER))

    def _calibrate_monitors(self):
        self.save(quiet=True)
        self.win.iconify()
        self.ctrl.start_calibration()

    def _calibrate_eyes(self):
        self.fields["mouse_mode"][0].set("eyes")
        self.save(quiet=True)
        self.win.iconify()
        self.ctrl.start_eye_calibration()

    def _flash(self, text, color=OK_GREEN):
        self.saved_lbl.configure(text=text, text_color=color)
        self.win.after(3000, lambda: self.alive and self.saved_lbl.configure(text=""))

    def save(self, quiet=False):
        old = copy.deepcopy(self.cfg.data)
        data = self.cfg.data
        for path, (var, kind) in self.fields.items():
            try:
                raw = var.get()
            except tk.TclError:
                continue
            if kind is int:
                value = int(round(float(raw)))
            elif kind is float:
                value = round(float(raw), 2)
            elif kind is bool:
                value = bool(raw)
            else:
                value = str(raw).strip()
            _set(data, path, value)
        if self.fields.get("phone.device_id"):
            data["phone"]["name"] = self._phone_names.get(data["phone"]["device_id"], "")
        if self.media_vars:
            apps = {k: v.get() for k, v in self.media_vars.items() if v.get() != "auto"}
            data["media_apps"] = apps
        self.cfg.save()
        set_language(data["language"])
        self.ctrl.apply_settings(old)
        self.on_saved()
        if quiet:
            return
        if old["language"] != data["language"] or old["role"] != data["role"]:
            section = self.section
            self.win.destroy()
            self.fields, self.media_vars = {}, {}
            self.section = section
            self._build()
        elif old.get("network_enabled") != data["network_enabled"] and self.section == "laptop":
            self.show("laptop")  # the role-dependent rows change
        self._flash(t("set.saved"))

    # ------------------------------------------------------------ live values
    def _tick(self):
        if not self.alive:
            return
        try:
            self._update_live()
        except Exception:
            log.debug("settings tick failed", exc_info=True)
        self.win.after(400, self._tick)

    def _update_live(self):
        ctrl = self.ctrl
        if "camera_state" in self.live:
            if getattr(self, "cam_btn", None) is not None and self.cam_btn.winfo_exists():
                self.cam_btn.configure(text=t("menu.cam_take") if ctrl.camera_lent_to else t("menu.cam_give"))
            if ctrl.camera_lent_to:
                self._set_live("camera_state", t("status.camera_lent_to", app=ctrl.camera_lent_to[1]), ORANGE)
            elif ctrl.status == "camera_busy":
                self._set_live("camera_state", t("status.camera_busy"), ORANGE)
            elif ctrl.sensor is not None:
                self._set_live("camera_state", t("set.cam_on"), OK_GREEN)
            elif ctrl.next_check_seconds() is not None:
                self._set_live("camera_state", t("set.cam_waiting", s=int(ctrl.next_check_seconds())), MUTED)
            else:
                self._set_live("camera_state", t("set.cam_off"), MUTED)
        if "owner_state" in self.live:
            n = len(self.cfg["owner_faces"])
            if ctrl._enroll is not None:
                self._set_live("owner_state", t("set.owner_learning"), ORANGE)
            elif n:
                self._set_live("owner_state", t("set.owner_saved", n=n), OK_GREEN)
            else:
                self._set_live("owner_state", t("set.owner_none"), MUTED)
        # the preview needs frames, so the webcam stays on while it is shown (even in interval mode)
        ctrl.camera_hold = self.preview_lbl is not None and self.preview_lbl.winfo_exists()
        if self.preview_lbl is not None and self.preview_lbl.winfo_exists():
            sensor = ctrl.sensor
            frame = sensor.last_frame if sensor is not None else None
            if frame is not None:
                rgb = frame[:, :, ::-1]
                img = Image.fromarray(rgb)
                if sensor.last_box:
                    x, y, w, h = sensor.last_box
                    ImageDraw.Draw(img).rounded_rectangle((x, y, x + w, y + h), radius=12, outline=ORANGE, width=4)
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
                self.preview_img = ctk.CTkImage(img, size=(320, int(320 * img.height / img.width)))
                self.preview_lbl.configure(image=self.preview_img, text="")
        if "phone_live" in self.live:
            near = ctrl.phone_near
            if near is None:
                self._set_live("phone_live", t("set.phone_unknown"), MUTED)
            else:
                self._set_live("phone_live", t("set.phone_near") if near else t("set.phone_gone"),
                               OK_GREEN if near else DANGER)
        if "t_water" in self.live:
            tm = ctrl.timers()

            def mins(v):
                return t("set.off") if v is None else t("widget.min", n=int(v // 60))
            self._set_live("t_water", mins(tm["water_left"]))
            if tm["break_active"]:
                s = int(tm["break_remaining"] or 0)
                self._set_live("t_break", f"{s // 60:02d}:{s % 60:02d}", ORANGE)
            else:
                self._set_live("t_break", mins(tm["break_left"]))
            self._set_live("t_sit", mins(tm["sitting"]))
            if "t_exercise" in self.live:
                self._set_live("t_exercise", mins(tm["exercise_left"]))
        if "link_state" in self.live:
            if not self.cfg["network_enabled"]:
                self._set_live("link_state", t("set.link_disabled"), MUTED)
            elif ctrl.link and ctrl.link.error:
                self._set_live("link_state", t("set.link_error", err=ctrl.link.error[:60]), DANGER)
            elif ctrl.link and ctrl.link.connected:
                names = ", ".join(ctrl.link.peer_names)
                self._set_live("link_state", t("set.link_connected", names=names), OK_GREEN)
            else:
                self._set_live("link_state", t("set.link_waiting"), ORANGE)
