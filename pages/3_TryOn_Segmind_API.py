import os, io, json, base64, requests, streamlit as st
from PIL import Image, ImageFilter

st.set_page_config(page_title="Try-On (SegFit v1.3)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — SegFit v1.3")
st.caption("Segmind SegFit v1.3: model_type, cn_strength, cn_end, image_format/quality, авто-апскейл входов.")

c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader("Your photo (front-facing, upper body)", type=["jpg","jpeg","png","webp"])
with c2:
    cloth_file  = st.file_uploader("Clothing image (product photo)",       type=["jpg","jpeg","png","webp"])

with st.expander("Model & Quality"):
    model_type    = st.selectbox("model_type", ["Speed","Balanced","Quality"], 2)
    cn_strength   = st.slider("cn_strength (detailing)", 0.5, 1.0, 0.8, 0.05)
    cn_end        = st.slider("cn_end (end step)",       0.3, 0.9, 0.5, 0.05)
    image_format  = st.selectbox("image_format", ["jpeg","png","webp"], 0)
    image_quality = st.slider("image_quality", 70, 100, 95)

with st.expander("Input pre-process"):
    min_side = st.slider("Min short side (upscale if smaller)", 640, 1400, 1024, 64)
    max_side = st.slider("Max long side (downscale if larger)", 1000, 2200, 1600, 50)
    jpeg_q_in = st.slider("JPEG quality for inputs", 80, 100, 95)
    post_up   = st.checkbox("Post-upscale ×1.25 + sharpen", True)

with st.expander("Variants"):
    n_variants = st.slider("Render variants (different seeds)", 1, 3, 1)
    seed_base  = st.number_input("Seed base (−1 = random)", value=-1, min_value=-1, max_value=999_999_999)

run = st.button("Try on (SegFit v1.3)")

def to_jpeg_bytes(file, min_side_px=1024, max_side_px=1600, quality=95) -> bytes:
    img = Image.open(file).convert("RGB")
    w, h = img.size
    long_side, short_side = max(w,h), min(w,h)
    if short_side < min_side_px: scale = min_side_px/short_side
    elif long_side > max_side_px: scale = max_side_px/long_side
    else: scale = 1.0
    if scale != 1.0: img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=quality); return buf.getvalue()

def b64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode("utf-8")

def call_segfit(model_b64, outfit_b64, *, model_type, cn_strength, cn_end, image_format, image_quality, seed, timeout_s=240):
    url = "https://api.segmind.com/v1/segfit-v1.3"
    payload = {
        "model_image":  model_b64,
        "outfit_image": outfit_b64,
        "model_type":   model_type,
        "cn_strength":  float(cn_strength),
        "cn_end":       float(cn_end),
        "image_format": image_format,
        "image_quality": int(image_quality),
        "base64": True,
    }
    if seed >= 0: payload["seed"] = int(seed)
    api_key = os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else None)
    headers = {"x-api-key": api_key or "", "Content-Type":"application/json", "Accept":"application/json"}
    r = requests.post(url, data=json.dumps(payload).encode("utf-8"), headers=headers, timeout=timeout_s)
    if r.status_code == 200:
        js = r.json(); img_b64 = js.get("image") if isinstance(js, dict) else js
        return True, base64.b64decode(img_b64), r
    return False, r.text, r

if run:
    if not person_file or not cloth_file:
        st.error("Upload both photos."); st.stop()
    try:
        person_b64 = b64(to_jpeg_bytes(person_file, min_side, max_side, jpeg_q_in))
        cloth_b64  = b64(to_jpeg_bytes(cloth_file,  min_side, max_side, jpeg_q_in))
    except Exception as e:
        st.error(f"Preprocess failed: {e}"); st.stop()

    cols = st.columns(min(n_variants,3))
    any_ok = False
    for i in range(n_variants):
        seed_i = -1 if seed_base < 0 else int(seed_base)+i
        ok, data, resp = call_segfit(person_b64, cloth_b64,
                                     model_type=model_type, cn_strength=cn_strength, cn_end=cn_end,
                                     image_format=image_format, image_quality=image_quality, seed=seed_i)
        with cols[i % len(cols)]:
            st.markdown(f"**Variant {i+1}** — seed={seed_i}")
            if ok:
                img_bytes = data
                if post_up:
                    try:
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        w,h = img.size
                        img = img.resize((int(w*1.25), int(h*1.25)), Image.LANCZOS)
                        img = img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=130, threshold=2))
                        out = io.BytesIO(); img.save(out, format="JPEG", quality=min(98, image_quality+1))
                        img_bytes = out.getvalue()
                    except: pass
                st.image(img_bytes, use_container_width=True)
                any_ok = True
            else:
                st.error(f"API error: {data}")
                if resp is not None:
                    st.caption(str(dict(resp.headers)))
    if not any_ok:
        st.warning("No variant succeeded. Try Balanced, меньше cn_strength/quality, другой seed или другие фото.")
