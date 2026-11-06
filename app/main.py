import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from .db import init_db, connect, rows, one
from .seed import seed_demo
from .analytics import run_segmentation
from .recommendations import get_recommendations

app = FastAPI(title="Clavel MVP", version="0.1.0", description="Inteligencia comercial local para tiendas de hardware")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

@app.on_event("startup")
def startup():
    init_db()
    seed_demo()

class CustomerIn(BaseModel):
    name: str = Field(min_length=2)
    email: str | None = None
    age: int | None = Field(default=None, ge=1, le=120)
    occupation: str | None = None
    budget: float = Field(default=0, ge=0)

class ProductIn(BaseModel):
    name: str
    category: str
    price: float = Field(ge=0)
    cost: float = Field(default=0, ge=0)
    stock: int = Field(default=0, ge=0)
    specs: dict = {}

class ItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)

class PurchaseIn(BaseModel):
    customer_id: int
    items: list[ItemIn] = Field(min_length=1)

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    stats = {
        "customers": one("SELECT COUNT(*) n FROM customers")["n"],
        "products": one("SELECT COUNT(*) n FROM products")["n"],
        "transactions": one("SELECT COUNT(*) n FROM transactions")["n"],
        "revenue": one("SELECT COALESCE(SUM(quantity*unit_price),0) n FROM transaction_items")["n"],
    }
    popular = rows("SELECT p.name,p.category,SUM(i.quantity) sold FROM products p JOIN transaction_items i ON i.product_id=p.id GROUP BY p.id ORDER BY sold DESC LIMIT 5")
    distribution = rows("SELECT label,COUNT(*) customers FROM segments GROUP BY label ORDER BY label")
    customers = rows("SELECT c.*,s.label segment FROM customers c LEFT JOIN segments s ON s.customer_id=c.id ORDER BY c.name")
    example = get_recommendations(customers[0]["id"]) if customers else None
    return templates.TemplateResponse("index.html", {"request":request,"stats":stats,"popular":popular,"distribution":distribution,"customers":customers,"example":example})

@app.get("/api/health")
def health(): return {"status":"ok"}

@app.get("/api/products")
def list_products(): return rows("SELECT * FROM products ORDER BY category,name")

@app.post("/api/products", status_code=201)
def add_product(p: ProductIn):
    with connect() as db:
        cur=db.execute("INSERT INTO products(name,category,price,cost,stock,specs) VALUES(?,?,?,?,?,?)",(p.name,p.category,p.price,p.cost,p.stock,json.dumps(p.specs)))
        return {"id":cur.lastrowid,"message":"Producto creado"}

@app.put("/api/products/{product_id}")
def update_product(product_id:int,p:ProductIn):
    with connect() as db:
        cur=db.execute("UPDATE products SET name=?,category=?,price=?,cost=?,stock=?,specs=? WHERE id=?",(p.name,p.category,p.price,p.cost,p.stock,json.dumps(p.specs),product_id))
        if not cur.rowcount: raise HTTPException(404,"Producto no encontrado")
    return {"message":"Producto actualizado"}

@app.delete("/api/products/{product_id}")
def delete_product(product_id:int):
    with connect() as db:
        try: cur=db.execute("DELETE FROM products WHERE id=?",(product_id,))
        except Exception: raise HTTPException(409,"No se puede eliminar: el producto tiene ventas asociadas")
        if not cur.rowcount: raise HTTPException(404,"Producto no encontrado")
    return {"message":"Producto eliminado"}

@app.get("/api/customers")
def list_customers(): return rows("SELECT c.*,s.label segment FROM customers c LEFT JOIN segments s ON s.customer_id=c.id ORDER BY c.name")

@app.post("/api/customers",status_code=201)
def add_customer(c:CustomerIn):
    try:
        with connect() as db:
            cur=db.execute("INSERT INTO customers(name,email,age,occupation,budget) VALUES(?,?,?,?,?)",(c.name,c.email,c.age,c.occupation,c.budget))
            return {"id":cur.lastrowid,"message":"Cliente registrado"}
    except Exception as e: raise HTTPException(409,"No se pudo registrar; revisa que el correo no esté duplicado") from e

@app.get("/api/transactions")
def list_transactions(): return rows("SELECT t.id,t.customer_id,c.name customer,t.created_at,COUNT(i.id) lines,SUM(i.quantity*i.unit_price) total FROM transactions t JOIN customers c ON c.id=t.customer_id JOIN transaction_items i ON i.transaction_id=t.id GROUP BY t.id ORDER BY t.id DESC")

@app.post("/api/purchases",status_code=201)
def purchase(p:PurchaseIn):
    if not one("SELECT id FROM customers WHERE id=?",(p.customer_id,)): raise HTTPException(404,"Cliente no encontrado")
    with connect() as db:
        checked=[]
        for item in p.items:
            product=db.execute("SELECT id,price,stock FROM products WHERE id=?",(item.product_id,)).fetchone()
            if not product: raise HTTPException(404,f"Producto {item.product_id} no encontrado")
            if product["stock"] < item.quantity: raise HTTPException(409,f"Stock insuficiente para producto {item.product_id}")
            checked.append((item,product))
        tx=db.execute("INSERT INTO transactions(customer_id) VALUES(?)",(p.customer_id,)).lastrowid
        for item,product in checked:
            db.execute("INSERT INTO transaction_items(transaction_id,product_id,quantity,unit_price) VALUES(?,?,?,?)",(tx,item.product_id,item.quantity,product["price"]))
            db.execute("UPDATE products SET stock=stock-? WHERE id=?",(item.quantity,item.product_id))
    return {"transaction_id":tx,"message":"Compra registrada y stock actualizado"}

@app.post("/api/segments/run")
def segment(): return run_segmentation()

@app.get("/api/recommendations/{customer_id}")
def recommendations(customer_id:int):
    result=get_recommendations(customer_id)
    if result is None: raise HTTPException(404,"Cliente no encontrado")
    return result

@app.post("/api/demo/reset")
def reset_demo():
    seed_demo(force=True)
    return {"message":"Base de demostración restaurada"}
