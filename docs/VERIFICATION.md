# مراجعة المصادر الرسمية — 2026-10-13

تم جلب الصفحات التالية أثناء العمل. بعض مسارات Buffer القديمة وصفحة تسعير OpenAI التسويقية أعادت 403؛ استخدمنا وثائق المطورين ومركز المساعدة الرسميين القابلين للوصول. لم نعتمد API القديم `/1/updates/create.json`.

| المصدر الرسمي | النتيجة المستخدمة |
|---|---|
| [Buffer API FAQ](https://support.buffer.com/articles/what-is-buffers-api-GtIYIQilz5) | API مجاني ضمن جميع الخطط، Free: مفتاح واحد و3,000 طلب/30 يومًا؛ TikTok ضمن القنوات المدعومة |
| [Buffer developer documentation](https://developers.buffer.com/llms-full.txt) | endpoint `https://api.buffer.com`، Bearer، GraphQL، `CreatePostInput`، `automatic`، `customScheduled`، `shareNow`، pagination، `post.status`، وعدم وجود رفع مباشر للصور |
| [TikTok with Buffer](https://support.buffer.com/articles/using-tiktok-with-buffer-oGEroY9Of2) | صور حتى 10 للمنشور، حد صورة 20MB و1080×1920، حد 5 هاشتاغات و2200 حرف؛ القناة تدعم النشر والإشعار بحسب المحتوى |
| [Buffer AI disclosure](https://support.buffer.com/articles/flagging-posts-as-ai-generated-in-buffer-V7jAnzYJ5n) | العلامة الأصلية TikTok للفيديو فقط؛ إرسال علم AI على صورة يعيد validation error |
| [Buffer Free plan queue](https://support.buffer.com/articles/what-happens-when-you-downgrade-to-the-free-plan-s6ayRdRtQ6) | حد 10 منشورات مجدولة للقناة |
| [TikTok photo API](https://developers.tiktok.com/doc/content-posting-api-reference-photo-post) | TikTok نفسه يدعم PHOTO وDIRECT_POST؛ لديه `is_aigc` للصور، لكن هذا لا يعني أن Buffer يمرره. العنوان 90 UTF-16 والوصف 4000 في API المباشر؛ اتبعنا حد Buffer الأقل للوصف |
| [TikTok integrity and authenticity](https://www.tiktok.com/community-guidelines/en/integrity-authenticity) | يلزم إفصاح للمشاهد/الأشخاص الواقعيين المعدلين، ويمكن أن يكون وصفًا واضحًا أو ملصقًا أو علامة مائية. العبارات ظهرت في بيانات محتوى الصفحة الرسمية المفكوكة من URL encoding |
| [TikTok Direct Post developer guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) | معاينة ووعي وتحكم المستخدم وموافقته قبل الرفع؛ الأدوات الخاصة لرفع محتوى حساب فريق ليست الاستخدام المقبول للتدقيق. لذلك لم ننشئ بديلًا خاصًا عبر TikTok API المباشر |
| [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation) | Images API، JPEG، جودة low/medium؛ جدول المقارنة يعطي GPT Image 2 low portrait بسعر مخرجات $0.005، medium $0.041. الأبعاد المخصصة لـGPT Image 2 مضاعفات 16، لذلك 1080×1920 ليست حجمًا أصليًا صالحًا؛ ملف النشر يُحجَّم محليًا |
| [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) | أسعار النص `gpt-6-luna` Standard قصير السياق $0.10/$0.50 لكل مليون رمز إدخال/إخراج؛ التسعير الكامل يشمل رموز مدخلات الصورة ومخرجاتها |
| [OpenAI moderation](https://developers.openai.com/api/docs/guides/moderation) | `omni-moderation-latest` يدعم النص والصور، endpoint moderation مجاني |
| [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) | تشغيل المشغّلات القياسية مجاني للمستودعات العامة؛ المستودعات الخاصة حصص وفوترة مختلفة |
| [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) | احتمال التأخير/إسقاط التشغيلات، التنفيذ من الفرع الافتراضي، وتعطيل بعد 60 يومًا دون نشاط بالمستودعات العامة |
| [football-data.org pricing](https://www.football-data.org/pricing) | خطة Free بقيمة €0 و12 بطولة و10 طلبات/دقيقة؛ النتائج والجداول موصوفة بأنها متأخرة. لا تحتاج الخطة الأعلى Free w/ Livescores بقيمة €12/شهر |
| [football-data.org coverage](https://www.football-data.org/coverage) | دوري الأبطال والدوريات الأوروبية الخمس وكأس العالم وأوروبا ضمن التغطية المجانية |
| [football-data.org v4 matches](https://docs.football-data.org/general/v4/match.html) | مصادقة X-Auth-Token، توقيت UTC، TIMED يعني تحديد اليوم والساعة؛ SCHEDULED موعد تقريبي لا يكفي لطباعة ساعة مؤكدة |
| [football-data.org v4 changes](https://docs.football-data.org/general/v4/index.html) | dateTo في v4 حد نهائي مستبعد؛ تُجلب الأيام UTC المحيطة ثم يطبّق حد يوم ألمانيا محليًا |

كذلك تم التحقق من SHAs المثبتة لـ`actions/checkout v4.2.2` و`actions/setup-python v5.6.0` و`actions/github-script v7.0.1` عبر API الرسمي لمستودعات GitHub التابعة لـactions.

**ما لا تثبته هذه المراجعة:** لا تثبت صلاحيات حسابك أو أن كل حساب/منطقة يدعم نشر الصور تلقائيًا. يُفحص نوع القناة واتصالها في التشغيل، ويُرفض تحول المنشور إلى notification أو draft. اختبار على حسابك مرتبط هو الإثبات النهائي؛ لا توجد حسابات أو مفاتيح في البيئة الحالية.
