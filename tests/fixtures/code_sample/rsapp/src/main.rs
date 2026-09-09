use rsapp::orders::OrderService;

fn main() {
    let service = OrderService::new();
    service.place(&Order::default());
}
