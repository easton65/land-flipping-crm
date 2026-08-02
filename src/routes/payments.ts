import { Router } from 'express';
import { config } from '../config';
import { stripe } from '../stripe';
import { findOrCreateCustomer } from '../lib/customers';

/**
 * PAYMENTS — one-time charges.
 *
 * Two patterns are included:
 *  1. Stripe-hosted Checkout (recommended default): least PCI burden, handles
 *     the payment UI, 3DS/SCA, receipts, and redirects for you.
 *  2. PaymentIntent (advanced): use when you build your own UI with Stripe
 *     Elements and need full control over the flow.
 *
 * For a land-flipping CRM these map to things like earnest-money deposits,
 * one-time assignment fees, or a one-off setup charge.
 */
export const paymentsRouter = Router();

/**
 * POST /payments/checkout
 * Create a hosted Checkout Session for a one-time payment.
 * Body: { email, amount (in cents), currency?, description?, crmContactId? }
 */
paymentsRouter.post('/checkout', async (req, res, next) => {
  try {
    const {
      email,
      amount,
      currency = 'usd',
      description = 'Land Flipping CRM payment',
      crmContactId,
    } = req.body ?? {};

    if (!email || !Number.isInteger(amount) || amount <= 0) {
      return res.status(400).json({
        error: 'Provide `email` and a positive integer `amount` in cents.',
      });
    }

    const customer = await findOrCreateCustomer({ email, crmContactId });

    const session = await stripe.checkout.sessions.create({
      mode: 'payment',
      customer: customer.id,
      line_items: [
        {
          price_data: {
            currency,
            unit_amount: amount,
            product_data: { name: description },
          },
          quantity: 1,
        },
      ],
      success_url: `${config.appBaseUrl}/payments/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${config.appBaseUrl}/payments/cancel`,
      metadata: {
        ...(crmContactId ? { crm_contact_id: crmContactId } : {}),
        purpose: 'one_time_payment',
      },
    });

    return res.json({ id: session.id, url: session.url });
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /payments/intent
 * Create a PaymentIntent for a custom (Elements) frontend.
 * Returns the client_secret the browser needs to confirm the payment.
 * Body: { email, amount (in cents), currency?, crmContactId? }
 */
paymentsRouter.post('/intent', async (req, res, next) => {
  try {
    const { email, amount, currency = 'usd', crmContactId } = req.body ?? {};

    if (!email || !Number.isInteger(amount) || amount <= 0) {
      return res.status(400).json({
        error: 'Provide `email` and a positive integer `amount` in cents.',
      });
    }

    const customer = await findOrCreateCustomer({ email, crmContactId });

    const intent = await stripe.paymentIntents.create({
      amount,
      currency,
      customer: customer.id,
      automatic_payment_methods: { enabled: true },
      metadata: {
        ...(crmContactId ? { crm_contact_id: crmContactId } : {}),
        purpose: 'one_time_payment',
      },
    });

    return res.json({
      clientSecret: intent.client_secret,
      publishableKey: config.stripePublishableKey,
    });
  } catch (err) {
    return next(err);
  }
});
