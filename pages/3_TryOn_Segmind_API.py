import os, io, json, base64, requests, streamlit as st
from PIL import Image, ImageFilter

st.set_page_config(page_title="Try-On (SegFit v1.3)", page_icon="🧪", layout="centered")
st.title("🧪 Try-On — SegFit v1.3 (Hardened)")
st.caption("Авто-апскейл входов, несколько стратегий вызова, подробный лог. Если какой-то режим падает — пробуем следующий.")

# ============ UI ============
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Фронтально, по грудь. Можно <1024px — апскейлим."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo) — REQUIRED",
        type=["jpg","jpeg","png","webp"],
        help="Карточка товара на ровном фоне. Можно <1024px — апскейлим."
    )

with st.expander("Model & Quality"):
    model_type_pref = st.selectbox("Preferred model_type", ["Quality", "Balanced", "Speed"], index=0)
    cn_strength = st.slider("cn_strength (detailing)", 0.5, 1.0, 0.8, 0.05)
    cn_end     = st.slider("cn_end (end step)",       0.3, 0.9, 0.5, 0.05)
    image_format = st.selectbox("image_format", ["jpeg", "png", "webp"], index=0)
    image_quality = st.slider("image_quality (1–100)", 70, 100, 95)

with st.expander("Input pre-process"):
    min_side = st.slider("Min short side (upscale if smaller)", 640, 1400, 1024, step=64)
    max_side = st.slider("Max long side (downscale if larger)", 1000, 2200, 1600, step=50)
    jpeg_quality_in = st.slider("JPEG quality for inputs", 80, 100, 95)
    post_upscale = st.checkbox("Post-upscale ×1.25 + sharpen", True)

with st.expander("Variants"):
    n_variants = st.slider("Render variants (different seeds)", 1, 3, 1)
    seed_base  = st.number_input("Seed base (−1 = random)", value=-1, min_value=-1, max_value=999_999_999)

run = st.button("Try on (SegFit v1.3)")

# ============ Helpers ============
def to_jpeg_bytes(file, min_side_px=1024, max_side_px=1600, quality=95) -> bytes:
    img = Image.open(file).convert("RGB")
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError("Empty image")
    long_side, short_side = max(w, h), min(w, h)
    if short_side < min_side_px:
        scale = min_side_px / short_side
    elif long_side > max_side_px:
        scale = max_side_px / long_side
    else:
        scale = 1.0
    if scale != 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

def b64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode("utf-8")

def kb_from_b64(s: str) -> int:
    # грубо: base64 на ~33% больше исходного
    return int(len(s) * 0.75 / 1024)

