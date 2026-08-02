import { Router, raw } from 'express';
import { config } from '../config';
import { stripe } from '../stripe';
import { alreadyProcessed, markProcessed } from '../lib/idempotency';
import { handleStripeEvent } from '../handlers/webhookHandlers';

/**
 * Stripe webhook receiver.
 *
 * Critical requirements (all handled below):
 *  - Verify the signature with the RAW request body. This router uses
 *    express.raw() so the body is an untouched Buffer; the app must NOT apply
 *    a JSON body parser to this path (see server.ts — json() is mounted after
 *    this router / scoped to other paths).
 *  - Reject anything that fails verification with 400.
 *  - Be idempotent: Stripe may deliver an event more than once.
 *  - Process the event, then return 2xx. We return 500 on handler failure so
 *    Stripe retries with backoff. (If you add a durable job queue, enqueue and
 *    return 2xx immediately instead.)
 */
export const webhooksRouter = Router();

webhooksRouter.post(
  '/stripe',
  raw({ type: 'application/json' }),
  async (req, res) => {
    const signature = req.headers['stripe-signature'];
    if (!signature) {
      return res.status(400).send('Missing stripe-signature header');
    }

    let event;
    try {
      event = stripe.webhooks.constructEvent(
        req.body, // raw Buffer — do not JSON.parse before this
        signature,
        config.stripeWebhookSecret,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : 'unknown error';
      console.error(`[webhook] signature verification failed: ${message}`);
      return res.status(400).send(`Webhook Error: ${message}`);
    }

    // Idempotency: acknowledge duplicates without reprocessing.
    if (alreadyProcessed(event.id)) {
      return res.status(200).json({ received: true, duplicate: true });
    }

    try {
      await handleStripeEvent(event);
      markProcessed(event.id);
      return res.status(200).json({ received: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'unknown error';
      console.error(`[webhook] handler error for ${event.id}: ${message}`);
      // Non-2xx tells Stripe to retry later.
      return res.status(500).json({ error: 'handler_failed' });
    }
  },
);
