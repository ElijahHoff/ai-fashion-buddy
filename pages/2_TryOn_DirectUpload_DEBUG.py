import os
import io
import tempfile
import streamlit as st
from PIL import Image

# ===== Replicate SDK =====
try:
    import replicate
    from replicate import files as replicate_files  # для files.upload
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False
    replicate_files = None  # type: ignore

st.set_page_config(page_title="Try-On (Direct Upload DEBUG)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — Direct Upload DEBUG")
st.caption("Build: DU-DEBUG v5 — заливаем изображения в Replicate Files → передаём URL. Ключи ровно как у модели.")

# ========== UI ==========
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body) — REQUIRED",
        type=["jpg", "jpeg", "png", "webp"],
        help="Фронтально, по грудь. Лучше ≥512px по короткой стороне."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo) — REQUIRED",
        type=["jpg", "jpeg", "png", "webp"],
        help="Карточка товара на ровном фоне."
    )

model_choice = st.selectbox(
    "Model",
    ["idm-vton (recommended)", "ecommerce-virtual-try-on"],
    index=0
)

run = st.button("Try on")

# ========== Helpers ==========
def _to_jpeg_bytes(uploaded_file, min_side: int = 512, max_side: int = 1024) -> bytes:
    """Любой формат → RGB JPEG. Подтягиваем мелкое до min_side, большое уменьшаем до max_side."""
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError("Empty image")
    long_side, short_side = max(w, h), min(w, h)
    if short_side < min_side:
        scale = min_side / short_side
    elif long_side > max_side:
        scale = max_side / long_side
    else:
        scale = 1.0
    if scale != 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def _upload_to_replicate_files(jpeg_bytes: bytes, name: str = "image.jpg") -> str:
    """Пишем во временный файл → replicate.files.upload(path) → получаем https URL."""
    if not REPLICATE_AVAILABLE or not replicate_files:
        raise RuntimeError("Replicate SDK/files unavailable")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
        tf.write(jpeg_bytes)
        tf.flush()
        path = tf.name
    url = replicate_files.upload(path)  # -> 'https://replicate.delivery/...' (прямая ссылка)
    return url

def _extract_first_image_url(output):
    """Достаём первый URL из разных форматов ответа (строка, список, dict, FileOutput)."""
    urls = []
    def consider(x):
        if x is None:
            return
        if isinstance(x, str) and x.startswith(("http://", "https://")):
            urls.append(x); return
        for attr in ("url", "href"):
            try:
                val = getattr(x, attr, None)
                if isinstance(val, str) and val.startswith(("http://", "https://")):
                    urls.append(val); return
            except Exception:
                pass
        try:
            s = str(x)
            if s.startswith(("http://", "https://")):
                urls.append(s)
        except Exception:
            pass
    if isinstance(output, dict):
        for key in ("images", "image", "output", "result", "results", "urls", "url", "data"):
            if key in output:
                v = output[key]
                if isinstance(v, list):
                    for it in v: consider(it)
                else:
                    consider(v)
    elif isinstance(output, list):
        for it in output: consider(it)
    else:
        consider(output)
    return urls[0] if urls else None

# ====== Run ======
if run:
    # базовые проверки
    errors = []
    if person_file is None: errors.append("Upload YOUR photo.")
    if cloth_file  is None: errors.append("Upload CLOTHING photo.")
    rep_token = os.getenv("REPLICATE_API_TOKEN") or (st.secrets.get("REPLICATE_API_TOKEN") if hasattr(st, "secrets") else None)
    if not rep_token: errors.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")
    if not REPLICATE_AVAILABLE: errors.append("`replicate` package not installed (add to requirements.txt).")
    if errors:
        st.error(" | ".join(errors))
    else:
        os.environ["REPLICATE_API_TOKEN"] = rep_token

        try:
            # 1) нормализуем → 2) грузим в Replicate Files → 3) получаем URL
            pj = _to_jpeg_bytes(person_file)
            cj = _to_jpeg_bytes(cloth_file)
            person_url = _upload_to_replicate_files(pj, "person.jpg")
            cloth_url  = _upload_to_replicate_files(cj, "cloth.jpg")
        except Exception as e:
            st.exception(e)
            st.error("Preprocess/upload failed.")
            st.stop()

        st.subheader("Debug (prepared URLs)")
        st.write({"person_url": person_url, "cloth_url": cloth_url, "model": model_choice})

        # зафиксированные версии (при необходимости обнови)
        IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
        ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

        try:
            with st.spinner("Generating try-on…"):
                if model_choice.startswith("idm-vton"):
                    # ВАЖНО: ровно те ключи, которые просит модель
                    output = replicate.run(
                        IDM_VTON,
                        input={"human_img": person_url, "garm_img": cloth_url}
                    )
                else:
                    output = replicate.run(
                        ECOM_VTON,
                        input={"face_image": person_url, "commerce_image": cloth_url}
                    )

            st.subheader("Debug (raw output)")
            st.write(output)

            result_url = _extract_first_image_url(output)
            if result_url:
                st.subheader("Result")
                st.image(result_url, use_container_width=True)
                st.success("Done!")
            else:
                st.error("No image URL parsed from response. Try the other model or different images.")

        except Exception as e:
            st.exception(e)
            st.error("Try-on failed.")
