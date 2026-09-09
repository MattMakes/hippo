namespace CsApp.Store;

/// <summary>A tiny base type every service derives from.</summary>
public class Base
{
    /// <summary>Log hands back the message it was given.</summary>
    public string Log(string message)
    {
        return message;
    }
}

/// <summary>OrderError is what an order throws when it will not save.</summary>
public class OrderError : Exception
{
}
