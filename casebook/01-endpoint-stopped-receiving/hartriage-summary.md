### HAR Triage summary

**What the customer was doing**
- Main hosts: expired.badssl.com (1)
- 1 request over 4 s, starting 2026-11-14 09:13:54 UTC, recorded in chromium 159.0.8154.6

**First failure:** Request #1: GET https://expired.badssl.com/ → net::ERR_CERT_DATE_INVALID

**Likely cause:** The secure connection to expired.badssl.com failed because the certificate has expired (or the device clock is wrong) (net::ERR_CERT_DATE_INVALID).

**Evidence**
- Requests #1
- Browser error: net::ERR_CERT_DATE_INVALID

**Suggested next step:** Open https://expired.badssl.com in the browser and look at the certificate. If it is valid there, ask whether a proxy or antivirus inspects TLS.

**KB article:** [R005: TLS/certificate error](https://github.com/priyadharshanexe/hartriage/blob/main/kb/R005-network.md)

**Other findings**
- [high] First failure: #1 GET https://expired.badssl.com/ → net::ERR_CERT_DATE_INVALID

_Redaction: No secrets found. Engine 1.0.0._
