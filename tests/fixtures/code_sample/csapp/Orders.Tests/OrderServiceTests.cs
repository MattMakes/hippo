namespace CsApp.Orders.Tests;

using CsApp.Orders;

public class OrderServiceTests
{
    [Fact]
    public void Place_totals()
    {
        new OrderService().Place(new Order());
    }
}
