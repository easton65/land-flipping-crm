# Stripe Integration Plan — Land Flipping CRM

A best-practices plan for integrating **Payments**, **Billing**, and **Invoicing**
into the Land Flipping CRM, plus the runnable scaffold that ships with it.

> This plan was generated from Stripe's current documentation. The preferred
> way to get a fully personalized plan is Stripe's `stripe_implementation_planner`
> tool, which requires connecting the **Stripe MCP connector** (see
> "Connecting the Stripe MCP" below). This document is a strong, doc-grounded
> substitute you can start building on today.

---

## 0. How the three products map to a land-flipping business

Two common revenue models — the scaffold supports either (or both):

| Product | SaaS model (you sell the CRM) | Deal-ops model (you run land deals) |
|---|---|---|
| **Payments** | One-time upgrades, add-ons | Earnest-money deposits, one-off assignment fees |
| **Billing** | Recurring plans (Pro monthly/yearly) | Retainers / recurring buyer memberships |
| **Invoicing** | B2B invoices for annual/enterprise | Bill a buyer an assignment fee; bill a seller for services |

> ⚠️ **Paying money OUT** to sellers/third parties (not just collecting) needs
> **Stripe Connect**, which is a larger build not included in this scaffold.
> Flag it if that's your use case.

---

## 1. Prerequisites

1. A Stripe account → https://dashboard.stripe.com
2. **Test-mode** API keys → https://dashboard.stripe.com/test/apikeys
   - `sk_test_...` (secret) and `pk_test_...` (publishable)
3. Stripe CLI for local webhook testing → https://docs.stripe.com/stripe-cli
4. Node.js 18+

Do all development in **test mode**. Only switch to live keys after the go-live
checklist (§8).

---

## 2. Connecting the Stripe MCP (for the planner + Dashboard-in-Claude)

The setup steps you were given assume a **local Claude Code CLI**. In a
**web/remote session** the equivalent is the Stripe **MCP connector**:

1. Connect the **Stripe** connector from the connector card (or in claude.ai →
   Settings → Connectors). It authenticates via OAuth in your browser.
2. Start a **new session** so the connector's tools (including
   `stripe_implementation_planner`, `create_product`, `create_price`,
   `search_documentation`, etc.) load.
3. Re-run the planner with your business context for a personalized plan, then
   compare it against this document.

The MCP connector is a convenience layer for Claude to talk to Stripe — your
**application** still authenticates with the secret key in `.env` (§3). The two
are independent.

---

## 3. Configuration

```bash
cp .env.example .env
# Fill in STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET
npm install
npm run dev
```

Secrets live only in `.env` (git-ignored). `src/config.ts` fails fast if a
required key is missing. **Never** hardcode keys or expose the secret key to a
frontend.

---

## 4. Architecture (what's in the scaffold)

```
src/
  config.ts                 # validated env config; test-vs-live detection
  stripe.ts                 # single shared Stripe client (retries, appInfo)
  server.ts                 # express wiring; webhook mounted BEFORE json()
  lib/
    customers.ts            # find-or-create Stripe Customer, tagged w/ CRM id
    idempotency.ts          # dedupe processed webhook events (swap for DB)
  routes/
    payments.ts             # POST /payments/checkout, /payments/intent
    billing.ts              # POST /billing/subscribe, /billing/portal
    invoicing.ts            # POST /invoicing/send
    webhooks.ts             # POST /webhooks/stripe (signature-verified)
  handlers/
    webhookHandlers.ts      # per-event business logic (TODO: your CRM writes)
```

**Design principles baked in:**

- **One Customer per CRM contact.** `findOrCreateCustomer` stamps
  `crm_contact_id` into Customer metadata so Stripe objects trace back to your
  records. Store the returned `customer.id` on your contact row.
- **Webhooks are the source of truth**, not redirect URLs. A user can close the
  tab before the success page loads; the webhook still fires.
