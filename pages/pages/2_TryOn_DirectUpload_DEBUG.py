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
st.caption("Build: DU-DEBUG v1 — файлы шлём напрямую в Replicate. Без внешних хостингов, минимум логики.")

# ========== UI ==========
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

model_choice = st.selectbox(
    "Model",
    ["idm-vton (recommended)", "ecommerce-virtual-try-on"],
    index=0
)

run = st.button("Try on")

# ========== Helpers ==========
def _to_jpeg_filelike(uploaded_file, out_name: str, min_side: int = 512, max_side: int = 1024):
    """Читаем любой формат → RGB JPEG. Апскейлим очень мелкое до min_side, уменьшаем очень большое до max_side.
       Возвращаем BytesIO с .name (важно для SDK)."""
    img = Image.open(uploaded_file).convert("RGB")
    w, h = img.size
    long_side, short_side = max(w, h), min(w, h)

    if short_side < min_side:
        scale = min_side / short_side
    elif long_side > max_side:
        scale = max_side / long_side
    else:
        scale = 1.0

    if scale != 1.0 and w > 0 and h > 0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    buf.name = out_name
    return buf

# ========== Guardrails ==========
if run:
    errors = []
    if person_file is None:
        errors.append("Upload YOUR photo.")
    if cloth_file is None:
        errors.append("Upload CLOTHING photo.")
    rep_tok_
