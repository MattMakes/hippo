use crate::billing::{send_invoice as invoice, total};
use crate::store::{Base, OrderError};

/// Keeps orders. The crate stores every order in Postgres and mails each invoice to the buyer.
///
/// Second paragraph, not part of the first.
pub struct OrderService {
    db: Db,
}

impl Base for OrderService {
    fn log(&self, message: &str) -> String {
        message.to_string()
    }
}

impl OrderService {
    /// Place an order: total it with billing, send the invoice and log the route the order took.
    pub fn place(&self, order: &Order) -> Result<i64, OrderError> {
        let amount = total(order);
        invoice(order);
        self.log("x");
        Ok(amount)
    }

    pub fn list_open(&self) {
        sqlx::query("SELECT id, total FROM orders WHERE status = 'open'");
    }

    pub fn save(&self, order: &Order) -> Result<(), OrderError> {
        sqlx::query("INSERT INTO orders (id, total) VALUES ($1, $2)");
        Err(OrderError)
    }

    pub fn archive(&self, order: &Order) {
        self.db.collection::<Order>("archive_orders").insert_one(order, None);
    }

    pub fn graph(&self) {
        neo4rs::query("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn place_totals() {
        super::OrderService::new().place(&Order::default());
    }
}
