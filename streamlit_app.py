import os
import numpy as np
import streamlit as st
from PIL import Image

# ---- Optional OpenAI (graceful fallback if not set) ----
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# -------------------- Retailer templates --------------------
RETAILERS = {
    "Zalando": "https://www.zalando.de/catalog/?q={q}",
    "ASOS": "https://www.asos.com/search/?q={q}",
    "H&M": "https://www2.hm.com/en_eur/search-results.html?q={q}",
    "Amazon": "https://www.amazon.de/s?k={q}",
}

DEFAULT_ITEMS = [
    ("Top", 0.22),
    ("Bottom", 0.22),
    ("Outerwear", 0.18),
    ("Shoes", 0.24),
    ("Accessory", 0.14),
]

STYLE_KEYWORDS = {
    "casual": ["t-shirt", "jeans", "sneakers"],
    "smart casual": ["oxford shirt", "chinos", "loafers"],
    "business": ["blazer", "trousers", "derby shoes"],
    "evening": ["silk blouse", "dress pants", "heels"],
    "streetwear": ["oversized hoodie", "cargo pants", "chunky sneakers"],
}

GENDER_KEYWORDS = {
    "male": ["men"],
    "female": ["women"],
    "unisex": ["unisex"],
}

# -------------------- Utils --------------------
def extract_palette(img: Image.Image, k: int = 4):
    """Return k prominent colors (simple k-means on pixels)."""
    img_small = img.convert("RGB").resize((64, 64))
    data = np.asarray(img_small).reshape(-1, 3).astype(np.float32)
    centers = data[np.random.choice(len(data), k, replace=False)]
    for _ in range(6):
        dists = ((data[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = dists.argmin(axis=1)
        new_centers = np.array(
            [
                data[labels == i].mean(axis=0) if np.any(labels == i) else centers[i]
                for i in range(k)
            ]
        )
        if np.allclose(new_centers, centers):
            break
        centers = new_centers
    return [tuple(map(int, c)) for c in centers.astype(int).tolist()]


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def budget_split(total: int):
    return [(name, max(10, int(total * pct))) for name, pct in DEFAULT_ITEMS]


def build_queries(event, vibe, gender, colors, sizes):
    base_terms = []
    if vibe:
        base_terms += STYLE_KEYWORDS.get(vibe.lower(), [vibe])
    if gender:
        base_terms += GENDER_KEYWORDS.get(gender.lower(), [gender])
    if colors:
        base_terms += colors
    if sizes:
        base_terms += [sizes]
    if event:
        base_terms += [event]

    base_terms = list(dict.fromkeys([t for t in base_terms if t]))

    return {
        "Top": [" ".join(base_terms + ["top"])],
        "Bottom": [" ".join(base_terms + ["pants"])],
        "Outerwear": [" ".join(base_terms + ["jacket"])],
        "Shoes": [" ".join(base_terms + ["shoes"])],
        "Accessory": [" ".join(base_terms + ["accessory"])],
    }


def product_links(query: str):
    links = []
    for name, tmpl in RETAILERS.items():
        url = tmpl.format(q=query.replace(" ", "+"))
        links.append(f"[{name}]({url})")
    return " | ".join(links)


def describe_outfit_with_ai(system_prompt: str, user_prompt: str, model: str):
    if not OPENAI_AVAILABLE:
        return "(Fallback) Outfit suggestion without AI description."
    api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "(No OpenAI key set) Showing basic suggestions."
    try:
        client = OpenAI(api_key=api_key)
        rsp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
        )
        return rsp.choices[0].message.content.strip()
    except Exception as e:
        return f"(AI error) {e}. Proceeding with basic description."

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="AI Fashion Buddy", page_icon="👗", layout="centered")
st.title("👗 AI Fashion Buddy — your stylist friend")

with st.sidebar:
    st.header("Preferences")
    event = st.text_input("Event / Occasion", placeholder="wedding, date, interview…")
    vibe = st.selectbox(
        "Style vibe", ["", "Casual", "Smart Casual", "Business", "Evening", "Streetwear"]
    )
    gender = st.selectbox("Target section", ["", "Female", "Male", "Unisex"])
    sizes = st.text_input("Sizes (e.g., EU 38, M, 42-32)")
    colors_pref = st.text_input("Preferred colors (comma-separated)")
    budget = st.number_input(
        "Total budget (€)", min_value=50, max_value=5000, value=300, step=10
    )
    model_name = st.text_input(
        "OpenAI model (optional)", value=os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )

    photo = st.file_uploader("Optional: upload a photo (JPG/PNG)", type=["jpg", "jpeg", "png"])

# Extract palette from photo
palette_hex = []
if photo is not None:
    try:
        img = Image.open(photo)
        cols = extract_palette(img, k=4)
        palette_hex = [rgb_to_hex(c) for c in cols]
        st.caption("Detected palette from photo:")
        st.write(" ".join([f"`{c}`" for c in palette_hex]))
        st.image(img, caption="Your photo (not uploaded anywhere)", use_container_width=True)
    except Exception as e:
        st.warning(f"Couldn't process the image: {e}")

# Chat
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hey! I’m your stylist friend. Tell me the occasion ✨"}
    ]

for m in st.session_state.messages:
    st.chat_message(m["role"]).write(m["content"])

prompt = st.chat_input("Ask me anything about your outfit…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

# Outfit plan
colors = [c.strip() for c in (colors_pref.split(",") if colors_pref else []) if c.strip()]
if palette_hex:
    colors += palette_hex

queries = build_queries(event, vibe, gender, colors, sizes)
splits = budget_split(int(budget))

system_prompt = (
    "You are a warm, witty fashion girlfriend. "
    "Be concise but vivid. Explain why the pieces fit the occasion, proportions, and palette."
)
user_prompt = f"Occasion: {event}\nVibe: {vibe}\nGender: {gender}\nSizes: {sizes}\nColors: {', '.join(colors) or '—'}\nBudget: {budget}€"

description = describe_outfit_with_ai(system_prompt, user_prompt, model=model_name)

st.subheader("Your Outfit Plan")
st.write(description)

st.divider()
for (item_name, price), qlist in zip(splits, queries.values()):
    st.markdown(f"### {item_name} — ~{price}€")
    q = qlist[0]
    st.markdown("**Search links:** " + product_links(q))
    st.caption(f"Query: `{q}`")

st.divider()
st.caption("Note: Links go to retailers with your search terms. Apply filters (size, color) there.")
