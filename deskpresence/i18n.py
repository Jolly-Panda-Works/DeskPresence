"""UI strings in Persian (fa) and English (en)."""
import ctypes

STRINGS = {
    # tray menu
    "menu.pause": {"fa": "توقف موقت", "en": "Pause"},
    "menu.gaze": {"fa": "موس دنبال نگاه من بیاید", "en": "Move the mouse to where I look"},
    "menu.calibrate": {"fa": "کالیبره کردن نگاه…", "en": "Calibrate gaze…"},
    "menu.break_now": {"fa": "شروع استراحت همین الان", "en": "Start a break now"},
    "menu.break_end": {"fa": "پایان استراحت", "en": "End the break"},
    "menu.test_off": {"fa": "تست: خاموش کردن مانیتورها", "en": "Test: turn monitors off"},
    "menu.autostart": {"fa": "اجرا همراه ویندوز", "en": "Start with Windows"},
    "menu.language": {"fa": "زبان / Language", "en": "Language / زبان"},
    "menu.settings": {"fa": "ویرایش تنظیمات", "en": "Edit settings"},
    "menu.reload": {"fa": "اعمال تنظیمات ذخیره‌شده", "en": "Apply saved settings"},
    "menu.folder": {"fa": "پوشه برنامه و لاگ", "en": "App & log folder"},
    "menu.about": {"fa": "درباره DeskPresence", "en": "About DeskPresence"},
    "menu.quit": {"fa": "خروج", "en": "Quit"},

    # status line
    "role.desktop": {"fa": "کامپیوتر", "en": "Desktop"},
    "role.laptop": {"fa": "لپ‌تاپ", "en": "Laptop"},
    "status.starting": {"fa": "در حال شروع...", "en": "Starting..."},
    "status.paused": {"fa": "متوقف شده", "en": "Paused"},
    "status.present": {"fa": "حاضر", "en": "At the desk"},
    "status.away": {"fa": "دور از میز", "en": "Away"},
    "status.break": {"fa": "استراحت اجباری", "en": "On a break"},
    "status.camera_error": {"fa": "خطا: وبکم باز نشد", "en": "Error: cannot open the webcam"},
    "status.laptop_wait": {"fa": "منتظر دستور از کامپیوتر اصلی", "en": "Waiting for the desktop"},
    "status.next_break": {"fa": "استراحت بعدی: {mins} دقیقه", "en": "Next break: {mins} min"},
    "status.link": {"fa": "اتصال: {state}", "en": "Link: {state}"},
    "status.link_on": {"fa": "برقرار", "en": "connected"},
    "status.link_off": {"fa": "قطع", "en": "disconnected"},

    # popups
    "app.running": {"fa": "DeskPresence در حال اجراست (آیکون کنار ساعت).",
                    "en": "DeskPresence is already running (icon next to the clock)."},
    "welcome.title": {"fa": "DeskPresence فعال شد", "en": "DeskPresence is on"},
    "welcome.body": {"fa": "برای اینکه موس دنبال نگاهتان بیاید، از منوی آیکون کنار ساعت «کالیبره کردن نگاه» را بزنید.",
                     "en": "To make the mouse follow your gaze, choose “Calibrate gaze” from the tray icon menu."},
    "reload.title": {"fa": "تنظیمات اعمال شد", "en": "Settings applied"},
    "reload.body": {"fa": "تغییر role یا تنظیمات شبکه بعد از اجرای دوباره برنامه اعمال می‌شود.",
                    "en": "Changes to role or network settings take effect after restarting the app."},
    "water.title": {"fa": "💧 وقت آب خوردن!", "en": "💧 Time to drink water!"},
    "water.body": {"fa": "یک لیوان آب بنوشید.", "en": "Have a glass of water."},
    "remind.title": {"fa": "وقت تکان خوردن!", "en": "Time to move!"},
    "remind.body": {"fa": "{mins} دقیقه است که پشت میز نشسته‌اید. کمی بلند شوید و راه بروید.",
                    "en": "You have been sitting for {mins} minutes. Stand up and walk a little."},
    "break.done.title": {"fa": "استراحت تمام شد ✓", "en": "Break is over ✓"},
    "break.done.body": {"fa": "خوش برگشتید! ادامه کار.", "en": "Welcome back!"},

    # break screen
    "break.title": {"fa": "☕  وقت استراحت", "en": "☕  Break time"},
    "break.hint": {"fa": "از پشت میز بلند شوید، کمی راه بروید و به دوردست نگاه کنید.",
                   "en": "Get up, walk around and look at something far away."},
    "break.counting": {"fa": "⏳ تایمر در حال شمارش است - تا تمام شدن آن برنگردید",
                       "en": "⏳ The timer is running - don't come back until it ends"},
    "break.waiting": {"fa": "⏸ تایمر وقتی شروع می‌شود که دوربین شما را پشت میز نبیند",
                      "en": "⏸ The timer starts once the camera no longer sees you at the desk"},
    "break.skip": {"fa": "رد کردن استراحت (اضطراری)", "en": "Skip the break (emergency)"},
    "break.skip_confirm": {"fa": "برای تأیید دوباره کلیک کنید", "en": "Click again to confirm"},

    # calibration
    "cal.look_monitor": {"fa": "به مانیتور {n} نگاه کنید", "en": "Look at monitor {n}"},
    "cal.look_laptop": {"fa": "حالا به صفحه لپ‌تاپ نگاه کنید", "en": "Now look at the laptop screen"},
    "cal.hint": {"fa": "صورتتان را به سمت این نقطه بچرخانید و ثابت بمانید",
                 "en": "Turn your face towards this dot and hold still"},
    "cal.ready": {"fa": "آماده...", "en": "Get ready..."},
    "cal.recording": {"fa": "در حال ثبت... {n}", "en": "Recording... {n}"},
    "cal.cancel_hint": {"fa": "Esc = لغو", "en": "Esc = cancel"},
    "cal.title": {"fa": "کالیبراسیون", "en": "Calibration"},
    "cal.no_camera": {"fa": "در این حالت وبکم فعال نیست.", "en": "The webcam is not used in this mode."},
    "cal.not_ready": {"fa": "وبکم آماده نیست یا مدل تشخیص چهره پیدا نشد.",
                      "en": "The webcam is not ready or the face model is missing."},
    "cal.cancelled": {"fa": "کالیبراسیون لغو شد", "en": "Calibration cancelled"},
    "cal.failed": {"fa": "کالیبراسیون ناموفق", "en": "Calibration failed"},
    "cal.failed_body": {"fa": "چهره به اندازه کافی دیده نشد. نور و جای وبکم را بررسی کنید.",
                        "en": "Your face was not seen clearly enough. Check the lighting and webcam position."},
    "cal.done": {"fa": "کالیبراسیون انجام شد ✓", "en": "Calibration done ✓"},
    "cal.done_body": {"fa": "از این به بعد موس به مانیتوری که نگاه می‌کنید می‌رود.",
                      "en": "From now on the mouse moves to the monitor you look at."},
    "cal.missing": {"fa": "ثبت نشد: {names}", "en": "Not recorded: {names}"},

    # about
    "about.version": {"fa": "نسخه {v}", "en": "Version {v}"},
    "about.by": {"fa": "ساخته‌شده توسط {a}", "en": "Created by {a}"},
    "about.tagline": {"fa": "وقتی از پشت میز بلند می‌شوید، کامپیوترتان می‌فهمد.",
                      "en": "Your PC knows when you leave the desk."},
    "about.privacy": {"fa": "تصویر وبکم فقط روی همین کامپیوتر پردازش می‌شود و هیچ‌جا ذخیره یا ارسال نمی‌شود.",
                      "en": "Webcam frames are processed on this PC only. Nothing is saved or uploaded."},
    "about.license": {"fa": "نرم‌افزار متن‌باز - مجوز MIT", "en": "Open source - MIT License"},
    "about.close": {"fa": "بستن", "en": "Close"},
}

LANGUAGES = {"fa": "فارسی", "en": "English"}

_lang = "en"


def system_language():
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fa" if lang_id & 0x3FF == 0x29 else "en"  # LANG_PERSIAN
    except Exception:
        return "en"


def set_language(lang):
    global _lang
    _lang = lang if lang in LANGUAGES else system_language()


def language():
    return _lang


def is_rtl():
    return _lang == "fa"


def t(key, **kw):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_lang) or entry["en"]
    if kw:
        text = text.format(**kw)
    if _lang == "fa":
        # Tk and Win32 menus lay text out left-to-right; a right-to-left embedding per line puts
        # punctuation, emoji and Latin words on the correct side.
        text = "\n".join(f"‫{line}‬" for line in text.split("\n"))
    return text
