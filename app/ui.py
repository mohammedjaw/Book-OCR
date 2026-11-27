from fastapi.templating import Jinja2Templates
from .paths import ASSET_ROOT
from .database import connect

LABELS = {
'home':('الرئيسية','Home','خانه'), 'books':('الكتب','Books','کتاب‌ها'),
'upload':('رفع كتاب','Upload book','افزودن کتاب'), 'search':('البحث','Search','جستجو'),
'transfer':('الاستيراد والتصدير','Import/export','درون‌ریزی/برون‌ریزی'), 'settings':('الإعدادات','Settings','تنظیمات'),
'completed':('مكتمل','Completed','تکمیل‌شده'), 'pending':('انتظار','Pending','در انتظار'),
'processing':('جارٍ الاستخراج','Processing','در حال پردازش'), 'failed':('فشل','Failed','ناموفق'),
'running':('الاستخراج نشط','OCR running','استخراج فعال است'), 'paused':('متوقف مؤقتًا','Paused','مکث شده'),
'pausing':('جارٍ الإيقاف بعد إنهاء الطلبات الحالية','Pausing; finishing active requests','در حال مکث؛ تکمیل درخواست‌های فعال'),
'stopped':('متوقف','Stopped','متوقف'), 'keys_unavailable':('لا توجد مفاتيح مختارة متاحة. تحقق من الإعدادات أو انتظر يوم الحصة التالي.','No usable selected keys remain. Check settings or wait for the next quota day.','کلید انتخابی قابل استفاده نیست. تنظیمات را بررسی کنید یا تا روز سهمیه بعد صبر کنید.'),
'application_error':('توقف آمن بسبب خطأ في التطبيق. تحقق من التخزين والإعدادات.','Stopped safely after an application error. Check storage and settings.','به دلیل خطای برنامه متوقف شد. فضای ذخیره و تنظیمات را بررسی کنید.'),
'start':('بدء / متابعة الاستخراج','Start / Resume OCR','شروع / ادامه استخراج'),
'pause':('إيقاف مؤقت','Pause','مکث'), 'retry':('إعادة محاولة الصفحات الفاشلة المؤهلة','Retry eligible failed pages','تلاش مجدد صفحات ناموفق واجد شرایط'),
'full_text':('نص الكتاب الكامل','Full book text','متن کامل کتاب'), 'pages':('تصفح الصفحات','Browse pages','مرور صفحات'),
'delete':('حذف الكتاب','Delete book','حذف کتاب'), 'confirm_delete':('تأكيد حذف هذا الكتاب وملف PDF والنصوص نهائيًا','Confirm permanent deletion of this book, its PDF and OCR text','تأیید حذف دائمی این کتاب، PDF و متن استخراج‌شده'),
'cancel':('إلغاء','Cancel','لغو'), 'previous':('السابق','Previous','قبلی'), 'next':('التالي','Next','بعدی'),
'page':('الصفحة','Page','صفحه'), 'original_pdf':('PDF الأصلي','Original PDF','PDF اصلی'),
'connection_error':('تعذر تحديث الحالة. جارٍ إعادة المحاولة.','Status update failed. Retrying.','به‌روزرسانی وضعیت ناموفق بود. تلاش مجدد.'),
'local_counters':('عدادات Book-OCR المحلية فقط — ليست حصة Google الرسمية. إعادة الضبط بتوقيت لوس أنجلوس.','LOCAL Book-OCR counters only, not official Google quota. Reset: America/Los_Angeles.','فقط شمارنده‌های محلی Book-OCR؛ نه سهمیه رسمی Google. بازنشانی: America/Los_Angeles.'),
'single':('مفتاح واحد','Single Key','یک کلید'), 'pool':('مجموعة مفاتيح مختارة','Multi-Key Pool','مجموعه کلیدها'),
'key_mode':('وضع مفاتيح OCR','OCR key mode','حالت کلید OCR'),
'quota_exhausted':('نفدت الحصة اليومية','Daily quota exhausted','سهمیه روزانه تمام شده'),
'available':('متاح','Available','در دسترس'), 'invalid_key':('مفتاح غير صالح','Invalid key','کلید نامعتبر'),
'rate_limited':('حد مؤقت — انتظار','Temporarily rate limited','محدودیت موقت درخواست'),
'network_error':('خطأ اتصال','Network error','خطای شبکه'), 'service_error':('خطأ خدمة','Service error','خطای سرویس'),
'save':('حفظ الإعدادات','Save settings','ذخیره تنظیمات'),
}

