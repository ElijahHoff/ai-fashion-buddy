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
st.caption("Build: DU-DEBUG v3 — прямой аплоад в Replicate (без внешних хостингов).")

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
    """
    Любой формат -> RGB JPEG. Подтягиваем очень мелкое до min_side, большое уменьшаем до max_side.
    Возвращаем BytesIO с .name (важно для SDK).
    """
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    long_side, short_side = max(w, h), min(w, h)

    if w == 0 or h == 0:
        raise ValueError("Empty image")

    # апскейл мелкого или даунскейл огромного
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

# ========== Run ==========
if run:
    # ---- basic guards ----
    errors = []
    if person_file is None:
        errors.append("Upload YOUR photo.")
    if cloth_file is None:
        errors.append("Upload CLOTHING photo.")

    rep_token = os.getenv("REPLICATE_API_TOKEN")
    if not rep_token:
        try:
            rep_token = st.secrets["REPLICATE_API_TOKEN"]
        except Exception:
            rep_token = None
    if not rep_token:
        errors.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")

    if not REPLICATE_AVAILABLE:
        errors.append("`replicate` package not installed (add to requirements.txt).")

    if errors:
        st.error(" | ".join(errors))
        st.stop()

    os.environ["REPLICATE_API_TOKEN"] = rep_token

    # ---- prepare inputs as file-like ----
    try:
        person_input = _to_jpeg_filelike(person_file, "person.jpg")
    except Exception as e:
        st.error(f"Cannot read your photo: {e}")
        st.stop()

    try:
        cloth_input = _to_jpeg_filelike(cloth_file, "cloth.jpg")
    except Exception as e:
        st.error(f"Cannot read clothing photo: {e}")
        st.stop()

    # ---- pinned model versions ----
    IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
    ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

    def run_idm_vton(person, cloth):
        # сначала human_img/garm_img, потом fallback
        try:
            return replicate.run(IDM_VTON, input={"human_img": person, "garm_img": cloth})
        except Exception:
            return replicate.run(IDM_VTON, input={"human_image": person, "cloth_image": cloth})

    def run_ecom_vton(person, cloth):
        # сначала face_image/commerce_image, потом fallback
        try:
            return replicate.run(ECOM_VTON, input={"face_image": person, "commerce_image": cloth})
        except Exception:
            return replicate.run(ECOM_VTON, input={"image_person": person, "image_clothing": cloth})

    # ---- call ----
    try:
        with st.spinner("Generating try-on…"):
            if model_choice.startswith("idm-vton"):
                output = run_idm_vton(person_input, cloth_input)
            else:
                output = run_ecom_vton(person_input, cloth_input)

        # Replicate часто возвращает список URL или строку URL
        if isinstance(output, list) and output:
            result_url = output[0]
        elif isinstance(output, str):
            result_url = output
        else:
            result_url = None

        st.subheader("Debug")
        st.write({
            "model": model_choice,
            "token_present": bool(rep_token),
            "person_input": "file" if hasattr(person_input, "read") else str(type(person_input)),
            "cloth_input":  "file" if hasattr(cloth_input, "read")  else str(type(cloth_input)),
            "raw_output": output,
        })

        if result_url:
            st.subheader("Result")
            st.image(result_url, use_container_width=True)
            st.success("Done!")
        else:
            st.error("No image URL in response. Try the other model or different images.")

    except Exception as e:
        # Покажем полную трассировку, чтобы понять, где именно падает
        st.exception(e)
        st.error("Try-on failed. Switch model (IDM/Ecommerce) or try different images.")
