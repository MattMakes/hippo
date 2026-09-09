namespace CsApp.Orders;

using CsApp.Billing;
using CsApp.Store;

/// <summary>
/// Keeps orders. Every order is totalled by the billing namespace, written to Postgres as one
/// row and copied into the archive collection the reporting team reads.
/// </summary>
public class OrderService : Base
{
    /// <summary>
    /// Place totals an order with billing, sends its invoice and logs the route the order took
    /// before handing back the amount the customer owes.
    /// </summary>
    public int Place(Order order)
    {
        var amount = Billing.Total(order);
        try
        {
            Billing.SendInvoice(order);
        }
        catch (OrderError e)
        {
            throw new InvalidOperationException("bad order");
        }

        this.Log("x");
        return amount;
    }

    public string Log(string message)
    {
        return message;
    }

    public void ListOpen()
    {
        db.Query("SELECT id, total FROM orders WHERE status = 'open'");
    }

    public void Save(Order order)
    {
        db.Execute("INSERT INTO orders (id, total) VALUES (@id, @total)");
        throw new OrderError();
    }

    public void Archive(Order order)
    {
        db.GetCollection<Order>("archive_orders").InsertOneAsync(order);
    }

    public void Graph()
    {
        session.RunAsync("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c");
    }
}