LABELS.update({
'selection_help':('وضع المفتاح الواحد يستخدم المفتاح النشط فقط. تغيير اختيار المجموعة يفعّل وضع المجموعة؛ احفظ الإعدادات قبل الاستئناف.','Single mode uses only the active key. Changing a pool checkbox selects pool mode; save settings before resuming.','حالت تک‌کلید فقط از کلید فعال استفاده می‌کند. تغییر گروه حالت گروه را فعال می‌کند؛ پیش از ادامه ذخیره کنید.'),
'partial_text':('تصدير النص المتاح (يدعم التصدير الجزئي)','Export available text (supports partial export)','برون‌ریزی متن موجود (شامل ناقص)'),
'partial_text_help':('يمكن التصدير أثناء المعالجة. يتضمن النص المتاح وعدّادات الحالة وعلامات للصفحات غير المستخرجة. يمكن التصدير مجددًا لاحقًا.','Export during processing: includes available text, status counts and placeholders for unavailable pages. Export again later as more pages finish.','هنگام پردازش متن موجود با شمارنده و جای‌نگهدار صفحات صادر می‌شود؛ بعداً دوباره صادر کنید.'),
'api_keys':('مفاتيح Gemini API','Gemini API keys','کلیدهای Gemini API'),
'key_name':('اسم المفتاح','Key name','نام کلید'), 'add_key':('إضافة مفتاح API','Add API key','افزودن کلید API'),
'delete_key':('حذف المفتاح','Delete key','حذف کلید'),
'delete_key_question':('هل تريد حذف هذا المفتاح من Book-OCR؟','Remove this key from Book-OCR?','این کلید از Book-OCR حذف شود؟'),
'confirm_key_deletion':('تأكيد الحذف','Confirm deletion','تأیید حذف'),
'active_key':('مفتاح الاستخراج الحالي','Active OCR key','کلید فعال استخراج'),
'language':('لغة الواجهة','Interface language','زبان رابط'), 'theme':('مظهر الموقع','Theme','ظاهر'),
'font':('خط عرض النصوص المستخرجة','Reader font','قلم متن'), 'font_size':('حجم النص','Font size','اندازه متن'),
'line_height':('تباعد الأسطر','Line spacing','فاصله خطوط'), 'model':('النموذج','Model','مدل'),
'thinking':('مستوى التفكير','Thinking level','سطح تفکر'), 'concurrency':('عدد الصفحات المتوازية','Concurrent pages','صفحات هم‌زمان'),
'requests':('طلبات اليوم','Requests today','درخواست‌های امروز'), 'successes':('ناجحة','Successful','موفق'),
'failures':('فاشلة','Failed','ناموفق'), 'status':('الحالة','Status','وضعیت'),
'test_connection':('اختبار اتصال Gemini','Test Gemini connection','آزمایش اتصال Gemini'),
'saved':('تم حفظ الإعدادات','Settings saved','تنظیمات ذخیره شد'),
'key_limit_reached':('تم الوصول إلى الحد الأقصى وهو 10 مفاتيح API.','The maximum of 10 API keys has been reached.','حداکثر ۱۰ کلید API مجاز است.'),
'delete_busy':('جارٍ إيقاف OCR. انتظر إنهاء الطلبات الحالية ثم أكد الحذف مجددًا.','OCR is pausing. Wait for active requests to finish, then confirm deletion again.','استخراج در حال مکث است. پس از پایان درخواست‌ها حذف را دوباره تأیید کنید.'),
})
LABELS.update({'download_word':('تنزيل Word','Download Word','دانلود Word'),'copy_page':('نسخ الصفحة كاملة','Copy full page','کپی صفحه کامل'),'copy_selection':('نسخ التحديد','Copy selection','کپی انتخاب')})
LABELS.update({
'previous_page':('الصفحة السابقة','Previous page','صفحه قبلی'),
'next_page':('الصفحة التالية','Next page','صفحه بعدی'),
'go_to_page':('الانتقال إلى صفحة','Go to page','رفتن به صفحه'),
'page_number':('رقم الصفحة','Page number','شماره صفحه'),
'extracted_text':('النص المستخرج','Extracted text','متن استخراج‌شده'),
'original_page':('الصفحة الأصلية من PDF','Original PDF page','صفحه اصلی PDF'),
'copied':('تم النسخ','Copied','کپی شد'),
'volume':('الجزء','Volume','جلد'),
})
LABELS.update({'rerender_retry':('إعادة إنشاء الصفحة من PDF وإعادة الاستخراج','Re-render page from PDF and retry OCR','بازسازی صفحه از PDF و تلاش دوباره برای استخراج متن')})

