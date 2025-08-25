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

st.set_page_config(page_title="Virtual Try-On (beta)", page_icon="🪄", layout="centered")
st.title("🪄 Virtual Try-On (beta)")
st.caption("Build: TryOn DirectUpload v2 — файлы передаются напрямую в Replicate, без внешних хостингов.")

# ================== UI ==================
c1, c2 = st.columns(2)
with c1:
    person_file = st.file_uploader(
        "Your photo (front-facing, upper body)",
        type=["jpg", "jpeg", "png", "webp"],
        help="Фронтально, по грудь. Желательно ≥512px по короткой стороне."
    )
with c2:
    cloth_file = st.file_uploader(
        "Clothing image (product photo)",
        type=["jpg", "jpeg", "png", "webp"],
        help="Карточка товара на ровном фоне."
    )

# опционально: можно дать URL для одежды (или для себя, если не хочешь грузить файл)
person_url_input = st.text_input("...or paste YOUR photo URL (optional)")
cloth_url = st.text_input("...or paste clothing image URL (optional)")

model_choice = st.selectbox(
    "Model endpoint",
    ["idm-vton (Replicate)", "ecommerce-virtual-try-on (Replicate)"],
    index=0
)

# ================== Helpers ==================
def _filelike_from_uploaded(uploaded_file, out_name: str, min_side: int = 512, max_side: int = 1024):
    """
    Открываем любой формат, конвертим в RGB JPEG.
    Если очень маленькое изображение — мягко подтягиваем до ~min_side по короткой стороне.
    Если очень большое — уменьшаем до ~max_side по длинной стороне.
    Возвращаем BytesIO с .name, готовый для передачи в replicate.run().
    """
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
    # важно: задать имя — некоторым SDK это помогает определить тип
    buf.name = out_name
    return buf

# ================== Build inputs for Replicate ==================
# Каждый инпут может быть либо file-like объектом (BytesIO), либо строкой-URL.
person_input = None
cloth_input  = None

# Приоритет: если дан прямой URL — используем его; иначе — файл
if person_url_input.strip():
    person_input = person_url_input.strip()
elif person_file is not None:
    try:
        person_input = _filelike_from_uploaded(person_file, "person.jpg")
    except Exception as e:
        st.error(f"Cannot process your photo: {e}")

if cloth_url.strip():
    cloth_input = cloth_url.strip()
elif cloth_file is not None:
    try:
        cloth_input = _filelike_from_uploaded(cloth_file, "cloth.jpg")
    except Exception as e:
        st.error(f"Cannot process clothing image: {e}")

with st.expander("Input debug"):
    st.write({
        "person_input": "file" if hasattr(person_input, "read") else (person_input or None),
        "cloth_input":  "file" if hasattr(cloth_input, "read")  else (cloth_input  or None),
        "model": model_choice
    })

run = st.button("Try on")

# ================== Guards ==================
if run:
    errors = []
    if person_input is None:
        errors.append("Upload your photo or paste its direct URL.")
    if cloth_input is None:
        errors.append("Provide clothing image (file upload or direct URL).")

    rep_token = os.getenv("REPLICATE_API_TOKEN")
    if not rep_token:
        try:
            rep_token = st.secrets["REPLICATE_API_TOKEN"]
        except Exception:
            rep_token = None
    if not rep_token:
        errors.append("Missing REPLICATE_API_TOKEN in Streamlit Secrets.")

    if errors:
        st.error(" | ".join(errors))
        st.stop()

    if not REPLICATE_AVAILABLE:
        st.error("`replicate` package not found. Ensure `replicate` is in requirements.txt.")
        st.stop()

    os.environ["REPLICATE_API_TOKEN"] = rep_token

    # Пинованные версии (при желании обнови на актуальные с Replicate)
    IDM_VTON = "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2"
    ECOM_VTON = "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447"

    def run_idm_vton(person, cloth):
        # Многие билды принимают и URL, и файл-объект
        try:
            return replicate.run(IDM_VTON, input={"human_img": person, "garm_img": cloth})
        except Exception:
            return replicate.run(IDM_VTON, input={"human_image": person, "cloth_image": cloth})

    def run_ecom_vton(person, cloth):
        try:
            return replicate.run(ECOM_VTON, input={"face_image": person, "commerce_image": cloth})
        except Exception:
            return replicate.run(ECOM_VTON, input={"image_person": person, "image_clothing": cloth})

    # ================== Run ==================
    try:
        with st.spinner("Generating try-on…"):
            if model_choice.startswith("idm-vton"):
                output = run_idm_vton(person_input, cloth_input)
            else:
                output = run_ecom_vton(person_input, cloth_input)

        # Replicate обычно отдаёт список URL или одну URL-строку
        if isinstance(output, list) and output:
            result_url = output[0]
        elif isinstance(output, str):
            result_url = output
        else:
            result_url = None

        if result_url:
            st.subheader("Result")
            st.image(result_url, use_container_width=True)
            with st.expander("Debug info"):
                st.write({
                    "person": "file" if hasattr(person_input, "read") else person_input,
                    "cloth":  "file" if hasattr(cloth_input, "read")  else cloth_input,
                    "raw_output": output if not isinstance(output, (str, bytes)) else "(string)"
                })
            st.success("Done! Try other photos for comparison.")
        else:
            st.error("No image in response. Try another model or different images.")

    except Exception as e:
        st.error(f"Try-on failed: {e}")
        st.info("Tips: use a clear front-facing photo (≥512px) and a product image with the garment fully visible.")
