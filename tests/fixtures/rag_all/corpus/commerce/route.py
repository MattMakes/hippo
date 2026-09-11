from fastapi import FastAPI
from .storage import save_order
app = FastAPI()

def create_order(tenant_id: str, order_id: str):
    return save_order(tenant_id, order_id)

app.post("/billing/orders")(create_order)
