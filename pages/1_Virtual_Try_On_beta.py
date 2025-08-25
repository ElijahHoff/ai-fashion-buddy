import os
import re
import io
import requests
import streamlit as st
from PIL import Image

# Optional: Replicate SDK
try:
    import replicate
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False

st.set_page_config(page_title="Virtual Try-On (beta)", page_icon="🪄", layout="centered")
st.title("🪄 Virtual Try-On (beta)")
st.caption("Загрузите фото себя и фото вещи (или URL). Картинки конвертируются и не сохраняются на сервере приложения.")

# ========== UI ==========
col1, col2 = st.columns(2)
with col1:
    person_file = st.file_uploader("Your photo (front-facing, upper body)", type=["jpg", "jpeg", "png", "webp"])
with col2:
    cloth_file = st.file_uploader("Clothing image (product photo)", type=["jpg", "jpeg", "png", "webp"])

cloth_url = st.text_input("...or paste clothing image URL (optional)")

model_choice = st.selectbox(
    "Model endpoint",
    ["idm-vton (Replicate)", "ecommerce-virtual-try-on (Replicate)"],
    index=0
)

# ========== Helpers ==========
def _is_direct_image_url(url: str) -> bool:
    try:
        if not url.lower().startswith(("http://", "https://")):
            return False
        head = requests.head(url, allow_redirects=True, timeout=15)
        ctype = head.headers.get("Content-Type", "")
        return head.status_code == 200 and ctype.startswith("image/")
    except Exception:
        return False

def _ensure_tmpfiles_dl(url: str) -> str:
    if not url:
        return url
    # Только если это страница tmpfiles вида https://tmpfiles.org/<id> -> делаем /dl/<id>
    m = re.fullmatch(r"https?://tmpfiles\.org/([A-Za-z0-9]+)", url.rstrip("/"))
    if m:
        return f"https://tmpfiles.org/dl/{m.group(1)}"
    return url

def _image_to_jpeg_bytes(img: Image.Image, target_max_side: int = 512) -> bytes:
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) == 0:
        scale = 1.0
    else:
        scale = min(1.0, target_max_side / max(w, h))  # не увеличиваем сверх исходника
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()

def _tmp_host_bytes(jpeg_bytes: bytes, filename: str = "image.jpg") -> str | None:
    try:
        files = {"file": (filename, io.BytesIO(jpeg_bytes), "image/jpeg")}
        up = requests.post("https://tmpfiles.org/api/v1/upload", files=files, timeout=60)
        up.raise_for_status()
        page_url = up.json().get("data", {}).get("url")
        return _ensure_tmpfiles_dl(page_url)
    except Exception as e:
        st.warning(f"Temporary hosting failed: {e}")
        return None

def _host_uploaded_file(uploaded_file, fallback_name: str) -> str | None:
    """Открываем любой формат (jpg/png/webp), приводим к валидному JPEG, хостим и возвращаем прямой URL."""
    try:
        img = Image.open(uploaded_file)
    except Exception as e:
        st.error(f"Cannot open image `{getattr(uploaded_file,'name',fallback_name)}`: {e}")
        return None
    jpeg = _image_to_jpeg_bytes(img)
    return _tmp_host_bytes(jpeg, fallback_name)

def _download_and_rehost(url: str, fallback_name: str) -> str | None:
    """Скачиваем любую ссылку, если это картинка — конвертируем в JPEG и пере-хостим."""
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        jpeg = _image_to_jpeg_bytes(img)
        return _tmp_host_bytes(jpeg, fallback_name)
    except Exception as e:
        st.warning(f"Could not fetch & rehost image: {e}")
        return None

# ========== Build image URLs (agnostic to file names) ==========
person_url = None
cloth_img_url = None

if person_file is not None:
    person_url = _host_uploaded_file(person_file, "person.jpg")

if cloth_file is not None:
    cloth_img_url = _host_uploaded_file(cloth_file, "cloth.jpg")

if not cloth_img_url and cloth_url:
    raw = cloth_url.strip()
    if _is_direct_image_url(raw):
        cloth_img_url = raw
    else:
        cloth_img_url = _download_and_rehost(raw, "cloth.jpg")

with st.expander("Input debug"):
    st.write({"person_url": person_url, "cloth_url": cloth_img_url})

run = st.button("Try on")

# ========== Tokens / guards ==========
rep_token = os.getenv("REPLICATE_API_TOKEN")
if not rep_token:
    try:
        rep_token = st.secrets["REPLICATE_API_TOKEN"]
    except Exception:
        rep_token = None

if not rep_token:
    st.info("Add REPLICATE_API_TOKEN to Streamlit **Secrets** to enable try-on.")
    st.stop()
if not REPLICATE_AVAILABLE:
    st.error("`replicate` package not found. Ensure `replicate` is in requirements.txt.")
    st.stop()

os.environ["REPLICATE_API_TOKEN"] = rep_token

# ========== Replicate call with robust field names ==========
# Закрепляем версии (можешь заменить на актуальные хэши с страницы модели)
IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

def run_idm_vton(person, cloth):
    # Некоторые билды ждут human_img/garm_img, другие — human_image/cloth_image
    # Порядок проб: новый контракт -> старый контракт
    try:
        return replicate.run(IDM_VTON, input={"human_img": person, "garm_img": cloth})
    except Exception:
        return replicate.run(IDM_VTON, input={"human_image": person, "cloth_image": cloth})

def run_ecom_vton(person, cloth):
    # Некоторые билды ждут face_image/commerce_image, другие — image_person/image_clothing
    try:
        return replicate.run(ECOM_VTON, input={"face_image": person, "commerce_image": cloth})
    except Exception:
        return replicate.run(ECOM_VTON, input={"image_person": person, "image_clothing": cloth})

# ========== Run ==========
if run:
    if not (person_url and cloth_img_url):
        st.error("Please provide both your photo and a clothing image (or URL).")
        st.stop()

    try:
        with st.spinner("Generating try-on…"):
            if model_choice.startswith("idm-vton"):
                output = run_idm_vton(person_url, cloth_img_url)
            else:
                output = run_ecom_vton(person_url, cloth_img_url)

        # Replicate обычно возвращает список URL или строку URL
        if isinstance(output, list) and output:
            result_url = output[0]
        elif isinstance(output, str):
            result_url = output
        else:
            result_url = None

        if result_url:
            st.subheader("Result")
            st.image(result_url, use_container_width=True)
            with st.expander("Debug info"):
                st.write({
                    "person_url": person_url,
                    "cloth_url": cloth_img_url,
                    "model": model_choice,
                    "raw_output": output if not isinstance(output, (str, bytes)) else "(string)"
                })
            st.success("Done! Try other photos for comparison.")
        else:
            st.error("No image in response. Try another model or different images.")

    except Exception as e:
        st.error(f"Try-on failed: {e}")
        st.info("Tips: use a clear front-facing photo and a product image with the garment fully visible.")
