CREATE SCHEMA logistics;
CREATE TABLE logistics.stock (warehouse_id UUID NOT NULL, sku TEXT NOT NULL, reserved INTEGER NOT NULL, PRIMARY KEY (warehouse_id, sku));
CREATE TABLE logistics.allocations (allocation_id UUID PRIMARY KEY, warehouse_id UUID NOT NULL, sku TEXT NOT NULL, quantity INTEGER CHECK (quantity > 0), FOREIGN KEY (warehouse_id, sku) REFERENCES logistics.stock(warehouse_id, sku));
CREATE VIEW logistics.available_stock AS SELECT warehouse_id, sku, reserved FROM logistics.stock;
