import os
import re
import io
import time
import requests
import streamlit as st
from PIL import Image

# ===== Replicate SDK =====
try:
    import replicate
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False

st.set_page_config(page_title="Virtual Try-On (beta)", page_icon="🪄", layout="centered")
st.title("🪄 Virtual Try-On (beta)")
st.caption("Загрузите фото себя и фото вещи (или вставьте прямые URL). Картинки конвертируются локально и не сохраняются на сервере приложения.")

# ===== UI =====
col1, col2 = st.columns(2)
with col1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body)",
        type=["jpg", "jpeg", "png", "webp"],
        help="Фронтально, по грудь. Желательно ≥512px по короткой стороне."
    )
with col2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo)",
        type=["jpg", "jpeg", "png", "webp"],
        help="Карточка товара на ровном фоне."
    )

person_url_input = st.text_input("...or paste YOUR photo URL (optional)")
cloth_url = st.text_input("...or paste clothing image URL (optional)")

model_choice = st.selectbox(
    "Model endpoint",
    ["idm-vton (Replicate)", "ecommerce-virtual-try-on (Replicate)"],
    index=0
)

# ===== Helpers =====
def _validate_image_url(url: str) -> bool:
    import io
    from PIL import Image
    try:
        if not url or not url.lower().startswith(("http://", "https://")):
            return False
        # 1) HEAD: быстро и дёшево
        resp = requests.head(url, allow_redirects=True, timeout=10)
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and ctype.startswith("image/"):
            return True
        # 2) fallback: маленький GET и попытка открыть как изображение
        r = requests.get(url, stream=True, timeout=15)
        r.raise_for_status()
        chunk = r.raw.read(200_000, decode_content=True)  # ~200KB
        Image.open(io.BytesIO(chunk))
        return True
    except Exception:
        return False


def _image_to_jpeg_bytes(img: Image.Image, target_min_side: int = 512, target_max_side: int = 1024) -> bytes:
    """Конверт в валидный JPEG. Если слишком маленькое изображение — мягко апскейлим до ~512 по короткой стороне;
    если слишком большое — уменьшим до ~1024 по длинной стороне."""
    img = img.convert("RGB")
    w, h = img.size
    long_side, short_side = max(w, h), min(w, h)
    if short_side < target_min_side:
        scale = target_min_side / short_side
    elif long_side > target_max_side:
        scale = target_max_side / long_side
    else:
        scale = 1.0
    if scale != 1.0 and w > 0 and h > 0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf.getvalue()

# ---- Хостинг: 0x0.st → catbox → tmpfiles (с ретраями и валидацией) ----
def _host_via_0x0(jpeg_bytes: bytes, filename: str = "image.jpg") -> str | None:
    try:
        files = {"file": (filename, io.BytesIO(jpeg_bytes), "image/jpeg")}
        r = requests.post("https://0x0.st", files=files, timeout=60)
        r.raise_for_status()
        url = r.text.strip()
        return url if url.startswith("http") else None
    except Exception:
        return None

def _host_via_catbox(jpeg_bytes: bytes, filename: str = "image.jpg") -> str | None:
    try:
        files = {"fileToUpload": (filename, io.BytesIO(jpeg_bytes), "image/jpeg")}
        data = {"reqtype": "fileupload"}
        r = requests.post("https://catbox.moe/user/api.php", data=data, files=files, timeout=60)
        r.raise_for_status()
        url = r.text.strip()
        return url if url.startswith("http") else None
    except Exception:
        return None

def _host_via_tmpfiles(jpeg_bytes: bytes, filename: str = "image.jpg") -> str | None:
    try:
        up = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (filename, io.BytesIO(jpeg_bytes), "image/jpeg")},
            timeout=60,
        )
        up.raise_for_status()
        page_url = up.json().get("data", {}).get("url")
        if not page_url:
            return None
        # https://tmpfiles.org/<id> -> /dl/<id>
        m = re.fullmatch(r"https?://tmpfiles\.org/([A-Za-z0-9]+)", page_url.rstrip("/"))
        return f"https://tmpfiles.org/dl/{m.group(1)}" if m else page_url
    except Exception:
        return None

