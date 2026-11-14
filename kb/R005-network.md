# R005 — DNS, connection and TLS failures

**What the tool found:** requests that never got an HTTP response because something failed below HTTP. The browser recorded an error code instead of a status. Chrome writes codes like `net::ERR_NAME_NOT_RESOLVED`; Firefox writes `NS_ERROR_UNKNOWN_HOST` or `SEC_ERROR_EXPIRED_CERTIFICATE`.

These are almost never bugs in the web app itself. They are about the network path between the customer and the server.

## By category

| Category | Typical codes | What it means | First step |
|---|---|---|---|
| **DNS** | `ERR_NAME_NOT_RESOLVED`, `NS_ERROR_UNKNOWN_HOST` | The hostname could not be looked up. | Check the spelling, then `nslookup <host>`. VPNs and corporate DNS filters are frequent causes. |
| **TLS / certificate** | `ERR_CERT_DATE_INVALID`, `ERR_CERT_AUTHORITY_INVALID`, `ERR_CERT_COMMON_NAME_INVALID`, `SEC_ERROR_*`, `SSL_ERROR_*` | The secure connection was refused: an expired certificate, a certificate for another hostname, or one from an untrusted issuer. | Open the host in a browser and inspect the certificate. If it is fine for you but not for the customer, a proxy or antivirus is re-signing their traffic, or their clock is wrong. |
| **Refused** | `ERR_CONNECTION_REFUSED` | Nothing is listening on that host and port. | Is the service up? Is the port right? |
| **Timeout** | `ERR_CONNECTION_TIMED_OUT`, `ERR_TIMED_OUT` | No answer at all. | A firewall dropping packets, or the server is down or overloaded. |
| **Reset** | `ERR_CONNECTION_RESET`, `ERR_CONNECTION_CLOSED` | The connection was cut. | Often a proxy, firewall or load balancer. Try another network. |
| **Offline** | `ERR_INTERNET_DISCONNECTED`, `ERR_NETWORK_CHANGED` | The device lost its connection (Wi-Fi switch, VPN reconnect). | Retry on a stable network. |
| **Proxy** | `ERR_PROXY_CONNECTION_FAILED`, `ERR_TUNNEL_CONNECTION_FAILED` | The configured proxy failed. | Check proxy or PAC settings on the device. |
| **Broken response** | `ERR_HTTP2_PROTOCOL_ERROR`, `ERR_INCOMPLETE_CHUNKED_ENCODING`, `ERR_EMPTY_RESPONSE` | The response started but was cut off or malformed. | Check CDN and server logs for crashes mid-response; try without the VPN or proxy. |
| **Browser policy** | `ERR_BLOCKED_BY_RESPONSE`, `ERR_BLOCKED_BY_ORB` | A security header (CORP, COEP) or the browser's ORB blocked the response. | Engineering: check the resource's headers. |
| **Blocked by an extension** (info) | `ERR_BLOCKED_BY_CLIENT` | An ad blocker or privacy extension stopped the request. | Harmless for analytics and ads. If the app needs that host, ask the customer to allow the site. |

## Webhook and API customers

The same categories apply to server-to-server calls (for example webhook deliveries): an expired certificate on the receiver produces TLS errors on every attempt until it is renewed. See casebook case 01.

## Ask the customer

- "Are you on a VPN, a corporate network, or using antivirus with 'HTTPS scanning'?"
- "Does it work on your phone's mobile data?" This one question separates their network from our servers.

## Escalate when

The failure happens from several networks and customers at once (likely our DNS, certificate or load balancer), or the certificate on our host really has expired.