- **Amounts are integers in the smallest currency unit** (cents). `$250.00` → `25000`.
- **Metadata everywhere** (`crm_contact_id`, `purpose`) for reconciliation.

---

## 5. The three flows in detail

### Payments (one-time)
- **`POST /payments/checkout`** → Stripe-hosted Checkout (recommended default;
  least PCI scope, handles SCA/3DS and receipts).
- **`POST /payments/intent`** → PaymentIntent + `client_secret` for a custom
  Stripe Elements UI. Uses `automatic_payment_methods` so enabled methods show
  up without code changes.

### Billing (subscriptions)
- **`POST /billing/subscribe`** → Checkout in `subscription` mode against a
  Price ID (set `PRICE_ID_PRO_MONTHLY`/`_YEARLY` in `.env`, or pass `priceId`).
- **`POST /billing/portal`** → Stripe **Customer Portal** so users self-serve
  upgrades, card updates, and cancellations — no billing UI to build.
- Access is granted/revoked from `customer.subscription.*` webhooks.

### Invoicing
- **`POST /invoicing/send`** → creates a Customer, adds invoice item(s),
  finalizes, and **emails a hosted invoice** with a pay link + PDF. Returns
  `hosted_invoice_url` and `invoice_pdf`. Outcome arrives via `invoice.paid` /
  `invoice.payment_failed`.

---

## 6. Webhooks (security-critical)

Implemented in `src/routes/webhooks.ts` per Stripe's guidance:

- **Signature verified** with `stripe.webhooks.constructEvent()` using the
  **raw body** (route uses `express.raw()`; the JSON parser is mounted *after*
  the webhook router so it never touches this path).
- **Idempotent** — duplicate event IDs are acknowledged without reprocessing.
- **Retry-friendly** — returns `500` on handler failure so Stripe retries with
  backoff; `400` on a bad signature.
- **Subscribe to only the events you handle:**
  `payment_intent.succeeded`, `payment_intent.payment_failed`,
  `checkout.session.completed`,
  `customer.subscription.created|updated|deleted`,
  `invoice.paid`, `invoice.payment_failed`.

Local testing:
```bash
npm run stripe:listen          # prints whsec_... -> put in STRIPE_WEBHOOK_SECRET
stripe trigger payment_intent.succeeded
stripe trigger invoice.paid
```

---

## 7. Connecting to the CRM data layer

The event handlers in `src/handlers/webhookHandlers.ts` have `TODO` markers
where you persist to your CRM. Since the README describes a Google
Sheets / Apps Script backend, wire each handler to either:
- an Apps Script Web App endpoint (call it over HTTPS from the handler), or
- a real database if/when you migrate off Sheets.

Also replace `src/lib/idempotency.ts`'s in-memory Set with a durable,
atomic check (a `processed_stripe_events` table or Redis) before production.

---

## 8. Go-live checklist

- [ ] Replace test keys with live keys (`sk_live_`, `pk_live_`) in prod env.
- [ ] Create a **live** webhook endpoint in the Dashboard; use its
      `whsec_...` as the prod `STRIPE_WEBHOOK_SECRET`.
- [ ] Serve the webhook over **HTTPS**.
- [ ] Durable idempotency store in place (§7).
- [ ] Handlers actually write to the CRM (remove the `console.log` TODOs).
- [ ] Enable email receipts / branding in Dashboard settings.
- [ ] Set the account's API version and match it to the installed SDK; test.
- [ ] Confirm tax handling (Stripe Tax) and business info are configured.
- [ ] Monitor the Dashboard → Developers → Events/Logs after first live charges.

---

## 9. Security notes

- Secret key is **server-side only**; never ship it to a browser or commit it.
- `.env` is git-ignored; rotate any key that leaks (Dashboard → API keys).
- Never trust client-sent amounts for fixed-price items — prefer server-side
  Price IDs (Billing already does this).
- Keep webhook signature verification on; it's your defense against forged events.
```
