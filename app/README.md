# تطبيق البحث العميق

قاعدة Flutter واحدة لـ Android وWindows.

## إنشاء ملفات المنصات أول مرة

```bash
cd app
flutter create --platforms=android,windows --project-name deep_search .
python ../scripts/prepare_platforms.py
python ../scripts/generate_icon.py
flutter pub get
```

## التشغيل

```bash
flutter run --dart-define=API_BASE_URL=https://YOUR_SERVER --dart-define=API_TOKEN=YOUR_TOKEN
```

لا يخزن التطبيق نتائج البحث كمصدر أساسي؛ السيرفر هو المصدر، لذلك نفس المهام تظهر على Android وWindows.
