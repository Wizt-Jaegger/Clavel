import os
import tempfile
from fastapi.testclient import TestClient

# Isolate the test database before importing the application.
fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["CLAVEL_DB"] = db_path
from app.main import app
from app.db import connect
from app.seed import seed_demo

seed_demo()
client = TestClient(app)

def test_dashboard_and_seed():
    r=client.get("/")
    assert r.status_code==200
    assert "Clavel" in r.text
    assert client.get("/api/customers").json()
    assert client.get("/api/products").json()

def test_purchase_updates_stock_and_transaction():
    customer=client.get("/api/customers").json()[0]
    product=next(p for p in client.get("/api/products").json() if p["stock"]>0)
    before=product["stock"]
    r=client.post("/api/purchases",json={"customer_id":customer["id"],"items":[{"product_id":product["id"],"quantity":1}]})
    assert r.status_code==201
    after=next(p for p in client.get("/api/products").json() if p["id"]==product["id"])["stock"]
    assert after==before-1
    assert client.get("/api/transactions").status_code==200

def test_segmentation_and_recommendations():
    result=client.post("/api/segments/run").json()
    assert result["status"]=="ok"
    customer=client.get("/api/customers").json()[0]
    recs=client.get(f"/api/recommendations/{customer['id']}")
    assert recs.status_code==200
    assert "recommendations" in recs.json()

def test_stock_validation():
    customer=client.get("/api/customers").json()[0]
    product=client.get("/api/products").json()[0]
    r=client.post("/api/purchases",json={"customer_id":customer["id"],"items":[{"product_id":product["id"],"quantity":99999}]})
    assert r.status_code==409
