import { Router } from 'express';
import { config } from '../config';
import { stripe } from '../stripe';
import { findOrCreateCustomer } from '../lib/customers';

/**
 * BILLING — recurring subscriptions.
 *
 * Flow:
 *  1. POST /billing/subscribe  -> hosted Checkout in `subscription` mode.
 *  2. Stripe redirects back to your success_url on completion.
 *  3. The `checkout.session.completed` + `customer.subscription.*` webhooks
 *     (see src/handlers/webhookHandlers.ts) are the SOURCE OF TRUTH for
 *     activating/deactivating access — never rely on the redirect alone.
 *  4. POST /billing/portal -> Stripe-hosted Customer Portal so users can
 *     upgrade, downgrade, update cards, and cancel without you building UI.
 *
 * Create your Products/Prices in the Dashboard (or via the API) and put the
 * Price IDs in .env (PRICE_ID_PRO_MONTHLY, etc.).
 */
export const billingRouter = Router();

/**
 * POST /billing/subscribe
 * Body: { email, priceId?, crmContactId? }
 * If priceId is omitted, defaults to PRICE_ID_PRO_MONTHLY from config.
 */
billingRouter.post('/subscribe', async (req, res, next) => {
  try {
    const { email, priceId, crmContactId } = req.body ?? {};
    const price = priceId || config.prices.proMonthly;

    if (!email) {
      return res.status(400).json({ error: 'Provide `email`.' });
    }
    if (!price) {
      return res.status(400).json({
        error:
          'No `priceId` provided and PRICE_ID_PRO_MONTHLY is not configured.',
      });
    }

    const customer = await findOrCreateCustomer({ email, crmContactId });

    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      customer: customer.id,
      line_items: [{ price, quantity: 1 }],
      success_url: `${config.appBaseUrl}/billing/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${config.appBaseUrl}/billing/cancel`,
      // Lets the Customer Portal / retries collect a new card if one fails.
      subscription_data: {
        metadata: {
          ...(crmContactId ? { crm_contact_id: crmContactId } : {}),
        },
      },
    });

    return res.json({ id: session.id, url: session.url });
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /billing/portal
 * Body: { customerId }  (the Stripe customer id you stored on the contact)
 * Returns a one-time URL to the Stripe Customer Portal.
 */
billingRouter.post('/portal', async (req, res, next) => {
  try {
    const { customerId } = req.body ?? {};
    if (!customerId) {
      return res.status(400).json({ error: 'Provide `customerId`.' });
    }

    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: `${config.appBaseUrl}/billing`,
    });

    return res.json({ url: session.url });
  } catch (err) {
    return next(err);
  }
});
