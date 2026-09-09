namespace CsApp.Billing;

/// <summary>Billing totals orders and sends their invoices.</summary>
public static class Billing
{
    /// <summary>Total adds up an order's lines.</summary>
    public static int Total(Order order)
    {
        var amount = 0;
        foreach (var line in order.Lines)
        {
            amount += line;
        }

        return amount;
    }

    /// <summary>SendInvoice mails the invoice for one order.</summary>
    public static void SendInvoice(Order order)
    {
        Console.WriteLine("sending", order.Id);
    }
}
