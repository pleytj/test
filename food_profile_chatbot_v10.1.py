import json
import streamlit as st
from openai import OpenAI
import requests
from PIL import Image
import pyzxing
import streamlit.components.v1 as components
import io
import base64

# ─── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="🥗 FoodScanalyzer", layout="wide")
st.title("🥗 FoodScanalyzer")

WEBHOOK_URL = "https://intelligentsia.app.n8n.cloud/webhook-test/e8ba65ef-ddd4-45f8-a3e8-7992c4fb58e2"

# ─── API SETUP ─────────────────────────────────────────────────────────────────
if "api" in st.secrets and "key" in st.secrets["api"]:
    api_key = st.secrets["api"]["key"]
    client = OpenAI(api_key=api_key)
else:
    st.stop("❌ Missing OpenAI key in secrets.toml")

# ─── SESSION STATE SETUP ───────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "system",
            "content": (
                "You are a dietary assistant that helps users build a structured food profile. "
                "Ask friendly follow-up questions to understand their allergies, diet preferences, dislikes, and health goals. "
                "When ready, output ONLY the structured food profile as a JSON object with these 4 fields: "
                "`allergies`, `diet`, `dislikes`, `health_goals`. All values should be arrays of strings. Keep it clean and API-ready."
            )
        },
        {
            "role": "assistant",
            "content": "Hi! 👋 Let's build your food profile. Do you have any allergies I should know about?"
        }
    ]

if "parsed_profile" not in st.session_state:
    st.session_state.parsed_profile = None

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

# ─── OPTIONAL TEST PROFILE SELECTION ───────────────────────────────────────────
profile_options = {
    "None": None,
    "Default Extensive Test Profile": {
        "allergies": ["gluten", "soy"],
        "diet": ["keto", "vegan"],
        "dislikes": ["shellfish", "eggplant", "mushroom","cheese"],
        "health_goals": ["low carb", "low sugar", "low fat", "low salt"]
    },
    "Profile A – Peanut, Vegan, Low Sugar": {
        "allergies": ["peanut"],
        "diet": ["vegan"],
        "dislikes": [],
        "health_goals": ["low sugar"]
    },
    "Profile B – Milk, Gluten, Keto, Low Fat, cafestol": {
        "allergies": ["milk", "gluten","cafestol"],
        "diet": ["keto"],
        "dislikes": [],
        "health_goals": ["low fat"]
    },
    "Profile C – Intermittent fasting": {
        "allergies": [],
        "diet": [],
        "dislikes": [],
        "health_goals": ["Intermittent fasting"]
    },
        "Profile D – No Restrictions": {
        "allergies": [],
        "diet": [],
        "dislikes": [],
        "health_goals": []
    }
}

selected_option = st.selectbox("🧪 Select test profile (or 'None' to disable)", list(profile_options.keys()))

if selected_option != "None":
    st.session_state.parsed_profile = profile_options[selected_option]
    st.success(f"✅ {selected_option} loaded.")

# ─── TABS ───────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["🤖 Build Profile", "📦 Scan Product"])

# === TAB 1: Chatbot Food Profile Builder ===
with tab1:
    st.header("Step 1: Chat to Build Your Food Profile")

    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    prompt = st.chat_input("Your answer...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.spinner("Thinking..."):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=st.session_state.messages,
                temperature=0.6
            )
            reply = response.choices[0].message.content
            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)

            if "```json" in reply:
                try:
                    json_block = reply.split("```json")[1].split("```")[0]
                    parsed = json.loads(json_block)
                    st.session_state.parsed_profile = parsed
                    st.success("✅ Profile detected and parsed successfully!")

                    if st.button("Submit to FoodScanalyzer"):
                        try:
                            r = requests.post(WEBHOOK_URL, json={"user_profile": parsed})
                            response_data = r.json()
                            st.success(f"✅ Submitted! Status code: {r.status_code}")
                            if "message" in response_data:
                                st.markdown("### 🧾 Food Profile Feedback")
                                st.markdown(f"```{response_data['message']}```")
                            else:
                                st.info("No message returned from n8n.")
                        except Exception as e:
                            st.error(f"❌ Submission failed: {e}")
                except Exception as e:
                    st.warning(f"⚠️ Could not parse JSON: {e}")

# === TAB 2: Barcode Scanner ===

