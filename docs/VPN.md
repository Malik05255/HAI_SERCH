# VPN / Egress داخل السيرفر

الـVPN جزء من السيرفر فقط، وليس من Android أو Windows.

## التشغيل الافتراضي

بدون أي إعداد VPN:

```bash
docker compose up -d
```

يعمل البحث بالاتصال المباشر. `EGRESS_MODE=auto` لا يسبب أي فشل إذا لم يوجد `EGRESS_PROXY_URL`.

## تشغيل WireGuard

1. احصل على **WireGuard client configuration** من مخرج تملكه أو مزود يسمح باستخدامه.
2. احفظ الملف محليًا فقط في:

```text
infra/wireguard/wg_confs/wg0.conf
```

هذا المسار مستثنى من Git ولا تُرفع المفاتيح الخاصة إلى GitHub.

3. شغّل الـoverlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.vpn.yml up -d --build
```

الـoverlay يضيف:

```text
Worker
  -> direct Internet
  -> http://wireguard:8888
       -> Tinyproxy
       -> WireGuard tunnel
       -> Internet
```

صورة LinuxServer WireGuard تعمل في **client mode** عندما لا يتم ضبط `PEERS` وتوجد ملفات `.conf` داخل `/config/wg_confs/`.

## أوضاع الخروج

```env
EGRESS_MODE=auto
```

- `auto`: اتصال مباشر أولًا، ثم VPN فقط عند خطأ شبكة/مهلة أو HTTP 451.
- `direct`: يمنع استخدام VPN.
- `vpn`: يجبر طلبات الويب العامة على VPN ويتطلب `EGRESS_PROXY_URL`.

في `docker-compose.vpn.yml` يتم ضبط عنوان البروكسي للـWorker تلقائيًا على:

```text
http://wireguard:8888
```

## قواعد الثبات

- المسار الناجح يصبح sticky لنفس النطاق أثناء جولة البحث.
- لا يوجد تدوير IP عشوائي.
- لا يتم تبديل المسار تلقائيًا بسبب 403 أو 429 أو CAPTCHA.
- SearXNG وPostgreSQL وVision خدمات داخلية ولا تمر عبر بروكسي VPN.

## عدة دول

WireGuard نفسه مجاني. لكن كل دولة تحتاج endpoint فعليًا في تلك الدولة. يمكن لاحقًا إضافة عدة overlays / exit nodes، لكن لا توجد عقد متعددة الدول مجانية تلقائيًا بمجرد تثبيت WireGuard.
