# معمارية البحث العميق

## المسار

```text
Android / Windows (Flutter)
        |
        v
    FastAPI
        |
        +---- PostgreSQL (الحسابات/المهام/النتائج + Queue)
        |
        +---- /data (الملفات المؤقتة)
        |
        v
 Research Worker
        |
        +---- SearXNG
        +---- HTTP fetch + Trafilatura
        +---- FFmpeg / OCR عند الوسائط
        |
        v
 WireGuard / Egress على نفس السيرفر
        |
        v
      Internet
```

## لماذا PostgreSQL Queue؟

لتوفير خدمة وذاكرة إضافية. `SELECT ... FOR UPDATE SKIP LOCKED` يسمح لأكثر من Worker بأخذ المهام بأمان من نفس PostgreSQL. للاستخدام الشخصي لا نحتاج Redis في البداية.

## البحث الطويل

كل مهمة تنفذ على جولات. إذا لم تصل إلى العدد المطلوب، تعاد إلى الطابور مع backoff بدل إبقاء CPU مشغولًا دون فائدة. الجولة اللاحقة توسع الاستعلامات وصفحات البحث تدريجيًا. هذا يسمح للمهمة بالبقاء ساعات أو أيام مع استهلاك منخفض أثناء الانتظار.

## الصور والفيديو

الطبقة الحالية تقبل رفع الصور والفيديو وتخزنها مؤقتًا. FFmpeg وTesseract موجودان في صورة الـWorker كأساس للتحليل المحلي. المرحلة التالية تضيف استخراج keyframes والصوت ووصف بصري محلي quantized. لا نعتمد على Vision API مدفوع.

## VPN

الـVPN داخل السيرفر وليس الجهاز. WireGuard يطبق على مستوى Linux أو Network Namespace. التطبيق لا يحصل على مفاتيح VPN. `EGRESS_PROXY_URL` مخصص لوضع متقدم يكون فيه VPN في namespace/gateway منفصل ويصل إليه الـWorker عبر proxy.

## Android + Windows

نفس Flutter client، ونفس API والحساب. لا يوجد بحث محلي على الجهاز؛ إغلاق الجهاز لا يوقف المهمة.
