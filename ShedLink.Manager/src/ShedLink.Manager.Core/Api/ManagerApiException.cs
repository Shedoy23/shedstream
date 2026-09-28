using System.Net;

namespace ShedLink.Manager.Core.Api;

public sealed class ManagerApiException : Exception
{
    public HttpStatusCode StatusCode { get; }
    public string ErrorCode { get; }

    public ManagerApiException(HttpStatusCode statusCode, string errorCode)
        : base($"Manager API request failed ({(int)statusCode}, {errorCode}).")
    {
        StatusCode = statusCode;
        ErrorCode = errorCode;
    }
}
