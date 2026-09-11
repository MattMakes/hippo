def save_order(tenant_id, order_id):
    query = "INSERT INTO commerce.orders (tenant_id, order_id) VALUES (%s, %s)"
    return query, (tenant_id, order_id)
