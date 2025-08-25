import os
import requests
import streamlit as st

# Optional: Replicate SDK
try:
    import replicate
    REPLICATE_AVAILABLE = True
except Exception:
    REPLICATE_AVAILABLE = False

st.set_page_config(page_title="Virtual Try-On (beta)", page_icon="🪄", layout="centered")
st.title("🪄 Virtual Try-On (beta)")
st.caption("Загрузите своё фото и фото вещи (или вставьте URL), и модель покажет, как вещь будет выглядеть на вас. Фото не сохраняются.")

# --- Uploads / Inputs ---
col1, col2 = st.columns(2)
with col1:
    person_file = st.file_uploader("Your photo (front-facing, upper body)", type=["jpg", "jpeg", "png"])
with col2:
    cloth_file = st.file_uploader("Clothing image (product photo)", type=["jpg", "jpeg", "png"])

cloth_url = st.text_input("...or paste clothing image URL")

model_choice = st.selectbox(
    "Model endpoint",
    ["idm-vton (Replicate)", "ecommerce-virtual-try-on (Replicate)"],
    index=0
)

def _tmp_host(uploaded_file):
    """Upload file to a temporary host to obtain a public URL (MVP).
    В продакшене лучше использовать S3 или Cloudflare R2."""
    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        r = requests.post("https://tmpfiles.org/api/v1/upload", files=files, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("data", {}).get("url")
    except Exception as e:
        st.warning(f"Temporary hosting failed: {e}")
        return None

person_url = None
cloth_img_url = None

if person_file:
    person_url = _tmp_host(person_file)
if cloth_file:
    cloth_img_url = _tmp_host(cloth_file)
if not cloth_img_url and cloth_url:
    cloth_img_url = cloth_url.strip()

run = st.button("Try on")

# --- Guard rails / tokens ---
rep_token = os.getenv("REPLICATE_API_TOKEN") or st.secrets.get("REPLICATE_API_TOKEN")
if not rep_token:
    st.info("Add REPLICATE_API_TOKEN to Streamlit **Secrets** to enable try-on.")
    st.stop()
if not REPLICATE_AVAILABLE:
    st.error("`replicate` package not found. Ensure `replicate` is in requirements.txt.")
    st.stop()

os.environ["REPLICATE_API_TOKEN"] = rep_token

# --- Run ---
if run:
    if not (person_url and cloth_img_url):
        st.error("Please provide both your photo and a clothing image (or URL).")
        st.stop()

    try:
        with st.spinner("Generating try-on…"):
            if model_choice.startswith("idm-vton"):
                # IDM-VTON (KAIST) — Non-commercial use only
                output = replicate.run(
                    "cuuupid/idm-vton:005205c5e7a4053b04418089f3a22b2b62705f0339ddad0b3f6db0d0e66aabc2",
                    input={
                        "human_image": person_url,
                        "cloth_image": cloth_img_url,
                        # можно добавить: "keep_background": True, "seed": 42
                    },
                )
            else:
                # Ecommerce Virtual Try-On
                output = replicate.run(
                    "wolverinn/ecommerce-virtual-try-on:39860afc9f164ce9734d5666d17a771f986dd2bd3ad0935d845054f73bbec447",
                    input={
                        "image_person": person_url,
                        "image_clothing": cloth_img_url,
                    },
                )

        # Replicate возвращает URL(ы) на изображение(я)
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
                    "person_url": person_url,
                    "cloth_url": cloth_img_url,
                    "model": model_choice
                })
            st.success("Done! Try other photos for comparison.")
        else:
            st.error("No image in response. Try another model or different images.")

    except Exception as e:
        st.error(f"Try-on failed: {e}")
        st.info("Tips: use a clear front-facing photo and a product image with the garment fully visible.")
