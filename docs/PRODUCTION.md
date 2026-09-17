# Production deployment

المسار الإنتاجي مصمم لخادم Ubuntu واحد اقتصادي (مثل Oracle Ampere) مع Docker Compose.

## قبل النشر مرة واحدة

1. وجّه DNS الخاص بـ `PUBLIC_HOST` إلى عنوان الخادم.
2. افتح TCP 80/443 في Cloud firewall، وUDP 443 اختياري لـ HTTP/3.
3. شغّل bootstrap بحساب يملك sudo:
   `sudo bash scripts/bootstrap_server.sh <ssh-user>`
4. أنشئ `.env` من `.env.example` وغير كل القيم التجريبية.
5. تحقق:
   `python3 scripts/validate_production_env.py .env`

Caddy يحصل على شهادة TLS تلقائيًا. منفذ FastAPI 8000 مربوط بـ localhost فقط ولا يُكشف مباشرة للإنترنت.

## GitHub Environment / Secrets

أنشئ Environment باسم `production` وضع الأسرار التالية:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_KNOWN_HOSTS` — سطر host key موثوق، وليس نتيجة ssh-keyscan غير موثقة داخل workflow.
- `DEPLOY_PATH` — يوصى `/opt/hai-search`
- `PRODUCTION_ENV_B64` — محتوى ملف `.env` الإنتاجي كاملًا بعد Base64.

ثم شغّل workflow **Deploy Production**. يمكن اختيار bootstrap لأول مرة إذا كان المستخدم يملك passwordless sudo.

النشر لا ينفذ `docker compose down`. إذا فشل health check المحلي أو HTTPS، يحاول الرجوع تلقائيًا إلى commit السابق.

## أسرار Release

لإصدار Android/Windows يلزم أيضًا:

- `API_BASE_URL`
- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`
- `ANDROID_KEYSTORE_PASSWORD`
- `FIREBASE_API_KEY`
- `FIREBASE_APP_ID`
- `FIREBASE_MESSAGING_SENDER_ID`
- `FIREBASE_PROJECT_ID`

لا ترفع أي قيمة من هذه إلى المستودع.

## أول Release

بعد نجاح النشر:

- افتح Actions → Release → Run workflow.
- أدخل نسخة مثل `v1.0.0`.
- الـworkflow يبني APK موقعًا وWindows installer، يحسب SHA-256، وينشئ GitHub Release.
- التطبيق يتحقق من SHA-256 قبل فتح المثبت.

يمكن لاحقًا الاستمرار بالطريقة التقليدية عبر push لتاغ `v*`.