def _host_jpeg_bytes_with_retry(jpeg_bytes: bytes, filename: str = "image.jpg") -> str | None:
    for hoster in (_host_via_0x0, _host_via_catbox, _host_via_tmpfiles):
        delay = 0.8
        for _ in range(3):
            url = hoster(jpeg_bytes, filename)
            if url and _validate_image_url(url):
                return url
            time.sleep(delay)
            delay *= 1.7
    return None

def _host_uploaded_file(uploaded_file, fallback_name: str) -> str | None:
    """Открываем любой формат (jpg/png/webp), конвертим в JPEG, хостим и возвращаем прямой URL."""
    try:
        img = Image.open(uploaded_file)
    except Exception as e:
        st.error(f"Cannot open image `{getattr(uploaded_file,'name',fallback_name)}`: {e}")
        return None
    jpeg = _image_to_jpeg_bytes(img)
    return _host_jpeg_bytes_with_retry(jpeg, fallback_name)

def _download_and_rehost(url: str, fallback_name: str) -> str | None:
    """Скачиваем любую ссылку. Если это картинка — конвертим в JPEG и пере-хостим на 0x0/catbox/tmpfiles."""
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        jpeg = _image_to_jpeg_bytes(img)
        return _host_jpeg_bytes_with_retry(jpeg, fallback_name)
    except Exception as e:
        st.warning(f"Could not fetch & rehost image: {e}")
        return None

# ===== Build image URLs =====
person_url = None
cloth_img_url = None

# YOUR photo: если дали прямой URL — используем его; иначе — upload→host
if person_url_input and _validate_image_url(person_url_input.strip()):
    person_url = person_url_input.strip()
elif person_file is not None:
    person_url = _host_uploaded_file(person_file, "person.jpg")

# Clothing: если прямой URL — используем; иначе — upload→host
if cloth_url and _validate_image_url(cloth_url.strip()):
    cloth_img_url = cloth_url.strip()
elif cloth_file is not None:
    cloth_img_url = _host_uploaded_file(cloth_file, "cloth.jpg")

with st.expander("Input debug"):
    st.write({"person_url": person_url, "cloth_url": cloth_img_url})

# Жёсткая проверка — не ходим в Replicate без валидных ссылок
invalid = []
if not person_url or not _validate_image_url(person_url):
    invalid.append("Your photo URL is invalid or not an image.")
if not cloth_img_url or not _validate_image_url(cloth_img_url):
    invalid.append("Clothing image URL is invalid or not an image.")
if invalid:
    st.error(" | ".join(invalid))
    st.stop()

run = st.button("Try on")

# ===== Tokens / guards =====
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

# ===== Replicate endpoints (пинованные версии) =====
IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

def run_idm_vton(person, cloth):
    # human_img/garm_img (новее) → fallback на human_image/cloth_image
    try:
        return replicate.run(IDM_VTON, input={"human_img": person, "garm_img": cloth})
    except Exception:
        return replicate.run(IDM_VTON, input={"human_image": person, "cloth_image": cloth})

def run_ecom_vton(person, cloth):
    # face_image/commerce_image (новее) → fallback на image_person/image_clothing
    try:
        return replicate.run(ECOM_VTON, input={"face_image": person, "commerce_image": cloth})
    except Exception:
        return replicate.run(ECOM_VTON, input={"image_person": person, "image_clothing": cloth})

# ===== Run =====
if run:
    try:
        with st.spinner("Generating try-on…"):
            if model_choice.startswith("idm-vton"):
                output = run_idm_vton(person_url, cloth_img_url)
            else:
                output = run_ecom_vton(person_url, cloth_img_url)

        # Replicate обычно возвращает список URL или один URL-строку
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
        st.info("Tips: use a clear front-facing photo (≥512px) and a product image with the garment fully visible.")
