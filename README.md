# البحث العميق — HAI_SERCH

تطبيق بحث طويل المدى يعمل من السحابة ويزامن نفس المهام والنتائج بين Android وWindows.

## الهدف

- إدخال نص، صورة، أو فيديو.
- استمرار البحث حتى بعد إغلاق الأجهزة.
- جمع نتائج موثقة وترتيبها حسب المطابقة.
- مزامنة فورية بين Android وWindows.
- VPN / Egress داخل السيرفر فقط.
- تشغيل شخصي بتكلفة أساسية 0 قدر الإمكان.

## البنية المختارة

- **Client:** Flutter (Android + Windows من قاعدة كود واحدة)
- **API:** FastAPI / Python
- **Database + queue:** PostgreSQL فقط، لتجنب Redis وخدمة إضافية
- **Search:** SearXNG + HTTP crawler خفيف، وPlaywright عند الحاجة فقط
- **Media:** FFmpeg + OCR + Whisper.cpp عند الحاجة
- **Files:** Cloudflare R2 مع حذف تلقائي للملفات المؤقتة
- **Notifications:** Firebase Cloud Messaging
- **Server:** Oracle Cloud Always Free Ampere A1
- **VPN:** WireGuard داخل السيرفر
- **Updates:** GitHub Releases

## فلسفة استهلاك المجاني

1. لا يتم تشغيل المتصفح الكامل إلا للمواقع التي تحتاج JavaScript.
2. لا يتم تحليل الفيديو إطارًا بإطار؛ تستخرج لقطات رئيسية فقط.
3. نتائج البحث والصفحات لها cache لمنع إعادة العمل.
4. المهام تستخدم PostgreSQL queue بدل تشغيل Redis منفصل.
5. الملفات المؤقتة لها TTL ويتم حذفها آليًا.
6. نماذج الذكاء محلية وخفيفة/quantized ولا تعتمد على API مدفوع.
7. لكل مهمة ميزانية موارد قابلة للضبط، مع إمكانية البحث الطويل دون هدر CPU.

راجع `docs/ARCHITECTURE.md` و `docs/FREE_TIER_BUDGET.md` للتفاصيل.
