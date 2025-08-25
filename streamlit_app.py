import os
import io
import numpy as np
import streamlit as st
from PIL import Image

# ---------- OpenAI (optional) ----------
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

def get_env(name: str, default=None):
    val = os.getenv(name)
    if val:
        return val
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

# ---------- App setup ----------
st.set_page_config(page_title="AI Fashion Buddy", page_icon="👗", layout="centered")
st.title("👗 AI Fashion Buddy — your stylist friend")

# ---------- Retailers & heuristics ----------
RETAILERS = {
    "Zalando": "https://www.zalando.de/catalog/?q={q}",
    "ASOS": "https://www.asos.com/search/?q={q}",
    "H&M": "https://www2.hm.com/en_eur/search-results.html?q={q}",
    "Amazon": "https://www.amazon.de/s?k={q}",
}
DEFAULT_ITEMS = [("Top", 0.22), ("Bottom", 0.22), ("Outerwear", 0.18), ("Shoes", 0.24), ("Accessory", 0.14)]
STYLE_KEYWORDS = {
    "casual": ["t-shirt", "jeans", "sneakers"],
    "smart casual": ["oxford shirt", "chinos", "loafers"],
    "business": ["blazer", "trousers", "derby shoes"],
    "evening": ["silk blouse", "dress pants", "heels"],
    "streetwear": ["oversized hoodie", "cargo pants", "chunky sneakers"],
}
GENDER_KEYWORDS = {"male": ["men"], "female": ["women"], "unisex": ["unisex"]}

