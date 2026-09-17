# التحديثات فوق النسخة الحالية

## Android

التطبيق يفحص أحدث GitHub Release ويمكنه تنزيل APK وفتح مثبت Android. Android يثبت الإصدار فوق الحالي ويحافظ على بيانات التطبيق **فقط إذا بقي `applicationId` ومفتاح التوقيع نفسه**.

لذلك لا نخزن مفتاح التوقيع في المستودع العام. أضف GitHub Actions secrets مرة واحدة:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`
- `ANDROID_KEYSTORE_PASSWORD`
- `API_BASE_URL`
- `API_TOKEN`

كل الإصدارات اللاحقة يجب أن تستخدم نفس keystore. Android قد يطلب من المستخدم السماح لهذا التطبيق بتثبيت تطبيقات من هذا المصدر أول مرة؛ هذا قيد من النظام ولا ينبغي تجاوزه.

## Windows

GitHub Release يبني Inno Setup installer بمعرف `AppId` ثابت. تشغيل المثبت الجديد يحدّث ملفات البرنامج في نفس المكان بدل إنشاء تطبيق منفصل. البيانات الحقيقية للمهمات والنتائج تبقى على السيرفر أساسًا.

## إصدار جديد

غيّر `version` في `app/pubspec.yaml` ثم أنشئ tag مثل:

```bash
git tag v0.2.0
git push origin v0.2.0
```

Workflow يبني `deep-search-android.apk` و `deep-search-windows-setup.exe` ويضيفهما إلى GitHub Release، والتطبيق يستطيع اكتشاف الإصدار الجديد من GitHub API.
