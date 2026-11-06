import json
import random
from .db import connect, init_db

PRODUCTS = [
    ("AMD Ryzen 5 7600", "CPU", 3899, 3100, 14, {"socket":"AM5","tdp":65}),
    ("AMD Ryzen 7 7800X3D", "CPU", 7499, 6200, 8, {"socket":"AM5","tdp":120}),
    ("Intel Core i5-14400F", "CPU", 3299, 2700, 12, {"socket":"LGA1700","tdp":148}),
    ("MSI B650M PRO-VDH", "Motherboard", 2799, 2200, 10, {"socket":"AM5","memory_type":"DDR5","form_factor":"mATX"}),
    ("ASUS PRIME B760M-A", "Motherboard", 3199, 2550, 9, {"socket":"LGA1700","memory_type":"DDR5","form_factor":"mATX"}),
    ("Corsair Vengeance 32GB DDR5", "RAM", 1899, 1400, 20, {"memory_type":"DDR5","capacity_gb":32}),
    ("Kingston Fury 16GB DDR4", "RAM", 899, 650, 18, {"memory_type":"DDR4","capacity_gb":16}),
    ("NVIDIA RTX 4060 8GB", "GPU", 6499, 5400, 7, {"vram_gb":8,"power_w":550}),
    ("AMD Radeon RX 7700 XT", "GPU", 8999, 7600, 5, {"vram_gb":12,"power_w":700}),
    ("Samsung 990 EVO 1TB", "Storage", 1699, 1250, 22, {"capacity_gb":1000,"interface":"NVMe"}),
    ("WD Blue SN580 2TB", "Storage", 2199, 1700, 16, {"capacity_gb":2000,"interface":"NVMe"}),
    ("Fuente Corsair 650W 80+ Bronze", "PSU", 1399, 1000, 11, {"wattage":650}),
    ("Gabinete NZXT H5 Flow", "Case", 2199, 1650, 6, {"form_factor":"ATX"}),
    ("Monitor AOC 24G2 144Hz", "Monitor", 2899, 2200, 8, {"refresh_hz":144,"size_in":24}),
    ("Logitech G502 Hero", "Peripheral", 999, 650, 25, {"type":"mouse"}),
    ("Teclado mecánico Redragon", "Peripheral", 1199, 800, 17, {"type":"keyboard"}),
]


def seed_demo(force=False):
    init_db()
    with connect() as db:
        if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] and not force:
            return
        if force:
            db.executescript("DELETE FROM transaction_items; DELETE FROM transactions; DELETE FROM segments; DELETE FROM model_runs; DELETE FROM customers; DELETE FROM products;")
        for name, cat, price, cost, stock, specs in PRODUCTS:
            db.execute("INSERT INTO products(name,category,price,cost,stock,specs) VALUES(?,?,?,?,?,?)", (name,cat,price,cost,stock,json.dumps(specs)))
        first = ["Ana López","Carlos Méndez","Sofía Ramírez","Diego Torres","Valeria Cruz","Luis Herrera","Mariana Flores","Jorge Castillo","Camila Reyes","Andrés Vega","Fernanda Ortiz","Pablo Navarro","Daniela Ríos","Miguel Soto","Renata Aguilar","Emilio Campos","Lucía Morales","Rodrigo Silva","Paola Fuentes","Mateo Luna"]
        jobs = ["Estudiante","Diseñador","Desarrollador","Oficinista"]
        rng = random.Random(41)
        for i, name in enumerate(first):
            db.execute("INSERT INTO customers(name,email,age,occupation,budget) VALUES(?,?,?,?,?)", (name,f"cliente{i+1}@demo.clavel.local",rng.randint(18,48),jobs[i%4],rng.choice([8000,12000,18000,25000,35000])))
        # Distinct purchasing profiles: gaming, productivity and peripherals/storage.
        profiles = [[1,3,5,7,9,11,12,13], [0,3,5,7,9,11], [2,4,6,9,10,11], [14,15,9,5,13]]
        for cid in range(1, 21):
            profile = profiles[(cid-1)//5]
            for _ in range(rng.randint(2,5)):
                tx = db.execute("INSERT INTO transactions(customer_id) VALUES(?)",(cid,)).lastrowid
                chosen = rng.sample(profile, k=min(rng.randint(1,3),len(profile)))
                for pidx in chosen:
                    prod = db.execute("SELECT id,price,stock FROM products WHERE id=?",(pidx+1,)).fetchone()
                    qty = 1 if pidx not in (5,9,10,14,15) else rng.randint(1,2)
                    db.execute("INSERT INTO transaction_items(transaction_id,product_id,quantity,unit_price) VALUES(?,?,?,?)",(tx,prod[0],qty,prod[1]))
                    db.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?",(qty,prod[0]))
