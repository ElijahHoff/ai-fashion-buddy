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
st.caption("Build: IDMVTON-SINGLE v2 — фиксированная версия + строго human_img/garm_img как URL (Replicate Files).")

# ==== UI ====
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Фронтально, по грудь. Желательно ≥512–768px по короткой стороне."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Карточка товара на ровном фоне."
    )

category = st.selectbox("Category", ["upper_body","lower_body","dresses"], index=0)
crop = st.checkbox("Auto-crop (если фото не 3:4)", True)
steps = st.slider("Steps (1–40)", 10, 40, 30)
seed = st.number_input("Seed (−1 = random)", value=-1, min_value=-1, max_value=2_147_483_647)

run = st.button("Try on (IDM-VTON)")

# ==== helpers ====
def to_jpeg_bytes(uploaded_file, min_side=768, max_side=1536, quality=95) -> bytes:
    img = Image.open(uploaded_file).convert("RGB")
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

def upload_to_replicate(jpeg_bytes: bytes, suffix=".jpg") -> str:
    if not REPLICATE_AVAILABLE or not replicate_files:
        raise RuntimeError("Replicate SDK/files unavailable")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(jpeg_bytes)
        tf.flush()
        path = tf.name
    # вернёт https://replicate.delivery/... — можно давать в input как string
    return replicate_files.upload(path)

def extract_first_url(output):
    if isinstance(output, str) and output.startswith(("http://","https://")):
        return output
    if isinstance(output, list) and output:
        x = output[0]
        # FileOutput и др. объекты имеют .url
        for attr in ("url","href"):
            try:
                v = getattr(x, attr, None)
                if isinstance(v, str) and v.startswith(("http://","https://")):
                    return v
            except Exception:
                pass
        if isinstance(x, str) and x.startswith(("http://","https://")):
            return x
    if isinstance(output, dict):
        for key in ("images","image","output","result","results","urls","url","data"):
            if key in output:
                v = output[key]
                if isinstance(v, list) and v:
                    return extract_first_url(v)
                if isinstance(v, str) and v.startswith(("http://","https://")):
                    return v
    return None

# ==== run ====
if run:
    errs = []
    if not person_file: errs.append("Upload YOUR photo.")
    if not cloth_file:  errs.append("Upload CLOTHING photo.")
    token = os.getenv("REPLICATE_API_TOKEN") or (st.secrets.get("REPLICATE_API_TOKEN") if hasattr(st, "secrets") else None)
    if not token: errs.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")
    if not REPLICATE_AVAILABLE: errs.append("`replicate` package not installed (add to requirements.txt).")
    if errs:
        st.error(" | ".join(errs))
        st.stop()

    os.environ["REPLICATE_API_TOKEN"] = token

    # 1) Нормализуем → 2) грузим в Replicate Files → 3) берём HTTPS-URL
    try:
        pj = to_jpeg_bytes(person_file)
        cj = to_jpeg_bytes(cloth_file)
        human_url = upload_to_replicate(pj, ".jpg")
        garm_url  = upload_to_replicate(cj, ".jpg")
    except Exception as e:
        st.exception(e)
        st.error("Preprocess/upload failed.")
        st.stop()

    st.subheader("Debug (request payload)")
    payload = {
        "human_img": human_url,
        "garm_img": garm_url,
        "category": category,
        "crop": bool(crop),
        "steps": int(steps),
        "seed": (None if seed < 0 else int(seed)),
    }
    st.json(payload)

    # 2) Конкретная рабочая версия IDM-VTON с нужной схемой входов (strings)
    IDM_VTON = "cuuupid/idm-vton:0513734a452173b8173e907e3a59d19a36266e55b48528559432bd21c7d7e985"  # schema: human_img/garm_img/category/crop/steps/seed

    try:
        with st.spinner("Generating try-on…"):
            out = replicate.run(IDM_VTON, input=payload)

        st.subheader("Debug (raw output)")
        st.write(out)

        url = extract_first_url(out)
        if url:
            st.subheader("Result")
            st.image(url, use_container_width=True)
            st.success("Done!")
        else:
            st.error("No image URL parsed from response.")
    except Exception as e:
        st.exception(e)
        st.error("Model call failed.")
