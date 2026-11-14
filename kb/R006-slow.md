# R006 — Slow requests

**What the tool found:** requests that took longer than the threshold (3 seconds by default), grouped by the **phase** where most of the time went. Long-lived connections (server-sent events, websockets) are excluded because they are slow by design.

## The phases

A HAR file splits each request's time into phases. The dominant phase points at who can fix it:

| Phase | Shown as | Where the time goes | Who can fix it |
|---|---|---|---|
| `blocked` | queued in the browser | Waiting in the browser before sending: too many parallel requests to one host over HTTP/1.1 (6 per host), a busy service worker, proxy decisions. | The app (fewer parallel requests, HTTP/2), or the customer's proxy. |
| `dns` | DNS lookup | Looking up the hostname. | The customer's network or VPN DNS. |
| `connect` | connecting | Opening the TCP connection. | Network path, firewall, server load. |
| `ssl` | TLS handshake | Setting up encryption. | TLS-inspecting proxies, distant servers. |
| `send` | uploading | Sending the request body. | Large uploads on a slow uplink. |
| `wait` | waiting for the server | Time to first byte: the server is thinking. | **Engineering**: the backend is slow. |
| `receive` | downloading | Downloading the response. | Large responses or a slow connection. |

**`wait` is the one most worth escalating.** It is measured from the request being sent to the first byte coming back, so the network has little to do with it.

## How to read the finding

- The evidence lists the slowest requests with their total time and the time spent in the dominant phase.
- Several requests slow in `dns` or `connect` at the same time point to the customer's network. One endpoint slow in `wait` every time points to that endpoint.
- Compare against a recording from a healthy session, if you have one.

## Ask the customer

- "Is it slow at certain times of day, or all the time?"
- "Is it slow for colleagues in the same office?"
- For `receive`: "What kind of connection are you on?"

## Escalate when

The phase is `wait` on our API. Include the endpoint, the timings, the time of day and correlation ids.
