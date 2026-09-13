import sqlite3
import pymupdf
from google import genai
from google.genai import types
from app.secrets import load_secrets

# =========================
# Read existing book from DB
# =========================

db = sqlite3.connect(r"data\library.db")
db.row_factory = sqlite3.Row

book = db.execute("""
    SELECT *
    FROM books
    ORDER BY id DESC
    LIMIT 1
""").fetchone()

db.close()

if not book:
    raise RuntimeError("No book found in the database.")

PDF_PATH = book["file_path"]

print("PDF:", PDF_PATH)
print("Pages:", book["page_count"])

# =========================
# Read Gemini API key
# =========================

API_KEY = load_secrets().get("gemini_api_key")

if not API_KEY:
    raise RuntimeError("Gemini API key is not configured.")

MODEL = "gemini-3.1-flash-lite"

PROMPT = """
أنت نظام متخصص في النسخ الحرفي الدقيق للكتب العربية المصورة.

المطلوب استخراج النص من الصفحة المرفقة فقط.

التزم بما يلي:

- انسخ النص كما يظهر في الصفحة دون تلخيص أو شرح أو إعادة صياغة.
- لا تصحح الأخطاء الإملائية أو النحوية أو الطباعية الموجودة في الأصل.
- حافظ على الرسم الإملائي القديم كما هو.
- حافظ على الآيات والأحاديث والأسماء والأرقام والرموز والحواشي كما تظهر.
- حافظ على تقسيم الأسطر كما يظهر في الصفحة الأصلية قدر الإمكان.
- كل سطر في الصفحة يجب أن يقابله سطر في النص المستخرج قدر الإمكان.
- لا تدمج سطرين منفصلين في سطر واحد.
- لا تقسّم سطرًا واحدًا إلى عدة أسطر إلا إذا كان ذلك موجودًا في الأصل.
- لا تضف أسطرًا فارغة غير موجودة في الصفحة.
- تجاهل فقط رأس الصفحة المتكرر ورقم الصفحة المطبوع إن كان منفصلًا عن المتن.
- إذا كانت كلمة أو عبارة غير مقروءة فاكتب [غير واضح] بدل التخمين.
- لا تستخدم Markdown.
- لا تضف مقدمة أو خاتمة أو تعليقات.
- أعد النص المستخرج فقط.
"""

# =========================
# Render PAGE 1 to PNG
# =========================

with pymupdf.open(PDF_PATH) as pdf:
    page = pdf[0]

    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(2.5, 2.5),
        alpha=False
    )

    image = pixmap.tobytes("png")

print("Page 1 rendered successfully.")
print("Image size:", len(image), "bytes")
print("Sending page 1 to Gemini...")

# =========================
# Gemini
# =========================

client = genai.Client(api_key=API_KEY)

try:
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(
                data=image,
                mime_type="image/png"
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=PROMPT,
            thinking_config=types.ThinkingConfig(
                thinking_level="high"
            )
        )
    )

    print()
    print("========== GEMINI RESULT ==========")
    print()
    print(response.text)
    print()
    print("===================================")

except Exception as e:
    print()
    print("========== GEMINI ERROR ==========")
    print(type(e).__name__)
    print(str(e))
    print("==================================")
    raise