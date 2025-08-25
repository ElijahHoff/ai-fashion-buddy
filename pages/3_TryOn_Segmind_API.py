import os, io, base64, requests, streamlit as st
from PIL import Image

st.set_page_config(page_title="Try-On (Segmind API)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — Segmind API")
st.caption("Рабочий путь: шлём фото человека и одежды в Segmind Try-On Diffusion API и получаем результат.")

# ===== UI =====
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Фронтально, по грудь. Желательно ≥512px."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Карточка товара/предмет на ровном фоне."
    )

category = st.selectbox("Category", ["Upper body","Lower body","Dress"], index=0)

with st.expander("Advanced"):
    steps = st.slider("num_inference_steps", 20, 60, 35)
    guidance = st.slider("guidance_scale", 1.0, 10.0, 2.0)
    seed = st.number_input("seed (-1=random)", value=-1, min_value=-1, max_value=999_999_999)

run = st.button("Try on")

# ===== helpers =====
def to_jpeg_bytes(file, min_side=512, max_side=1024) -> bytes:
    img = Image.open(file).convert("RGB")
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError("Empty image")
    long_side, short_side = max(w,h), min(w,h)
    if short_side < min_side:
        scale = min_side / short_side
    elif long_side > max_side:
        scale = max_side / long_side
    else:
        scale = 1.0
    if scale != 1.0:
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def b64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode("utf-8")

# ===== run =====
if run:
    errors = []
    if not person_file: errors.append("Upload YOUR photo.")
    if not cloth_file:  errors.append("Upload CLOTHING photo.")
    api_key = os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else None)
    if not api_key: errors.append("Add SEGMIND_API_KEY to Secrets.")
    if errors:
        st.error(" | ".join(errors))
    else:
        try:
            person_b64 = b64(to_jpeg_bytes(person_file))
            cloth_b64  = b64(to_jpeg_bytes(cloth_file))
        except Exception as e:
            st.error(f"Preprocess failed: {e}")
            st.stop()

        url = "https://api.segmind.com/v1/try-on-diffusion"
        payload = {
            "model_image": person_b64,   # фото человека (base64)
            "cloth_image": cloth_b64,    # фото вещи (base64)
            "category": category,        # Upper body / Lower body / Dress
            "num_inference_steps": int(steps),
            "guidance_scale": float(guidance),
            "seed": int(seed),
            "base64": True               # просим отдать base64
        }
        headers = {"x-api-key": api_key}

        with st.spinner("Generating try-on via Segmind…"):
            r = requests.post(url, json=payload, headers=headers, timeout=120)

        if r.status_code == 200:
            # API возвращает image/jpeg (если base64=False) или base64-строку (если True).
            # Мы запросили base64=True — распарсим:
            try:
                # если пришёл бинарный JPEG
                if r.headers.get("Content-Type","").startswith("image/"):
                    st.image(r.content, use_container_width=True)
                else:
                    data = r.json()
                    # иногда API возвращает просто строку; иногда {"image": "<b64>"}
                    img_b64 = data.get("image") if isinstance(data, dict) else data
                    img_bytes = base64.b64decode(img_b64)
                    st.image(img_bytes, use_container_width=True)
                st.success("Done!")
            except Exception as e:
                st.error(f"Parse response failed: {e}")
                st.text(f"Status {r.status_code} headers {dict(r.headers)}")
                st.code(r.text[:2000])
        else:
            st.error(f"API error {r.status_code}")
            st.text(f"Headers: {dict(r.headers)}")
            st.code(r.text[:4000])
