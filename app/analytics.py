import json
import uuid
import numpy as np
import pandas as pd
from sklearn.cluster import Birch
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer, StandardScaler
from .db import connect

MIN_CUSTOMERS = 6


def run_segmentation():
    with connect() as db:
        customers = pd.read_sql_query("SELECT id, age, budget, occupation FROM customers ORDER BY id", db)
        purchases = pd.read_sql_query("SELECT t.customer_id, p.category, SUM(i.quantity) qty, SUM(i.quantity*i.unit_price) spend FROM transactions t JOIN transaction_items i ON i.transaction_id=t.id JOIN products p ON p.id=i.product_id GROUP BY t.customer_id,p.category", db)
    if len(customers) < MIN_CUSTOMERS or purchases.empty:
        return {"status":"insufficient_data","message":f"Se necesitan al menos {MIN_CUSTOMERS} clientes y compras registradas.","customers":len(customers),"segments":0}
    pivot = purchases.pivot_table(index="customer_id",columns="category",values="qty",aggfunc="sum",fill_value=0)
    pivot = pivot.reindex(customers.id,fill_value=0)
    features = customers.set_index("id")[["age","budget"]].fillna(0).copy()
    features["spend"] = purchases.groupby("customer_id").spend.sum().reindex(features.index).fillna(0)
    features["purchase_count"] = purchases.groupby("customer_id").qty.sum().reindex(features.index).fillna(0)
    features = pd.concat([features, pivot], axis=1)
    x = StandardScaler().fit_transform(features.astype(float))
    # SVD is used only when dimensionality permits; small demo datasets remain valid.
    if x.shape[1] > 2 and min(x.shape) > 1:
        x = TruncatedSVD(n_components=min( min(8, x.shape[1]-1), x.shape[0]-1), random_state=42).fit_transform(x)
    x = Normalizer().fit_transform(x)
    n_clusters = min(max(2, round(len(customers) ** 0.5)), len(customers)-1)
    model = Birch(threshold=0.65, n_clusters=n_clusters)
    labels = model.fit_predict(x)
    version = str(uuid.uuid4())[:8]
    with connect() as db:
        db.execute("DELETE FROM segments")
        db.executemany("INSERT INTO segments(customer_id,label,model_version) VALUES(?,?,?)", [(int(cid),int(label),version) for cid,label in zip(customers.id,labels)])
        db.execute("INSERT INTO model_runs(model_version,customer_count,segment_count,details) VALUES(?,?,?,?)",(version,len(customers),len(set(labels)),json.dumps({"pipeline":"StandardScaler -> TruncatedSVD (when applicable) -> L2 Normalizer -> BIRCH","threshold":0.65,"n_clusters":n_clusters})))
    return {"status":"ok","customers":len(customers),"segments":len(set(labels)),"model_version":version,"pipeline":"StandardScaler + TruncatedSVD + L2 Normalizer + BIRCH"}
