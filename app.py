import os, json, time, requests
from flask import Flask, request, jsonify
from flask_cors import CORS

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
VTEX_BASE_URL = os.getenv("VTEX_BASE_URL", "https://www.carrefour.com.ar")
DEFAULT_SELLER = os.getenv("DEFAULT_SELLER", "1")
DEFAULT_SC = os.getenv("DEFAULT_SC", "1")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": [
    "https://www.carrefour.com.ar",
    "https://carrefour.com.ar"
]}})

def llm_route(user_text):
    prompt = (
        "Devolveme SOLO un JSON con keys intent, query, reply.\n"
        "Si el usuario pide productos, intent='products' y 'query' con el término buscado.\n"
        "Si no, intent='smalltalk' y reply con un texto corto útil.\n"
        "Usuario: " + user_text
    )
    try:
        headers = {
            "Authorization": "Bearer " + OPENROUTER_API_KEY,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://carrefour.com.ar",
            "X-Title": "Carrefour Shopping Assistant"
        }
        data = {
            "model": "openrouter/cypher-alpha:free",
            "messages": [{"role":"user","content":prompt}],
            "temperature": 0.2
        }
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers=headers, json=data, timeout=35)
        txt = r.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(txt)
            if "intent" in parsed:
                return parsed
        except:
            pass
    except Exception as e:
        print("LLM error:", e)
    return {"intent":"smalltalk","query":"","reply":"Estoy acá para ayudarte. Contame qué buscás 👀"}

def vtex_search(term, seller_id, sc):
    url = VTEX_BASE_URL + "/api/catalog_system/pub/products/search/" + requests.utils.quote(term)
    res = requests.get(url, timeout=20)
    res.raise_for_status()
    data = res.json()

    results = []
    for prod in data:
        name = prod.get("productName", "")
        link_text = prod.get("linkText", "")
        url_pdp = VTEX_BASE_URL + "/" + link_text + "/p" if link_text else VTEX_BASE_URL

        sku = None
        price = None
        image_url = None

        items = prod.get("items", []) or []
        for it in items:
            images = it.get("images", []) or []
            if images:
                image_url = images[0].get("imageUrl")
            sellers = it.get("sellers", []) or []
            for s in sellers:
                sid = s.get("sellerId")
                offer = s.get("commertialOffer") or {}
                p = offer.get("Price")
                if sid == seller_id and p and p > 0:
                    sku = it.get("itemId")
                    price = p
                    break
            if sku and price:
                break

        if not (sku and price):
            for it in items:
                sellers = it.get("sellers", []) or []
                for s in sellers:
                    offer = s.get("commertialOffer") or {}
                    p = offer.get("Price")
                    if p and p > 0:
                        sku = it.get("itemId")
                        price = p
                        images = it.get("images", []) or []
                        if images and not image_url:
                            image_url = images[0].get("imageUrl")
                        break
                if sku and price:
                    break

        if sku and price:
            results.append({
                "name": name,
                "imageUrl": image_url,
                "price": float(price),
                "url": url_pdp,
                "sku": str(sku),
                "addToCart": VTEX_BASE_URL + "/checkout/cart/add/?sku=" + str(sku) + "&qty=1&seller=" + seller_id + "&sc=" + sc
            })
    return results[:10]

@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True) or {}
    message = (body.get("message") or "").strip()
    ctx = body.get("context") or {}
    seller_id = (ctx.get("sellerId") or DEFAULT_SELLER)
    sc = (ctx.get("sc") or DEFAULT_SC)

    if not message:
        return jsonify({"type":"text","message":"¿Qué estás buscando hoy?"})

    route = llm_route(message)
    if route.get("intent") == "products":
        term = route.get("query") or message
        prods = vtex_search(term, seller_id, sc)
        if prods:
            return jsonify({"type":"products","message":"Te dejo opciones que encontré:","products": prods})
        else:
            return jsonify({"type":"text","message":"No encontré resultados. Probá con otro término 👀"})
    return jsonify({"type":"text","message": route.get("reply") or "Decime un producto o categoría 😉"})

@app.route("/", methods=["GET"])
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
