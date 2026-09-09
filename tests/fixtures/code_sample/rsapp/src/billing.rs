//! Billing helpers.

pub fn total(order: &Order) -> i64 {
    order.lines.iter().sum()
}

pub fn send_invoice(order: &Order) {
    println!("sending {}", order.id);
}