def call_segfit(model_b64: str, outfit_b64: str, *, model_type: str, cn_strength: float, cn_end: float,
                image_format: str, image_quality: int, seed: int, base64_out: bool, timeout_s: int = 240):
    url = "https://api.segmind.com/v1/segfit-v1.3"
    payload = {
        "model_image":  model_b64,
        "outfit_image": outfit_b64,
        "model_type":   model_type,     # "Speed" | "Balanced" | "Quality"
        "cn_strength":  float(cn_strength),
        "cn_end":       float(cn_end),
        "image_format": image_format,   # "jpeg" | "png" | "webp"
        "image_quality": int(image_quality),
        "base64":       bool(base64_out),
    }
    # Если seed < 0 — не отправляем вовсе (избегаем крашей у бэкенда)
    if seed >= 0:
        payload["seed"] = int(seed)

    api_key = os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else None)
    if not api_key:
        return False, "SEGMIND_API_KEY not found in secrets/env", None, payload

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json" if base64_out else "*/*",
    }
    data = json.dumps(payload).encode("utf-8")

    try:
        r = requests.post(url, data=data, headers=headers, timeout=timeout_s)
    except Exception as e:
        return False, f"Request failed: {e}", None, payload

    if r.status_code == 200:
        try:
            if base64_out:
                js = r.json()
                img_b64 = js.get("image") if isinstance(js, dict) else js
                img_bytes = base64.b64decode(img_b64)
                return True, img_bytes, r, payload
            else:
                # отдадут бинарный JPEG/PNG
                return True, r.content, r, payload
        except Exception as e:
            return False, f"Parse response failed: {e}\nRaw: {r.text[:1000]}", r, payload

    # Вернём текст ошибки для дебага
    try:
        err_text = r.text
    except Exception:
        err_text = "<no text>"
    return False, f"API error {r.status_code}: {err_text[:1000]}", r, payload

# ============ Run ============
if run:
    errs = []
    if not person_file: errs.append("Upload YOUR photo.")
    if not cloth_file:  errs.append("Upload CLOTHING photo.")
    api_key_present = bool(os.getenv("SEGMIND_API_KEY") or (st.secrets.get("SEGMIND_API_KEY") if hasattr(st, "secrets") else None))
    if not api_key_present: errs.append("Add SEGMIND_API_KEY to Secrets.")
    if errs:
        st.error(" | ".join(errs))
        st.stop()

    # Готовим входы (ап/даунскейл)
    try:
        p_bytes = to_jpeg_bytes(person_file, min_side_px=min_side, max_side_px=max_side, quality=jpeg_quality_in)
        c_bytes = to_jpeg_bytes(cloth_file,  min_side_px=min_side, max_side_px=max_side, quality=jpeg_quality_in)
        p_b64, c_b64 = b64(p_bytes), b64(c_bytes)
    except Exception as e:
        st.error(f"Preprocess failed: {e}")
        st.stop()

    # Покажем инфо о размерах
    with st.expander("Input sizes (after preprocess)"):
        st.write({
            "person_kB": round(len(p_bytes)/1024, 1),
            "cloth_kB":  round(len(c_bytes)/1024, 1),
            "person_b64_kB": kb_from_b64(p_b64),
            "cloth_b64_kB":  kb_from_b64(c_b64),
            "min_side": min_side,
            "max_side": max_side,
            "jpeg_quality_in": jpeg_quality_in
        })

    # Стратегии вызова — от «качества» к «надёжности»
    # 1) Preferred model_type + base64 ответ
    # 2) Balanced + base64
    # 3) Balanced + base64, сниженная детальность
    # 4) Balanced + бинарный ответ (base64_out=False)
    strategies = [
        ("S1", model_type_pref,        cn_strength,     cn_end,     True),
        ("S2", "Balanced",             cn_strength,     cn_end,     True),
        ("S3", "Balanced",             min(cn_strength, 0.7), 0.6,  True),
        ("S4", "Balanced",             min(cn_strength, 0.7), 0.6,  False),
    ]

    cols = st.columns(min(n_variants, 3))
    any_ok = False
    for v in range(n_variants):
        seed_v = -1 if seed_base < 0 else int(seed_base) + v
        for name, mt, cns, cne, base64_out in strategies:
            with st.spinner(f"SegFit v1.3 → {name} (seed={seed_v}, type={mt}, base64_out={base64_out})"):
                ok, data, resp, sent = call_segfit(
                    model_b64=p_b64,
                    outfit_b64=c_b64,
                    model_type=mt,
                    cn_strength=cns,
                    cn_end=cne,
                    image_format=image_format,
                    image_quality=image_quality,
                    seed=seed_v,
                    base64_out=base64_out,
                    timeout_s=240
                )

            # Лог запроса/ответа (без самих картинок)
            with st.expander(f"Debug {name} / variant {v+1}"):
                safe_sent = {k: (("<b64 person>" if k=="model_image" else "<b64 cloth>") if k in ("model_image","outfit_image") else sent[k])
                             for k in sent.keys()}
                st.write({"payload": safe_sent})
                if resp is not None:
                    st.write({"status": resp.status_code, "headers": dict(resp.headers)})
                    try:
                        st.code((resp.text or "")[:1200])
                    except Exception:
                        pass
                else:
                    st.write({"response": None})

            if ok:
                img_bytes = data
                if post_upscale:
                    try:
                        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        w, h = img.size
                        img = img.resize((int(w*1.25), int(h*1.25)), Image.LANCZOS)
                        img = img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=130, threshold=2))
                        out = io.BytesIO()
                        out_format = "JPEG" if image_format.lower() == "jpeg" else image_format.upper()
                        img.save(out, format=out_format, quality=min(98, image_quality+1))
                        img_bytes = out.getvalue()
                    except Exception:
                        pass
                with cols[v % len(cols)]:
                    st.image(img_bytes, use_container_width=True, caption=f"{name} · {mt} · seed {seed_v}")
                any_ok = True
                break  # выходим из стратегий — вариант готов

        # если текущий вариант не удался всеми стратегиями — продолжаем к следующему сид
    if not any_ok:
        st.error("SegFit вернул ошибки на всех стратегиях. Это обычно их серверная проблема. "
                 "Попробуй позже/другие фото. Request-ID см. в Debug-блоках (кинуть в саппорт).")
