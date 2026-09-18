from fastapi import FastAPI
app = FastAPI()

def list_orders():
    return []

app.get("/tracking/orders")(list_orders)
