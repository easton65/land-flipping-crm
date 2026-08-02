# Land Flipping CRM

A powerful, simple-to-use CRM system for tracking vacant land deals from seller outreach to final assignment. Designed around Alex Mineo’s proven 5-step L.A.N.D. Profit System.

## 💼 Features
- Seller lead tracking (skip trace, contact status, offer)
- Contract & acquisition dashboard
- Buyer CRM with buy box filters
- Deal pipeline with assignment price, profit, and status
- Built for Google Sheets & Apps Script integrations

## 🧠 Based on the L.A.N.D. System
1. **Market Research** – Identify hot zip codes with builder demand
2. **Seller Outreach** – Track contacts, follow-ups, and offers
3. **Contracting** – Record terms, due diligence, and signatures
4. **Dispo** – Match deals to active builders or cash buyers
5. **Closing** – Track assignments, profits, and timelines

## 🔧 Tools Used
- Google Sheets
- PropStream (list building)
- KindSkip / BatchSkip (contact info)
- Smarter Contact or cold call tracking

## 📈 Future Features
- Status automations
- Buy box filters for builders
- Notifications for follow-ups

## 💳 Stripe Integration
Payments, Billing, and Invoicing are wired up as a Node.js + TypeScript service.

```bash
cp .env.example .env   # add your TEST-mode Stripe keys
npm install
npm run dev            # server on http://localhost:4242
```

- One-time payments: `POST /payments/checkout`, `POST /payments/intent`
- Subscriptions: `POST /billing/subscribe`, `POST /billing/portal`
- Invoices: `POST /invoicing/send`
- Signature-verified webhooks: `POST /webhooks/stripe`

See **[docs/STRIPE_INTEGRATION_PLAN.md](docs/STRIPE_INTEGRATION_PLAN.md)** for the
full architecture, webhook events, and go-live checklist.

## 📜 License
MIT License — use and modify freely.
