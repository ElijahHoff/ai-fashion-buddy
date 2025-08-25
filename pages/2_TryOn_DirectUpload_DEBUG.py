import os
import io
import streamlit as st
from PIL import Image

# ===== Replicate SDK =====
try:
    import replicate
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False

st.set_page_config(page_title="Try-On (Direct Upload DEBUG)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — Direct Upload DEBUG")
st.caption("Build: DU-DEBUG v4 — прямой аплоад в Replicate + корректный парсинг FileOutput (.url).")

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
def _to_jpeg_filelike(uploaded_file, out_name: str, min_side: int = 512, max_side: int = 1024):
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
    buf.seek(0)
    buf.name = out_name
    return buf

def _extract_first_image_url(output):
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

# ========== Run ==========
if run:
    errors = []
    if person_file is None: errors.append("Upload YOUR photo.")
    if cloth_file is None:  errors.append("Upload CLOTHING photo.")
    rep_token = os.getenv("REPLICATE_API_TOKEN") or (st.secrets.get("REPLICATE_API_TOKEN") if hasattr(st, "secrets") else None)
    if not rep_token: errors.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")
    if not REPLICATE_AVAILABLE: errors.append("`replicate` package not installed (add to requirements.txt).")
    if errors:
        st.error(" | ".join(errors))
    else:
        os.environ["REPLICATE_API_TOKEN"] = rep_token
        try:
            person_input = _to_jpeg_filelike(person_file, "person.jpg")
            cloth_input  = _to_jpeg_filelike(cloth_file,  "cloth.jpg")
        except Exception as e:
            st.error(f"Preprocess failed: {e}")
            st.stop()

        IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
        ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

        def run_idm_vton(person, cloth):
            try:
                return replicate.run(IDM_VTON, input={"human_img": person, "garm_img": cloth})
            except Exception:
                return replicate.run(IDM_VTON, input={"human_image": person, "cloth_image": cloth})

        def run_ecom_vton(person, cloth):
            try:
                return replicate.run(ECOM_VTON, input={"face_image": person, "commerce_image": cloth})
            except Exception:
                return replicate.run(ECOM_VTON, input={"image_person": person, "image_clothing": cloth})

        try:
            with st.spinner("Generating try-on…"):
                if model_choice.startswith("idm-vton"):
                    output = run_idm_vton(person_input, cloth_input)
                else:
                    output = run_ecom_vton(person_input, cloth_input)

            st.subheader("Debug (raw output)"); st.write(output)
            result_url = _extract_first_image_url(output)

            if result_url:
                st.subheader("Result"); st.image(result_url, use_container_width=True); st.success("Done!")
            else:
                st.error("No image URL in response (parsed). Try the other model (IDM) or different images.")
        except Exception as e:
            st.exception(e)
            st.error("Try-on failed. Switch model (IDM/Ecommerce) or try different images.")