LABELS.update({'collections': ('المجموعات', 'Collections', 'مجموعه\u200cها'), 'collection': ('المجموعة', 'Collection', 'مجموعه'), 'create_collection': ('إنشاء مجموعة', 'Create collection', 'ایجاد مجموعه'), 'collection_title': ('عنوان المجموعة', 'Collection title', 'عنوان مجموعه'), 'rename_collection': ('تغيير اسم المجموعة', 'Rename collection', 'تغییر نام مجموعه'), 'delete_collection': ('حذف المجموعة الفارغة', 'Delete empty collection', 'حذف مجموعه خالی'), 'collection_not_empty': ('أزل الكتب من المجموعة قبل حذفها. لن تُحذف الكتب.', 'Remove all books from the collection before deleting it. Books will not be deleted.', 'پیش از حذف مجموعه، همه کتاب\u200cها را از آن خارج کنید. کتاب\u200cها حذف نمی\u200cشوند.'), 'volumes': ('الأجزاء', 'Volumes', 'جلدها'), 'volume_number': ('رقم الجزء / الترتيب', 'Volume / order number', 'شماره جلد / ترتیب'), 'volume_help': ('الترتيب تصاعدي؛ الأرقام المتساوية حسب معرّف الكتاب، والأجزاء بلا رقم أخيرًا.', 'Ascending order; ties use book ID, and unnumbered volumes appear last.', 'ترتیب صعودی؛ شماره\u200cهای یکسان بر اساس شناسه کتاب و جلدهای بدون شماره در پایان.'), 'standalone': ('كتاب مستقل', 'Standalone book', 'کتاب مستقل'), 'standalone_books': ('الكتب المستقلة', 'Standalone books', 'کتاب\u200cهای مستقل'), 'assign_collection': ('حفظ المجموعة والترتيب', 'Save collection and order', 'ذخیره مجموعه و ترتیب'), 'add_volume': ('إضافة كتاب موجود', 'Add existing book', 'افزودن کتاب موجود'), 'remove_volume': ('إزالة من المجموعة', 'Remove from collection', 'خارج کردن از مجموعه'), 'save_order': ('حفظ الترتيب', 'Save order', 'ذخیره ترتیب'), 'empty_library': ('لا توجد كتب أو مجموعات.', 'No books or collections yet.', 'هنوز کتاب یا مجموعه\u200cای وجود ندارد.'), 'empty_collection': ('لا توجد أجزاء في هذه المجموعة.', 'This collection has no volumes.', 'این مجموعه جلدی ندارد.'), 'page_count': ('الصفحات', 'Pages', 'صفحات'), 'open_book': ('فتح الكتاب', 'Open book', 'باز کردن کتاب'), 'all_books': ('كل الكتب', 'All books', 'همه کتاب\u200cها'), 'current_volume': ('الجزء المحدد', 'Selected volume', 'جلد انتخاب\u200cشده'), 'search_placeholder': ('ابحث في النصوص', 'Search OCR text', 'جستجو در متن'), 'exact': ('مطابق', 'Exact', 'دقیق'), 'flexible': ('مرن', 'Flexible', 'انعطاف\u200cپذیر'), 'result_count': ('عدد النتائج', 'Results', 'نتایج'), 'of': ('من', 'of', 'از'), 'page_matches': ('عدد المطابقات في الصفحة', 'Matches on page', 'تطابق\u200cها در صفحه'), 'view_text': ('عرض النص', 'View text', 'نمایش متن'), 'open_original': ('فتح الصفحة الأصلية', 'Open original page', 'باز کردن صفحه اصلی'), 'no_results': ('لا توجد نتائج.', 'No results.', 'نتیجه\u200cای یافت نشد.'), 'ready': ('جاهز', 'Ready', 'آماده'), 'جاهز': ('جاهز', 'Ready', 'آماده')})

