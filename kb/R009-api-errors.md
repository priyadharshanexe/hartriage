# R009 — API error messages

**What the tool found:** error responses that came with a small JSON body (under 16 KB), grouped by error **code** and **message**. Most response bodies are dropped before storage, because they can contain customer data. Error bodies of failed requests are kept because they explain the failure, after the same secret redaction as everything else. For GraphQL (which reports errors with status 200), only the `errors` array is kept; the `data` is dropped.

The tool understands the common shapes:

- `{"error": {"code": "card_declined", "message": "Your card was declined."}}` (Stripe-style)
- `{"error": "invalid_grant", "error_description": "…"}` (OAuth)
- `{"errors": [{"code": "…", "message": "…"}]}` (JSON:API, GraphQL)
- `{"type": "…", "title": "…", "detail": "…"}` (RFC 9457 problem details)
- `{"detail": [{"loc": ["body", "email"], "msg": "field required"}]}` (FastAPI validation)
- `{"code": …, "message": …}` and `{"message": …}`

## How to use it

1. The error code is the fastest route to an answer: search the API's documentation or our KB for it.
2. **Validation errors (400/422)** name the field: tell the customer exactly which field and why.
3. **The same code many times** means one root cause. Answer it once.
4. **Codes that mention the account** (`plan_limit`, `subscription_inactive`, `feature_disabled`) are account issues, not bugs.

## Reply template (validation)

> The form was rejected because the email field was empty when it was sent ("email: field required"). If you're using autofill, it may not be triggering the form's update. Typing the address in by hand should work.

## Escalate when

The error code is internal (`internal_error`, `unexpected`) or undocumented. Include the code, the message, the request numbers and correlation ids.
