import os, io, base64, requests, streamlit as st
from PIL import Image, ImageFilter

st.set_page_config(page_title="Try-On (Segmind API)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — Segmind API (HQ)")
st.caption("Качество: больше входное разрешение, больше шагов, несколько сидов, опциональный апскейл/шарп.")

# ===== UI =====
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body)",
        type=["jpg","jpeg","png","webp"],
        help="Фронтально, по грудь. Лучше ≥768 px по короткой стороне."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo)",
        type=["jpg","jpeg","png","webp"],
        help="Карточка товара/предмет на ровном фоне."
    )

category = st.selectbox("Category", ["Upper body","Lower body","Dress"], index=0)

with st.expander("Quality settings"):
    hq = st.checkbox("High quality mode", True)
    steps = st.slider("num_inference_steps", 20, 60, 50 if hq else 35)
    guidance = st.slider("guidance_scale", 1.0, 6.0, 3.0 if hq else 2.0)
    n_variants = st.slider("Render variants (different seeds)", 1, 4, 2 if hq else 1)
    seed_base = st.number_input("seed start (-1 = random)", value=-1, min_value=-1, max_value=999_999_999)
    post_upscale = st.checkbox("Post-upscale ×1.5 + sharpen (client-side)", True if hq else False)

run = st.button("Try on (Segmind)")

# ===== helpers =====
def to_jpeg_bytes(file, min_side=768, max_side=1536, quality=95) -> bytes:
    """Более крупные входы для лучшей детализации."""
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
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

def b64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode("utf-8")

def postprocess_upscale(img_bytes: bytes, scale=1.5) -> bytes:
    """Простой клиентский апскейл + UnsharpMask — без внешних сервисов."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size
    img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=150, threshold=3))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95)
    return out.getvalue()

def call_segmind(person_b64: str, cloth_b64: str, category: str, steps: int, guidance: float, seed: int, base64_out=True):
    url = "https://api.segmind.com/v1/try-on-diffusion"
    payload = {
        "model_image": person_b64,
        "cloth_image": cloth_b64,
        "category": category,                 # "Upper body" | "Lower body" | "Dress"
        "num_inference_steps": int(steps),
        "guidance_scale": float(guidance),
        "seed": int(seed),
        "base64": bool(base64_out)
    }
    headers = {"x-api-key": os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else "")}
    r = requests.post(url, json=payload, headers=headers, timeout=180)
    return r

# ===== run =====
if run:
    errs = []
    if not person_file: errs.append("Upload YOUR photo.")
    if not cloth_file:  errs.append("Upload CLOTHING photo.")
    api_key = os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else None)
    if not api_key: errs.append("Add SEGMIND_API_KEY to Secrets.")
    if errs:
        st.error(" | ".join(errs))
    else:
        try:
            person_b64 = b64(to_jpeg_bytes(person_file, min_side=(768 if hq else 512),
                                           max_side=(1536 if hq else 1024),
                                           quality=(95 if hq else 90)))
            cloth_b64  = b64(to_jpeg_bytes(cloth_file,  min_side=(768 if hq else 512),
                                           max_side=(1536 if hq else 1024),
                                           quality=(95 if hq else 90)))
        except Exception as e:
            st.error(f"Preprocess failed: {e}")
            st.stop()

        cols = st.columns(n_variants)
        got_any = False
        for i in range(n_variants):
            # генерим разные сиды (если -1, даём -1 чтобы API само рандомизировало)
            seed = -1 if seed_base < 0 else (int(seed_base) + i)
            with st.spinner(f"Generating variant {i+1}/{n_variants}…"):
                r = call_segmind(person_b64, cloth_b64, category, steps, guidance, seed, base64_out=True)

            if r.status_code == 200:
                try:
                    data = r.json()
                    img_b64 = data.get("image") if isinstance(data, dict) else data
                    img_bytes = base64.b64decode(img_b64)
                    if post_upscale:
                        img_bytes = postprocess_upscale(img_bytes, scale=1.5)
                    with cols[i]:
                        st.image(img_bytes, use_container_width=True, caption=f"Variant {i+1} (seed={seed})")
                    got_any = True
                except Exception as e:
                    st.error(f"Parse response failed (variant {i+1}): {e}")
                    st.code(r.text[:1200])
            else:
                st.error(f"API error {r.status_code} (variant {i+1})")
                st.code(r.text[:1200])

        if not got_any:
            st.warning("No variants succeeded. Try fewer steps, other seed, or different photos.")
