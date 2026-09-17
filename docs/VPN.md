# VPN / Egress داخل السيرفر

الـVPN جزء من السيرفر فقط، وليس من Android أو Windows.

## التشغيل الافتراضي

بدون أي إعداد VPN:

```bash
docker compose up -d
```

يعمل البحث بالاتصال المباشر. `EGRESS_MODE=auto` لا يسبب أي فشل إذا لم يوجد أي proxy exit.

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

- `auto`: اتصال مباشر أولًا، ثم مخارج السيرفر فقط عند خطأ شبكة/مهلة أو HTTP 451.
- `direct`: يمنع استخدام أي VPN/proxy exit.
- `vpn`: يجبر طلبات الويب العامة على مخارج البروكسي المعرفة في السيرفر ويتطلب مخرجًا واحدًا على الأقل.

في `docker-compose.vpn.yml` يتم ضبط المخرج الافتراضي للـWorker تلقائيًا على:

```text
http://wireguard:8888
```

ويمكن إبقاء هذا المخرج في المتغير القديم:

```env
EGRESS_PROXY_URL=http://wireguard:8888
```

## مخارج متعددة

يمكن إضافة مخارج HTTP(S) داخلية أو خاصة بالسيرفر بدون أي تغيير في تطبيق Android أو Windows:

```env
EGRESS_PROXY_URLS=asia=http://vpn-asia:8888,europe=http://vpn-europe:8888
```

ويمكن الجمع بين المخرج القديم والمخارج المسماة:

```env
EGRESS_PROXY_URL=http://wireguard:8888
EGRESS_PROXY_URLS=asia=http://vpn-asia:8888,europe=http://vpn-europe:8888
```

المسارات المتاحة عندها تكون مثل:

```text
direct
vpn
asia
europe
```

كل proxy endpoint يجب أن يكون endpoint فعليًا ومشروعًا يملكه المستخدم أو يسمح مزوده باستخدامه. إضافة الاسم وحدها لا تنشئ خادمًا أو IP في تلك الدولة.

## قواعد الثبات والفشل

- المسار الناجح يصبح sticky لنفس النطاق أثناء عمر جولة البحث.
- لا يوجد تدوير IP عشوائي.
- لا يتم تبديل المسار تلقائيًا بسبب 403 أو 429 أو CAPTCHA.
- التبديل مسموح فقط لأخطاء النقل/المهلة أو HTTP 451.
- تكرار أخطاء النقل يفتح circuit breaker مؤقتًا لذلك المخرج حتى لا يعيد الـWorker ضرب endpoint معطوب بلا فائدة.
- SearXNG وPostgreSQL وVision خدمات داخلية ولا تمر عبر proxy الخاص بطلبات الصفحات العامة.

## عدة دول

WireGuard نفسه مجاني. لكن كل دولة تحتاج endpoint فعليًا في تلك الدولة. دعم المخارج المتعددة موجود في الـWorker، أما توفير تلك العقد نفسها فيظل مسؤولية البنية التحتية/المزود.
