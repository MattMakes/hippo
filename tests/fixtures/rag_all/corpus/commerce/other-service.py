from fastapi import FastAPI
app = FastAPI()

def list_orders():
    return []

app.get("/checkout/orders")(list_orders)
