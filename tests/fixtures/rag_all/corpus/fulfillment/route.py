from fastapi import FastAPI
from .storage import reserve_stock
app = FastAPI()

def allocate_shipment(warehouse_id: str, sku: str, quantity: int):
    return reserve_stock(warehouse_id, sku, quantity)

app.put("/shipping/allocations")(allocate_shipment)
