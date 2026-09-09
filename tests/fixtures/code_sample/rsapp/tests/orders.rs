use rsapp::orders::OrderService;

#[test]
fn test_place() {
    OrderService::new().place(&Order::default());
}