LABELS.update({
    'source_fingerprint': ('بصمة المصدر (Git)', 'Source fingerprint (Git tree)', 'اثر انگشت منبع (Git)'),
    'permission_denied': ('رُفض الوصول', 'Access denied', 'دسترسی رد شد'),
    'key_add_failed': ('أدخل مفتاحًا صالحًا وغير مكرر.', 'Enter a valid key that is not already saved.', 'کلیدی معتبر وارد کنید که قبلاً ذخیره نشده باشد.'),
    'about_book_ocr': ('حول Book-OCR', 'About Book-OCR', 'دربارهٔ Book-OCR'),
    'app_version': ('إصدار التطبيق', 'Application version', 'نسخهٔ برنامه'),
    'release': ('إصدار رسمي', 'Release', 'نسخهٔ انتشار'),
    'development': ('نسخة تطوير', 'Development', 'نسخهٔ توسعه'),
    'build_time': ('تاريخ ووقت البناء', 'Build date and time', 'تاریخ و زمان ساخت'),
    'source_run': ('تشغيل من المصدر', 'Running from source', 'اجرا از کد منبع'),
    'git_commit': ('معرّف الالتزام في Git', 'Git commit', 'شناسهٔ کامیت Git'),
    'unknown_commit': ('غير متوفر', 'Unavailable', 'در دسترس نیست'),
    'latest_published': ('أحدث إصدار منشور على GitHub', 'Latest published GitHub release', 'تازه‌ترین نسخهٔ منتشرشده در GitHub'),
    'stable': ('مستقر', 'Stable', 'پایدار'),
    'prerelease': ('إصدار تمهيدي', 'Prerelease', 'پیش‌انتشار'),
    'not_checked': ('لم يتم التحقق بعد', 'Not checked yet', 'هنوز بررسی نشده است'),
    'check_updates': ('التحقق من التحديثات', 'Check for Updates', 'بررسی به‌روزرسانی‌ها'),
    'official_repository': ('المستودع الرسمي على GitHub', 'Official GitHub repository', 'مخزن رسمی در GitHub'),
    'no_releases': ('لا توجد إصدارات منشورة.', 'No published releases.', 'هنوز نسخه‌ای منتشر نشده است.'),
    'no_stable': ('لا يوجد إصدار مستقر منشور.', 'No stable release has been published.', 'هنوز نسخهٔ پایداری منتشر نشده است.'),
    'update_available': ('يتوفر إصدار مستقر أحدث.', 'A newer stable release is available.', 'نسخهٔ پایدار جدیدتری در دسترس است.'),
    'version_current': ('رقم إصدار التطبيق يطابق أحدث إصدار مستقر.', 'This version number matches the latest stable release.', 'شمارهٔ این نسخه با آخرین نسخهٔ پایدار یکسان است.'),
    'version_ahead': ('رقم الإصدار المحلي أحدث من الإصدار المستقر.', 'This version is ahead of the latest stable release.', 'شمارهٔ نسخهٔ محلی از آخرین نسخهٔ پایدار جدیدتر است.'),
    'comparison_unavailable': ('تعذرت مقارنة رقمي الإصدار.', 'The version numbers could not be compared.', 'مقایسهٔ شمارهٔ نسخه‌ها امکان‌پذیر نبود.'),
    'update_check_failed': ('تعذر التحقق من إصدارات GitHub. حاول مجددًا لاحقًا.', 'Could not check GitHub Releases. Try again later.', 'بررسی نسخه‌های GitHub امکان‌پذیر نبود. بعداً دوباره تلاش کنید.'),
})

def preferences(request):
    with connect() as db: prefs = {r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
    lang = prefs.get('ui_language','ar')
    index = {'ar':0,'en':1,'fa':2}.get(lang,0)
    def tr(key): return LABELS.get(key,(key,key,key))[index]
    return {'prefs':prefs,'lang':lang,'tr':tr,'labels':{key:values[index] for key,values in LABELS.items()}}

templates = Jinja2Templates(directory=ASSET_ROOT / 'templates', context_processors=[preferences])