# ---------- Utils ----------
def extract_palette(img: Image.Image, k: int = 4):
    img_small = img.convert("RGB").resize((64, 64))
    data = np.asarray(img_small).reshape(-1, 3).astype(np.float32)
    centers = data[np.random.choice(len(data), k, replace=False)]
    for _ in range(6):
        dists = ((data[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = dists.argmin(axis=1)
        new_centers = np.array(
            [data[labels == i].mean(axis=0) if np.any(labels == i) else centers[i] for i in range(k)]
        )
        if np.allclose(new_centers, centers):
            break
        centers = new_centers
    return [tuple(map(int, c)) for c in centers.astype(int).tolist()]

def rgb_to_hex(rgb): return "#%02x%02x%02x" % rgb
def budget_split(total: int): return [(n, max(10, int(total * pct))) for n, pct in DEFAULT_ITEMS]

def build_queries(event, vibe, gender, colors, sizes):
    base = []
    if (v := (vibe or "").strip().lower()):   base += STYLE_KEYWORDS.get(v, [v])
    if (g := (gender or "").strip().lower()): base += GENDER_KEYWORDS.get(g, [g])
    if colors: base += colors
    if sizes:  base += [sizes]
    if event:  base += [event]
    base = list(dict.fromkeys([t for t in base if t]))
    return {
        "Top":       [" ".join(base + ["top"])],
        "Bottom":    [" ".join(base + ["pants"])],
        "Outerwear": [" ".join(base + ["jacket"])],
        "Shoes":     [" ".join(base + ["shoes"])],
        "Accessory": [" ".join(base + ["accessory"])],
    }

def product_links(query: str):
    return " | ".join(f"[{name}]({tmpl.format(q=query.replace(' ', '+'))})" for name, tmpl in RETAILERS.items())

def describe_outfit_with_ai(system_prompt: str, user_prompt: str, model: str):
    if not OPENAI_AVAILABLE:
        return "(Fallback) Outfit suggestion without AI description."
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        return "(No OpenAI key set) Showing basic suggestions."
    try:
        client = OpenAI(api_key=api_key)
        rsp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.8,
        )
        return (rsp.choices[0].message.content or "").strip()
    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "exceeded your current quota" in msg:
            return "(AI limit reached) Showing basic suggestions."
        return f"(AI error) {e}. Proceeding with basic description."

# ---------- Sidebar (preferences) ----------
with st.sidebar:
    st.header("Preferences")
    event = st.text_input("Event / Occasion", placeholder="wedding, date, interview…")
    vibe = st.selectbox("Style vibe", ["", "Casual", "Smart Casual", "Business", "Evening", "Streetwear"])
    gender = st.selectbox("Target section", ["", "Female", "Male", "Unisex"])
    sizes = st.text_input("Sizes (e.g., EU 38, M, 42-32)")
    colors_pref = st.text_input("Preferred colors (comma-separated)")
    budget = st.number_input("Total budget (€)", min_value=50, max_value=5000, value=300, step=10)
    model_name = st.text_input("OpenAI model (optional)", value=get_env("OPENAI_MODEL", "gpt-4o-mini"))
    photo = st.file_uploader("Optional: upload a photo (JPG/PNG/WEBP)", type=["jpg", "jpeg", "png", "webp"])

# ---------- Palette from photo (optional) ----------
palette_hex = []
if photo is not None:
    try:
        img = Image.open(photo)
        cols = extract_palette(img, k=4)
        palette_hex = [rgb_to_hex(c) for c in cols]
        st.caption("Detected palette from photo:")
        st.write(" ".join(f"`{c}`" for c in palette_hex))
        st.image(img, caption="Your photo (not uploaded anywhere)", use_container_width=True)
    except Exception as e:
        st.warning(f"Couldn't process the image: {e}")

# =============== CHAT (single block!) ===============
st.divider()
st.subheader("Ask me anything about your outfit…")

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hey! I’m your stylist friend. Tell me the occasion ✨"}
    ]

# render history
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

def offline_reply(user_text: str) -> str:
    t = (user_text or "").lower()
    if any(k in t for k in ["свидан", "dating", "date", "роман"]):
        vibe = "dating / романтичный вайб"; palette = "тёплые нейтральные, бордовый, молочный"
    elif any(k in t for k in ["интервью", "собесед", "job", "офис"]):
        vibe = "интервью / смарт-кэжуал"; palette = "серый, тёмно-синий, белый"
    elif any(k in t for k in ["вечерин", "club", "party", "ноч"]):
        vibe = "вечеринка"; palette = "чёрный, металлик, контрастные акценты"
    else:
        vibe = "ежедневный кэжуал"; palette = "базовые нейтральные + 1 акцент"
    return (
        f"Зафиксировала: **{vibe}**.\n\n"
        f"1) Верх — базовый топ/рубашка (палитра: {palette}).\n"
        f"2) Низ — посадка по фигуре (straight/slim).\n"
        f"3) Обувь — удобная, но опрятная.\n"
        f"4) Акцент — слой (пиджак/кардиган) или аксессуар.\n\n"
        f"Подскажи размер/рост/цвета и бюджет — соберу конкретные позиции и ссылки."
    )

def ai_chat_reply() -> str | None:
    if not OPENAI_AVAILABLE:
        return None
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        client = OpenAI(api_key=api_key)
        system = {"role": "system", "content":
                  "You are a warm, witty fashion girlfriend. Keep answers concise but vivid. "
                  "Ask 1 clarifying question if needed. Suggest items and explain why they fit the occasion, proportions, and palette."}
        msgs = [system] + [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages][-16:]
        resp = client.chat.completions.create(
            model=get_env("OPENAI_MODEL", "gpt-4o-mini"),
            messages=msgs,
            temperature=0.8,
            top_p=0.9,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None

# single chat_input in the whole app:
user_msg = st.chat_input("Напиши сюда: повод, бюджет, цвета, размер…")
if user_msg:
    st.session_state.messages.append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    reply = ai_chat_reply()
    if not reply:
        reply = offline_reply(user_msg)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.markdown(reply)

# ---------- Outfit Plan ----------
colors = [c.strip() for c in (colors_pref.split(",") if colors_pref else []) if c.strip()]
if palette_hex:
    colors = list(dict.fromkeys(colors + palette_hex))

queries = build_queries(event, vibe, gender, colors, sizes)
splits = budget_split(int(budget))

system_prompt = (
    "You are a warm, witty fashion girlfriend. "
    "Be concise but vivid. Explain why the pieces fit the occasion, proportions, and palette."
)

# last user text to season the plan
last_user_text = ""
for m in reversed(st.session_state.messages):
    if m["role"] == "user":
        last_user_text = m["content"]; break

user_prompt = (
    f"Occasion: {event or '—'}\n"
    f"Vibe: {vibe or '—'}\n"
    f"Gender: {gender or '—'}\n"
    f"Sizes: {sizes or '—'}\n"
    f"Colors: {', '.join(colors) or '—'}\n"
    f"Budget: {budget}€\n"
    f"User says: {last_user_text or '—'}"
)

description = describe_outfit_with_ai(system_prompt, user_prompt, model=model_name)

st.subheader("Your Outfit Plan")
st.write(description)

st.divider()
for item_name, price in splits:
    q = build_queries(event, vibe, gender, colors, sizes)[item_name][0]
    st.markdown(f"### {item_name} — ~{price}€")
    st.markdown("**Search links:** " + product_links(q))
    st.caption(f"Query: `{q}`")

st.divider()
st.caption("Note: Links go to retailers with your search terms. Apply filters (size, color) there.")
