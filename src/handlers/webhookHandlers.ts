import Stripe from 'stripe';

/**
 * Business logic for each Stripe event we care about.
 *
 * These handlers are where you update YOUR database / CRM records. They are
 * kept separate from the HTTP/verification layer (src/routes/webhooks.ts) so
 * the transport and the business logic can be tested independently.
 *
 * The TODOs mark where to plug in your CRM persistence (Google Sheets/Apps
 * Script API, a DB, etc.).
 */
export async function handleStripeEvent(event: Stripe.Event): Promise<void> {
  switch (event.type) {
    /* ---------------------------------------------------------------- */
    /* PAYMENTS                                                          */
    /* ---------------------------------------------------------------- */
    case 'payment_intent.succeeded': {
      const pi = event.data.object as Stripe.PaymentIntent;
      console.log(`[payments] succeeded: ${pi.id} (${pi.amount} ${pi.currency})`);
      // TODO: mark the deal/deposit as paid in your CRM using pi.metadata.crm_contact_id
      break;
    }
    case 'payment_intent.payment_failed': {
      const pi = event.data.object as Stripe.PaymentIntent;
      console.warn(`[payments] failed: ${pi.id} — ${pi.last_payment_error?.message}`);
      // TODO: flag the contact for follow-up
      break;
    }

    /* ---------------------------------------------------------------- */
    /* BILLING (subscriptions)                                          */
    /* ---------------------------------------------------------------- */
    case 'checkout.session.completed': {
      const session = event.data.object as Stripe.Checkout.Session;
      console.log(
        `[billing] checkout completed: ${session.id} (mode=${session.mode})`,
      );
      // For subscription mode this confirms signup. The subscription id is
      // session.subscription; the customer is session.customer.
      // TODO: link session.customer -> your CRM contact and grant access.
      break;
    }
    case 'customer.subscription.created':
    case 'customer.subscription.updated': {
      const sub = event.data.object as Stripe.Subscription;
      console.log(`[billing] subscription ${sub.status}: ${sub.id}`);
      // TODO: upsert plan + status (active/past_due/canceled) on the contact.
      break;
    }
    case 'customer.subscription.deleted': {
      const sub = event.data.object as Stripe.Subscription;
      console.log(`[billing] subscription canceled: ${sub.id}`);
      // TODO: revoke access for the contact tied to sub.customer.
      break;
    }

    /* ---------------------------------------------------------------- */
    /* INVOICING (and subscription invoices)                            */
    /* ---------------------------------------------------------------- */
    case 'invoice.paid': {
      const invoice = event.data.object as Stripe.Invoice;
      console.log(`[invoicing] paid: ${invoice.id} (${invoice.amount_paid})`);
      // TODO: mark the invoice/deal as paid in your CRM.
      break;
    }
    case 'invoice.payment_failed': {
      const invoice = event.data.object as Stripe.Invoice;
      console.warn(`[invoicing] payment failed: ${invoice.id}`);
      // TODO: trigger dunning / follow-up in your CRM.
      break;
    }

    default:
      // Safe to ignore. Configure the endpoint to only send events you handle.
      console.log(`[webhook] unhandled event type: ${event.type}`);
  }
}
