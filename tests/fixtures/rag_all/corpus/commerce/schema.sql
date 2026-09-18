CREATE SCHEMA commerce;
CREATE TABLE commerce.customers (tenant_id UUID NOT NULL, customer_id UUID NOT NULL, PRIMARY KEY (tenant_id, customer_id));
CREATE TABLE commerce.orders (tenant_id UUID NOT NULL, order_id UUID NOT NULL, customer_id UUID, PRIMARY KEY (tenant_id, order_id), FOREIGN KEY (tenant_id, customer_id) REFERENCES commerce.customers(tenant_id, customer_id));
CREATE VIEW commerce.order_keys AS SELECT tenant_id, order_id FROM commerce.orders;
