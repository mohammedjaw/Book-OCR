from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates

from ..database import connect
from ..secrets import load_secrets, save_secrets


templates = Jinja2Templates(directory="templates")
router = APIRouter()


def get_settings_context():
    with connect() as db:
        settings = {
            row["key"]: row["value"]
            for row in db.execute("SELECT * FROM settings")
        }

    settings["gemini_api_key"] = ""
    settings["has_api_key"] = bool(
        load_secrets().get("gemini_api_key")
    )

    return settings


@router.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": get_settings_context(),
            "message": None,
            "test_result": None,
        },
    )


@router.post("/settings")
def save_settings(
    request: Request,
    api_key: str = Form(""),
    model: str = Form(""),
    thinking: str = Form("minimal"),
    concurrency: int = Form(3),
):
    api_key = api_key.strip(); concurrency=max(1,min(5,concurrency))

    secrets = load_secrets()
    old_key = secrets.get("gemini_api_key", "")

    # If user entered a new key, validate it.
    if api_key:
        if not api_key.isascii():
            return templates.TemplateResponse(
                request=request,
                name="settings.html",
                context={
                    "settings": get_settings_context(),
                    "message": "مفتاح API غير صالح: يجب أن يحتوي على أحرف ASCII فقط.",
                    "test_result": None,
                },
                status_code=400,
            )

        save_secrets({
            "gemini_api_key": api_key
        })

    # If input is empty, preserve the old key.
    elif old_key:
        save_secrets({
            "gemini_api_key": old_key
        })

    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)",
            ("gemini_model", model.strip() or "gemini-3.1-flash-lite"),
        )

        db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)",
            ("thinking_level", thinking.strip() or "minimal"),
        )
        db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ("max_concurrent_pages", str(concurrency)))

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": get_settings_context(),
            "message": "تم حفظ الإعدادات بنجاح.",
            "test_result": None,
        },
    )


@router.post("/settings/test")
def test_gemini(request: Request):
    from google import genai
    from google.genai import types

    key = load_secrets().get("gemini_api_key", "")

    with connect() as db:
        settings = {
            row["key"]: row["value"]
            for row in db.execute("SELECT * FROM settings")
        }

    model = (
        settings.get("gemini_model")
        or "gemini-3.1-flash-lite"
    )

    thinking = (
        settings.get("thinking_level")
        or "minimal"
    )

    if not key:
        result = "❌ لم يتم إعداد مفتاح Gemini."

    else:
        try:
            client = genai.Client(api_key=key)

            # We only need to verify that Google accepts the request.
            # Do not depend on response.text or exact output.
            client.models.generate_content(
                model=model,
                contents="Reply with OK.",
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_level=thinking
                    )
                ),
            )

            result = "✅ اتصال Gemini يعمل بنجاح."

        except Exception as exc:
            error_text = str(exc)

            # Never expose an API key if somehow included in an exception.
            if key:
                error_text = error_text.replace(key, "[API KEY HIDDEN]")

            result = (
                f"❌ فشل اتصال Gemini: "
                f"{type(exc).__name__}: {error_text}"
            )

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": get_settings_context(),
            "message": None,
            "test_result": result,
        },
    )
