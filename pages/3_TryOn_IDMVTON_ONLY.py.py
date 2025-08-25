import os
import io
import tempfile
import streamlit as st
from PIL import Image

# ==== Replicate SDK ====
try:
    import replicate
    from replicate import files as replicate_files
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False
    replicate_files = None  # type: ignore

st.set_page_config(page_title="Try-On — IDM-VTON ONLY", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — IDM-VTON ONLY")
st.caption("Build: IDMVTON-SINGLE v1 — без фолбеков, только human_img + garm_img, прямой аплоад в Replicate Files.")

# ==== UI ====
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body) — REQUIRED",
        type=["jpg", "jpeg", "png", "webp"],
        help="Фронтально, по грудь. Желательно ≥512px по короткой стороне."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo) — REQUIRED",
        type=["jpg", "jpeg", "png", "webp"],
        help="Карточка товара на ровном фоне."
    )
run = st.button("Try on")

# ==== Helpers ====
def to_jpeg_bytes(uploaded_file, min_side: int = 512, max_side: int = 1024) -> bytes:
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

def upload_to_replicate(jpeg_bytes: bytes, suffix=".jpg") -> str:
    if not REPLICATE_AVAILABLE or not replicate_files:
        raise RuntimeError("Replicate SDK/files unavailable")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(jpeg_bytes)
        tf.flush()
        path = tf.name
    # Вернёт прямую ссылку вида https://replicate.delivery/...
    return replicate_files.upload(path)

def extract_first_image_url(output):
    urls = []
    def consider(x):
        if x is None: return
        if isinstance(x, str) and x.startswith(("http://", "https://")):
            urls.append(x); return
        for attr in ("url", "href"):
            try:
                v = getattr(x, attr, None)
                if isinstance(v, str) and v.startswith(("http://", "https://")):
                    urls.append(v); return
            except Exception:
                pass
        try:
            s = str(x)
            if s.startswith(("http://", "https://")):
                urls.append(s)
        except Exception:
            pass
    if isinstance(output, dict):
        for k in ("images","image","output","result","results","urls","url","data"):
            if k in output:
                v = output[k]
                if isinstance(v, list):
                    for it in v: consider(it)
                else:
                    consider(v)
    elif isinstance(output, list):
        for it in output: consider(it)
    else:
        consider(output)
    return urls[0] if urls else None

# ==== Run ====
if run:
    # Гварды
    errors = []
    if person_file is None: errors.append("Upload YOUR photo.")
    if cloth_file  is None: errors.append("Upload CLOTHING photo.")
    token = os.getenv("REPLICATE_API_TOKEN") or (st.secrets.get("REPLICATE_API_TOKEN") if hasattr(st, "secrets") else None)
    if not token: errors.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")
    if not REPLICATE_AVAILABLE: errors.append("`replicate` package not installed (add to requirements.txt).")
    if errors:
        st.error(" | ".join(errors))
        st.stop()

    os.environ["REPLICATE_API_TOKEN"] = token

    # 1) нормализуем обе картинки
    try:
        pj = to_jpeg_bytes(person_file)
        cj = to_jpeg_bytes(cloth_file)
    except Exception as e:
        st.exception(e)
        st.error("Preprocess failed.")
        st.stop()

    # 2) грузим в Replicate Files → получаем HTTPS URL
    try:
        human_url = upload_to_replicate(pj, ".jpg")
        garm_url  = upload_to_replicate(cj, ".jpg")
    except Exception as e:
        st.exception(e)
        st.error("Upload to Replicate Files failed.")
        st.stop()

    # Печатаем, ЧТО ИМЕННО отправим в модель
    st.subheader("Debug (request to model)")
    input_payload = {"human_img": human_url, "garm_img": garm_url}
    st.json(input_payload)

    # 3) вызываем КОНКРЕТНУЮ версию IDM-VTON с ЭТИМИ ключами
    IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"

    try:
        with st.spinner("Generating try-on (IDM-VTON)…"):
            output = replicate.run(IDM_VTON, input=input_payload)

        st.subheader("Debug (raw output)")
        st.write(output)

        result_url = extract_first_image_url(output)
        if result_url:
            st.subheader("Result")
            st.image(result_url, use_container_width=True)
            st.success("Done!")
        else:
            st.error("No image URL parsed from response.")

    except Exception as e:
        # Показываем ПОЛНУЮ ошибку модели (без скрытия)
        st.exception(e)
        st.error("Model call failed.")
