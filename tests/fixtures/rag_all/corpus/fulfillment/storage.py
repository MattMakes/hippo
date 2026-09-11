def reserve_stock(warehouse_id, sku, quantity):
    query = "UPDATE logistics.stock SET reserved = reserved + %s WHERE warehouse_id = %s AND sku = %s"
    return query, (quantity, warehouse_id, sku)
