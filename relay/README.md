<div dir="rtl">

# سرور واسط DeskPresence (relay)

این سرور کوچک روی سرور مجازی (VPS) خودتان اجرا می‌شود و باعث می‌شود گوشی‌ها **از هر جایی** (اینترنت موبایل، وای‌فای دیگر) به کامپیوترتان وصل شوند و گوشی‌ها وضعیتشان را برای هم بفرستند.

- کامپیوتر و گوشی‌ها فقط **به سمت سرور** وصل می‌شوند. برای همین پشت هر مودم، CGNAT یا اینترنت موبایلی کار می‌کند و لازم نیست پورتی روی مودم خانه باز کنید.
- همه چیز **رمزنگاری سرتاسری** دارد: سرور واسط فقط بسته‌های رمزشده را جابه‌جا می‌کند و تصویر وبکم، پیام‌ها و وضعیت‌ها را نمی‌بیند.
- اگر کامپیوتر خاموش باشد، گوشی‌ها همچنان وضعیتشان را برای هم می‌فرستند.

## نیازمندی‌ها

- یک سرور مجازی لینوکس (اوبونتو یا دبیان) با آی‌پی عمومی؛ کمترین مشخصات کافی است (۱ هسته، ۵۱۲ مگابایت رم).
- یک زیردامنه، مثلا `deskpresence.useffarahmand.com`.
- پورت‌های ۸۰ و ۴۴۳ باز باشند (اگر سرویس‌دهنده پنل فایروال جدا دارد، آنجا هم).

## ۱. تنظیم DNS در ابر آروان

۱. وارد پنل ابر آروان شوید ← دامنه `useffarahmand.com` ← **DNS**.
۲. یک رکورد **A** بسازید:
   - نام: `deskpresence`
   - مقدار: آی‌پی سرور مجازی
   - **پروکسی (ابر نارنجی) را خاموش کنید**. گواهی HTTPS را خود سرور (Caddy) از Let's Encrypt می‌گیرد و اتصال‌های طولانی (تصویر وبکم) باید مستقیم به سرور برسند.
۳. چند دقیقه صبر کنید تا رکورد اعمال شود. بررسی: `ping deskpresence.useffarahmand.com`

## ۲. نصب روی سرور (یک دستور)

با SSH وارد سرور شوید و بزنید:

<div dir="ltr">

```bash
curl -fsSL https://raw.githubusercontent.com/Jolly-Panda-Works/DeskPresence/main/relay/install.sh | sudo bash -s deskpresence.useffarahmand.com
```

</div>

اسکریپت در صورت نیاز Docker را نصب می‌کند، سرور واسط و Caddy را بالا می‌آورد و گواهی HTTPS را خودکار می‌گیرد. بررسی:

<div dir="ltr">

```bash
curl https://deskpresence.useffarahmand.com/health
```

</div>

باید `{"ok": true, ...}` برگرداند. برای به‌روزرسانی، همان دستور نصب را دوباره اجرا کنید.

## ۳. تنظیم کامپیوتر و گوشی

۱. روی کامپیوتر: DeskPresence ← تنظیمات ← **موبایل** ← «آدرس سرور واسط»: `https://deskpresence.useffarahmand.com`. وضعیت باید «متصل به سرور واسط ✓» شود.
۲. «ساخت کد» را بزنید. حالا کد QR و لینک اتصال آماده است. QR را با برنامه گوشی اسکن کنید، یا لینک را برای گوشی بفرستید.
۳. از این به بعد گوشی در خانه از طریق وای‌فای (سریع‌تر) و بیرون از خانه از طریق سرور واسط به کامپیوتر وصل می‌شود؛ خودکار.

## اتصال دو گوشی

در برنامه گوشی ← تب **افراد** ← «دعوت گوشی». روی گوشی دیگر ← «پیوستن» و QR را اسکن کنید، کد ۶ رقمی را بزنید، یا لینک را باز کنید. از آن به بعد وضعیت (در دسترس / مشغول / …)، باتری، در حال تماس بودن و آخرین زمان فعالیت هر دو گوشی برای هم نمایش داده می‌شود.

## نگهداری

<div dir="ltr">

```bash
cd /opt/deskpresence/relay
docker compose logs -f relay     # logs
docker compose restart           # restart
```

</div>

داده‌ها (فهرست کامپیوترها، گوشی‌ها و آخرین وضعیت رمزشده هر گوشی) در volume `relay-data` در یک فایل SQLite نگهداری می‌شوند.

</div>

---

## English summary

A tiny relay for your own VPS: the PC and phones connect *out* to it, so phones reach the PC from anywhere (mobile data, other networks, CGNAT), and phones exchange statuses even while the PC is off. Everything is end-to-end encrypted; the relay forwards sealed envelopes only.

1. DNS: an **A** record `deskpresence.example.com` → the VPS IP (CDN proxy **off**).
2. On the VPS: `curl -fsSL https://raw.githubusercontent.com/Jolly-Panda-Works/DeskPresence/main/relay/install.sh | sudo bash -s deskpresence.example.com`
3. On the PC: Settings → Mobile app → Relay address → `https://deskpresence.example.com`.

Protocol: see the docstring at the top of [relay.py](relay.py). Run the tests with `python -m pytest tests/test_relay.py` from the repository root.
