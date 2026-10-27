"""The exercise window: the webcam picture with your body lines, the count and live feedback.

Runs on the Tk thread and only reads controller.exercise_view, which the camera thread replaces
with every frame.
"""
import logging
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from .exercise import (L_ELBOW, L_SHOULDER, L_WRIST, NOSE, R_ELBOW, R_SHOULDER, R_WRIST, VISIBLE)
from .i18n import is_rtl, t
from .ui import (BG, BORDER, FAINT_TEXT, FG, FONT, MUTED, ON_ORANGE, ORANGE, ORANGE_H, PANEL, PANEL_H,
                 style_titlebar)

log = logging.getLogger(__name__)

GOOD = "#4ADE80"
FIX = "#FBBF24"
VIEW_W = 560
BONES = ((L_SHOULDER, R_SHOULDER), (L_SHOULDER, L_ELBOW), (L_ELBOW, L_WRIST), (R_SHOULDER, R_ELBOW),
         (R_ELBOW, R_WRIST), (7, 8), (11, 23), (12, 24), (23, 24))
CLOSE_AFTER_DONE_MS = 5000


class ExerciseWindow:
    def __init__(self, root, ctrl, monitor):
        self.ctrl = ctrl
        self._closing = False
        self._last_count = -1
        rtl = is_rtl()
        anchor = "e" if rtl else "w"
        win = self.win = tk.Toplevel(root, bg=BG)
        win.title(t("ex.title"))
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.stop)
        win.resizable(False, False)
        for ms in (0, 60, 300):
            win.after(ms, lambda: style_titlebar(win))

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=20, pady=(16, 4))
        self.step_lbl = tk.Label(head, text="", bg=BG, fg=ORANGE, font=(FONT, 9, "bold"), anchor=anchor)
        self.step_lbl.pack(fill="x")
        self.name_lbl = tk.Label(head, text="", bg=BG, fg=FG, font=(FONT, 18, "bold"), anchor=anchor)
        self.name_lbl.pack(fill="x")
        self.how_lbl = tk.Label(head, text="", bg=BG, fg=MUTED, font=(FONT, 10), anchor=anchor,
                                justify="right" if rtl else "left", wraplength=VIEW_W + 220)
        self.how_lbl.pack(fill="x", pady=(2, 0))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", padx=20, pady=8)
        # an image from the start, so the label is sized in pixels (text-only labels count characters)
        self._img = ImageTk.PhotoImage(Image.new("RGB", (VIEW_W, int(VIEW_W * 0.75)), PANEL))
        self.view = tk.Label(body, bg=PANEL, fg=MUTED, text=t("ex.camera_starting"), font=(FONT, 10),
                             image=self._img, compound="center")
        self.view.pack(side="right" if rtl else "left")
        side = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, width=210)
        side.pack(side="left" if rtl else "right", fill="y", padx=(0, 12) if rtl else (12, 0))
        side.pack_propagate(False)
        tk.Label(side, text=t("ex.reps"), bg=PANEL, fg=MUTED, font=(FONT, 9, "bold")).pack(pady=(24, 0))
        self.count_lbl = tk.Label(side, text="0", bg=PANEL, fg=FG, font=(FONT, 54, "bold"))
        self.count_lbl.pack()
        self.target_lbl = tk.Label(side, text="", bg=PANEL, fg=FAINT_TEXT, font=(FONT, 11))
        self.target_lbl.pack()
        self.bar = tk.Canvas(side, width=170, height=8, bg=PANEL_H, highlightthickness=0)
        self.bar.pack(pady=(10, 0))
        self.msg_lbl = tk.Label(side, text="", bg=PANEL, fg=FG, font=(FONT, 13, "bold"), wraplength=180,
                                justify="center")
        self.msg_lbl.pack(fill="x", padx=12, pady=(24, 0))

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=20, pady=(4, 16))
        far = "left" if rtl else "right"
        self._button(row, t("ex.stop"), self.stop).pack(side=far)
        self._button(row, t("ex.later"), self.later).pack(side=far, padx=8)
        self.next_btn = self._button(row, t("ex.next"), self.ctrl.skip_exercise, primary=True)
        self.next_btn.pack(side=far)

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        l, t_, r, b = monitor.work
        win.geometry(f"+{l + max(0, (r - l - w) // 2)}+{t_ + max(0, (b - t_ - h) // 2)}")
        win.lift()
        win.focus_force()
        self._tick()

    @staticmethod
    def _button(parent, text, command, primary=False):
        if primary:
            return tk.Button(parent, text=text, command=command, bg=ORANGE, fg=ON_ORANGE, activebackground=ORANGE_H,
                             activeforeground=ON_ORANGE, relief="flat", bd=0, font=(FONT, 10, "bold"), padx=16,
                             pady=7, cursor="hand2")
        return tk.Button(parent, text=text, command=command, bg=PANEL_H, fg=FG, activebackground=BORDER,
                         activeforeground=FG, relief="flat", bd=0, font=(FONT, 10), padx=16, pady=7, cursor="hand2")

    @property
    def alive(self):
        return self.win is not None and self.win.winfo_exists()

    def stop(self):
        self.ctrl.stop_exercise()
        self.close()

    def later(self):
        self.ctrl.stop_exercise(later=True)
        self.close()

    def close(self):
        if self.alive:
            self.win.destroy()
        self.win = None

    # ------------------------------------------------------------ live
    def _tick(self):
        if not self.alive:
            return
        try:
            self._update()
        except Exception:
            log.debug("exercise window update failed", exc_info=True)
        if self.alive:
            self.win.after(66, self._tick)

    def _update(self):
        view = self.ctrl.exercise_view
        if view is None or (self.ctrl.exercise is None and not self._closing):
            self.close()
            return
        snap = view["snap"]
        key = snap["move"]
        self.step_lbl.configure(text=t("ex.step", i=snap["index"] + 1, n=snap["total"]).upper())
        self.name_lbl.configure(text=t(f"ex.name.{key}"))
        self.how_lbl.configure(text=t(f"ex.how.{key}"))
        self.count_lbl.configure(text=str(snap["count"]), fg=GOOD if snap["count"] >= snap["target"] else FG)
        self.target_lbl.configure(text=t("ex.of", n=snap["target"]))
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, int(170 * min(1.0, snap["count"] / snap["target"])), 8, fill=ORANGE, width=0)
        color = {"good": GOOD, "fix": FIX}.get(snap["tone"], FG)
        self.msg_lbl.configure(text=t(snap["message"]), fg=color)
        if view["frame"] is not None:
            self._draw(view["frame"], view["lm"], color)
        if snap["done"] and not self._closing:
            self._closing = True
            self.next_btn.configure(state="disabled")
            self.win.after(CLOSE_AFTER_DONE_MS, self.stop)

    def _draw(self, frame, lm, color):
        img = Image.fromarray(frame[:, :, ::-1])
        if lm is not None:
            d = ImageDraw.Draw(img)
            for a, b in BONES:
                if lm[a][3] >= VISIBLE and lm[b][3] >= VISIBLE:
                    d.line((lm[a][0], lm[a][1], lm[b][0], lm[b][1]), fill=color, width=5)
            for i in (NOSE, L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST):
                if lm[i][3] >= VISIBLE:
                    x, y = lm[i][0], lm[i][1]
                    d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=ORANGE)
        img = img.transpose(Image.FLIP_LEFT_RIGHT)  # like a mirror
        img = img.resize((VIEW_W, int(VIEW_W * img.height / img.width)))
        self._img = ImageTk.PhotoImage(img)
        self.view.configure(image=self._img, text="")
