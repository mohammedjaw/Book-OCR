from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi import UploadFile, File
from fastapi.templating import Jinja2Templates

from ..database import connect
from ..secrets import load_secrets
from ..ocr_service import classify_gemini_error
from ..gemini_key_manager import list_keys, get_active_key, set_active_key, delete_key, MAX_GEMINI_API_KEYS
from ..key_backup import export_backup, restore_backup
from ..build_info import running_build
from ..releases import REPOSITORY, check_releases


from ..ui import templates
router = APIRouter()

@router.post('/settings/keys/backup/export')
def export_key_backup(password: str = Form(...), confirmation: str = Form(...)):
    if password != confirmation: raise HTTPException(400, 'Passwords do not match.')
    try: blob = export_backup(password)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    return Response(blob, media_type='application/octet-stream', headers={'Content-Disposition':'attachment; filename="book-ocr-keys.bookocr-keys"'})

@router.post('/settings/keys/backup/import')
async def import_key_backup(file: UploadFile = File(...), password: str = Form(...), mode: str = Form(...), replace_confirmation: str = Form('')):
    try: restore_backup(await file.read(), password, mode, confirmed=replace_confirmation == 'REPLACE')
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    return RedirectResponse('/settings?saved=1', 303)

@router.post('/settings/keys/add')
def add_gemini_key(name: str = Form(''), new_api_key: str = Form('')):
    from ..gemini_key_manager import add_key
    secret = new_api_key.strip()
    data = load_secrets()
    if len(data.get('gemini_api_keys', [])) >= MAX_GEMINI_API_KEYS:
        return RedirectResponse('/settings?key_error=limit', 303)
    if not add_key(name, secret):
        return RedirectResponse('/settings?key_error=invalid', 303)
    return RedirectResponse('/settings', 303)


@router.post('/settings/keys/{key_id}/delete')
def delete_gemini_key(key_id: str, confirmation: str = Form('')):
    if confirmation != 'delete':
        raise HTTPException(400, 'Deletion requires confirmation.')
    if not delete_key(key_id):
        raise HTTPException(404, 'Key not found.')
    return RedirectResponse('/settings?saved=1', 303)


def get_settings_context():
    with connect() as db:
        settings = {
            row["key"]: row["value"]
            for row in db.execute("SELECT * FROM settings")
        }

    settings["gemini_api_key"] = ""
    settings.setdefault("ui_language", "ar")
    settings.setdefault("theme", "تلقائي")
    settings["has_api_key"] = bool(
        get_active_key()
    )
    settings['gemini_keys'] = list_keys()
    settings['can_delete_keys'] = True

    import json
    settings['pool_ids'] = json.loads(settings.get('ocr_pool_ids', '[]'))
    return settings


def render_settings(request, test_result=None):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": get_settings_context(),
            "message": None,
            "key_error": request.query_params.get('key_error'),
            "test_result": test_result,
            "build": running_build(),
            "repository": REPOSITORY,
            "release_check": getattr(request.app.state, "release_check", None),
        },
    )


@router.get("/settings")
def settings_page(request: Request):
    return render_settings(request)


@router.post("/settings/check-updates")
def check_updates(request: Request):
    request.app.state.release_check = check_releases(running_build()["version"])
    return RedirectResponse("/settings#about", 303)


