import json
from .db import rows, one


def compatible(customer_id, product):
    # Infer only constraints explicitly present in the customer's previous purchases.
    specs = json.loads(product.get("specs") or "{}")
    purchased = rows("SELECT DISTINCT p.specs FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id JOIN products p ON p.id=i.product_id WHERE t.customer_id=?",(customer_id,))
    prior = [json.loads(p["specs"] or "{}") for p in purchased]
    sockets = {p["socket"] for p in prior if p.get("socket")}
    memory = {p["memory_type"] for p in prior if p.get("memory_type")}
    if specs.get("socket") and sockets and specs["socket"] not in sockets:
        return False, "Socket distinto al de componentes comprados anteriormente"
    if specs.get("memory_type") and memory and specs["memory_type"] not in memory:
        return False, "Tipo de memoria distinto al de componentes comprados anteriormente"
    return True, "Sin incompatibilidad conocida; validar plataforma completa antes de comprar"


def get_recommendations(customer_id, limit=5):
    customer = one("SELECT id,name FROM customers WHERE id=?",(customer_id,))
    if not customer:
        return None
    segment = one("SELECT label FROM segments WHERE customer_id=?",(customer_id,))
    if segment:
        query = """SELECT p.*, SUM(i.quantity) popularity FROM products p JOIN transaction_items i ON i.product_id=p.id JOIN transactions t ON t.id=i.transaction_id JOIN segments s ON s.customer_id=t.customer_id WHERE s.label=? AND p.stock>0 AND p.id NOT IN (SELECT i2.product_id FROM transactions t2 JOIN transaction_items i2 ON i2.transaction_id=t2.id WHERE t2.customer_id=?) GROUP BY p.id ORDER BY popularity DESC LIMIT ?"""
        products = rows(query,(segment["label"],customer_id,limit))
        source = "popularidad del segmento"
    else:
        query = """SELECT p.*, SUM(i.quantity) popularity FROM products p JOIN transaction_items i ON i.product_id=p.id WHERE p.stock>0 AND p.id NOT IN (SELECT i2.product_id FROM transactions t2 JOIN transaction_items i2 ON i2.transaction_id=t2.id WHERE t2.customer_id=?) GROUP BY p.id ORDER BY popularity DESC LIMIT ?"""
        products = rows(query,(customer_id,limit))
        source = "popularidad global"
    result=[]
    for p in products:
        ok, note = compatible(customer_id,p)
        if ok:
            result.append({**p,"specs":json.loads(p["specs"] or "{}"),"compatibility_note":note})
    return {"customer":customer,"segment":segment["label"] if segment else None,"source":source,"recommendations":result}