# === TAB 2: Barcode Scanner ===================================================
with tab2:
    st.header("📦 Step 2: Scan or Upload a Product Barcode")

    reader = pyzxing.BarCodeReader()

    # ── Guard: profile required ──────────────────────────────────────────────
    if not st.session_state.get("parsed_profile"):
        st.error("❌ No stored profile found. Build one first in the chatbot.")
        st.stop()

    # ── State helpers ────────────────────────────────────────────────────────
    st.session_state.setdefault("scanned_barcode", "")
    st.session_state.setdefault("product_info", {})     # {'barcode','found','name','img'}
    st.session_state.setdefault("label_photos", [])     # list[UploadedFile]

    # ── Scan method ──────────────────────────────────────────────────────────
    scan_mode = st.radio("Choose scan method:", ["Upload image", "Use live camera"])
    detected_barcode = ""

    # --- 1) File upload ------------------------------------------------------
    if scan_mode == "Upload image":
        up = st.file_uploader("Upload barcode image (JPG/PNG)", ["jpg", "jpeg", "png"])
        if up:
            tmp = "temp_barcode.jpg"
            with open(tmp, "wb") as f:
                f.write(up.read())
            res = reader.decode(tmp)
            if res:
                raw = res[0].get("raw")
                detected_barcode = raw.decode() if isinstance(raw, bytes) else raw
                st.success("✅ Barcode detected!")
            else:
                st.warning("⚠️ No barcode detected. Try a clearer photo.")

    # --- 2) Live camera ------------------------------------------------------
    elif scan_mode == "Use live camera":
        st.info("📷 Point your webcam/phone at the barcode.")
        components.html(
            """
            <script src="https://unpkg.com/html5-qrcode"></script>
            <div id="reader" style="width:300px"></div>
            <script>
              function onScanSuccess(code){
                const i = window.parent.document.querySelector(
                  'input[aria-label="📎 Barcode scanned (or paste manually)"]');
                if(i && i.value !== code){
                  i.value = code; i.dispatchEvent(new Event('input',{bubbles:true}));
                  document.getElementById("reader").style.display="none";
                }
              }
              new Html5QrcodeScanner("reader",{fps:10,qrbox:250}).render(onScanSuccess);
            </script>
            """,
            height=400
        )

    # ── Persist barcode & reset caches if new --------------------------------
    if detected_barcode:
        st.session_state.scanned_barcode = detected_barcode.strip()
        st.session_state.product_info = {}
        st.session_state.label_photos = []

    bc = st.session_state.scanned_barcode
    product_name = ""

    # ── Lookup in OpenFoodFacts once per code --------------------------------
    info = st.session_state.product_info
    if bc and info.get("barcode") != bc:
        try:
            r = requests.get(
                f"https://world.openfoodfacts.org/api/v0/product/{bc}.json", timeout=10
            )
            if r.status_code == 200 and r.json().get("status") == 1:
                p = r.json()["product"]
                info = {
                    "barcode": bc,
                    "found": True,
                    "name": p.get("product_name", "Unknown product"),
                    "img":  p.get("image_front_thumb_url")
                            or p.get("image_small_url")
                            or p.get("image_front_url")
                }
            else:
                info = {"barcode": bc, "found": False, "name": "", "img": ""}
        except Exception:
            info = {"barcode": bc, "found": False, "name": "", "img": ""}
        st.session_state.product_info = info

    # ── UI: show product or prompt for photos --------------------------------
    if bc:
        if info["found"]:
            product_name = info["name"]
            st.success(f"✅ Product found: **{product_name}**")
            cols = st.columns(3)

            # 1. Product image
            if info["img"]:
                with cols[0]:
                    st.image(info["img"], caption="Product Image", width=200)
            else:
                with cols[0]:
                    st.markdown("❌ No product image found.")

            # 2. Label image
            label_img_url = p.get("image_ingredients_thumb_url") or p.get("image_ingredients_url")
            if label_img_url:
                with cols[1]:
                    st.image(label_img_url, caption="Label Image", width=200)
            else:
                with cols[1]:
                    st.markdown("❌ No label image found.")

            # 3. Nutrition table image
            nutri_img_url = p.get("image_nutrition_thumb_url") or p.get("image_nutrition_url")
            if nutri_img_url:
                with cols[2]:
                    st.image(nutri_img_url, caption="Nutrition Table", width=200)
            else:
                with cols[2]:
                    st.markdown("❌ No nutrition image found.")
        else:
            st.warning("⚠️ Barcode not in OpenFoodFacts.")
            st.markdown("### 📸 Take up to 3 clear label photos")
            if len(st.session_state.label_photos) < 3:
                shot = st.camera_input(
                    f"Photo {len(st.session_state.label_photos)+1}/3"
                )
                if shot:
                    st.session_state.label_photos.append(shot)
                    st.success("📸 Photo captured!")
            for p in st.session_state.label_photos:
                st.image(p, width=150)

        st.markdown("### 📋 Scanned barcode (copy-paste if needed)")
        st.code(bc, language="text")

    # ── Manual entry ---------------------------------------------------------
    barcode_input = st.text_input("📎 Barcode scanned (or paste manually)", "")

    # ── Submit to n8n --------------------------------------------------------
    if st.button("Submit Profile + Barcode"):
        barcode_to_send = barcode_input.strip() or bc
        if not barcode_to_send:
            st.warning("⚠️ Scan or paste a barcode first.")
            st.stop()

        payload = {
            "barcode": barcode_to_send,
            "product_name": product_name,
            "user_profile": st.session_state.parsed_profile,
        }
        if st.session_state.label_photos:
            img = Image.open(st.session_state.label_photos[0])
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            payload["label_photo"] = base64.b64encode(buf.getvalue()).decode()

        # --- n8n request -----------------------------------------------------
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=30)
            data = resp.json()
        except Exception as e:
            st.error(f"❌ Submission failed: {e}")
            st.stop()

        # unwrap list-of-one
                # ── Unwrap list-of-one -------------------------------------------------
        if isinstance(data, list) and data:
            data = data[0]

        # ── Helper: walk nested dicts/lists looking for the analyzer object ---
        def find_content(obj):
            if isinstance(obj, dict):
                if "score" in obj and "flags" in obj:  # very likely the analyzer payload
                    return obj
                for v in obj.values():
                    found = find_content(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = find_content(item)
                    if found:
                        return found
            return {}

        content  = find_content(data)
        coaching = ""
        # try to locate a coaching_message sibling if present
        if isinstance(data, dict):
            coaching = data.get("coaching_message",
                        data.get("message", {}).get("coaching_message", ""))

        # fallbacks to avoid KeyError
        alternatives = content.get("alternatives",
                      data.get("alternatives", []))

        # ── Build chat bubbles ----------------------------------------------
        st.session_state.chat_messages = [
            ("user", f"I scanned barcode **{barcode_to_send}**", "🧍")
        ]

        score   = content.get("score", 0)
        flags   = content.get("flags", [])
        summary = content.get("summary", "")
        expl    = content.get("explained", [])
        tip     = content.get("suggestion", "")
        alts    = content.get("alternatives",
                   data.get("alternatives", []))

        emoji = "🔴" if score < 40 else ("🟠" if score < 70 else "🟢")
        analysis = f"**Score:** {emoji} {score}/100\n\n"
        if summary:
            analysis += f"**Summary:** {summary}\n\n"
        if flags:
            analysis += "**Flags:**\n" + "\n".join(
                f"- {f.replace('_',' ').capitalize()}" for f in flags
            ) + "\n\n"
        if tip:
            analysis += f"**Tip:** {tip}\n\n"
        if expl:
            analysis += "**Explanation:**\n" + (
                "\n".join(f"{i+1}. {line}" for i, line in enumerate(expl))
                if isinstance(expl, list) else expl
            )

        st.session_state.chat_messages.append(("assistant", analysis, "🧪"))

        if alts:
            alt_txt = "**✅ Suggested Alternatives:**\n" + "\n".join(
                f"- **{a['name']}**: {a['reason']}" for a in alts
            )
            st.session_state.chat_messages.append(("assistant", alt_txt, "✅"))

        if coaching:
            st.session_state.chat_messages.append(("assistant", coaching, "🍏"))

    # ── Render chat history ---------------------------------------------------
    for role, msg, avatar in st.session_state.get("chat_messages", []):
        with st.chat_message(role, avatar=avatar):
            st.markdown(msg, unsafe_allow_html=True)