@router.post("/settings")
async def save_settings(request: Request):
    import json
    form = await request.form()
    mapping = {'model':'gemini_model','thinking':'thinking_level','concurrency':'max_concurrent_pages',
               'font_family':'font_family','font_size':'font_size','line_height':'line_height',
               'theme':'theme','ui_language':'ui_language','ocr_key_mode':'ocr_key_mode'}
    values = {}
    for field, column in mapping.items():
        if field not in form: continue
        value = str(form[field]).strip()
        try:
            if field == 'concurrency': value = str(max(1,min(5,int(value))))
            if field == 'font_size': value = str(max(14,min(36,int(value))))
            if field == 'line_height': value = str(max(1.4,min(2.4,float(value))))
        except ValueError:
            continue
        if field == 'theme' and value not in ('فاتح','داكن','تلقائي'): continue
        if field == 'ui_language' and value not in ('ar','en','fa'): continue
        if field == 'ocr_key_mode' and value not in ('single','pool'): continue
        if field == 'thinking' and value not in ('minimal','low','medium','high'): continue
        if field == 'font_family':
            import re
            value = re.sub(r'[^\w ,.-]', '', value)[:100] or 'Noto Naskh Arabic'
        if field == 'model': value = value or 'gemini-3.1-flash-lite'
        values[column] = value
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if 'pool_present' in form:
            known = {k['id'] for k in list_keys()}
            values['ocr_pool_ids'] = json.dumps([key for key in form.getlist('pool_ids') if key in known])
            previous = db.execute("SELECT value FROM settings WHERE key='ocr_pool_ids'").fetchone()
            if set(json.loads(previous[0]) if previous else []) != set(json.loads(values['ocr_pool_ids'])):
                # Match the checkbox UI even without JavaScript: changed membership selects pool mode.
                values['ocr_key_mode'] = 'pool'
        db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', values.items())
    if form.get('active_key_id'): set_active_key(str(form['active_key_id']))
    # Redirect ensures the base template reads the newly committed preferences.
    return RedirectResponse('/settings?saved=1', 303)


@router.post("/settings/test")
def test_gemini(request: Request):
    from google import genai
    from google.genai import types

    active_key = get_active_key()
    key = active_key["api_key"] if active_key else ""

    with connect() as db:
        settings = {
            row["key"]: row["value"]
            for row in db.execute("SELECT * FROM settings")
        }

    lang = settings.get('ui_language', 'ar')

    if not key:
        result = {'en':'❌ Gemini connection failed: Gemini API key is not configured.','fa':'❌ اتصال Gemini ناموفق بود: کلید API تنظیم نشده است.','ar':'❌ فشل اتصال Gemini: لم يتم إعداد مفتاح Gemini.'}.get(lang)

    else:
        try:
            with genai.Client(api_key=key, http_options={'timeout': 30000}) as client:
                next(client.models.list(config={'page_size': 1}), None)
            result = {'en':'✅ Gemini key is valid and the connection works.','fa':'✅ کلید Gemini معتبر است و اتصال برقرار است.','ar':'✅ مفتاح Gemini صالح والاتصال يعمل.'}.get(lang)

        except Exception as exc:
            kind = classify_gemini_error(exc)
            labels = {
                'quota_exhausted': {'ar':'⚠️ حصة Gemini مستنفدة.', 'en':'⚠️ Gemini quota is exhausted.', 'fa':'⚠️ سهمیه Gemini تمام شده است.'},
                'rate_limited': {'ar':'⚠️ تم الوصول إلى حد الطلبات مؤقتًا. حاول لاحقًا.', 'en':'⚠️ Temporarily rate limited. Try again later.', 'fa':'⚠️ موقتاً به حد درخواست‌ها رسیدید. بعداً دوباره تلاش کنید.'},
                'permission_denied': {'ar':'رفض Gemini الوصول. تحقق من أذونات المشروع.', 'en':'Gemini denied access. Check project permissions.', 'fa':'دسترسی رد شد. مجوزهای پروژه را بررسی کنید.'},
                'invalid_key': {'ar':'❌ مفتاح Gemini غير صالح.', 'en':'❌ Gemini API key is invalid.', 'fa':'❌ کلید Gemini نامعتبر است.'},
                'network_error': {'ar':'❌ تعذر الوصول إلى Gemini بسبب مشكلة اتصال.', 'en':'❌ Could not reach Gemini because of a connection problem.', 'fa':'❌ دسترسی به Gemini به دلیل مشکل اتصال ممکن نیست.'},
            }
            friendly = labels.get(kind, {'ar':'❌ حدث خطأ في خدمة Gemini.', 'en':'❌ Gemini service error.', 'fa':'❌ خطای سرویس Gemini.'})[lang]
            result = friendly


    return render_settings(request, test_result=result)
