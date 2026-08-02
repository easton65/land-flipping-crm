import { Router } from 'express';
import { stripe } from '../stripe';
import { findOrCreateCustomer } from '../lib/customers';

/**
 * INVOICING — send a hosted invoice a customer can pay online.
 *
 * Useful for land deals: bill a buyer an assignment fee, or a seller for a
 * service, and let Stripe email a professional hosted invoice with a pay link,
 * reminders, and receipts.
 *
 * Flow: create/reuse a Customer -> add invoice item(s) -> create invoice ->
 * finalize & send. The `invoice.paid` / `invoice.payment_failed` webhooks tell
 * you the outcome.
 */
export const invoicingRouter = Router();

/**
 * POST /invoicing/send
 * Body: {
 *   email, name?, crmContactId?,
 *   items: [{ description, amount (cents), quantity? }],
 *   currency?, daysUntilDue?, memo?
 * }
 */
invoicingRouter.post('/send', async (req, res, next) => {
  try {
    const {
      email,
      name,
      crmContactId,
      items,
      currency = 'usd',
      daysUntilDue = 7,
      memo,
    } = req.body ?? {};

    if (!email || !Array.isArray(items) || items.length === 0) {
      return res.status(400).json({
        error: 'Provide `email` and a non-empty `items` array.',
      });
    }
    for (const item of items) {
      if (!item?.description || !Number.isInteger(item?.amount) || item.amount <= 0) {
        return res.status(400).json({
          error: 'Each item needs a `description` and positive integer `amount` (cents).',
        });
      }
    }

    const customer = await findOrCreateCustomer({ email, name, crmContactId });

    // Create the invoice first so we can attach items directly to it.
    const invoice = await stripe.invoices.create({
      customer: customer.id,
      collection_method: 'send_invoice',
      days_until_due: daysUntilDue,
      description: memo,
      metadata: {
        ...(crmContactId ? { crm_contact_id: crmContactId } : {}),
      },
    });

    for (const item of items) {
      await stripe.invoiceItems.create({
        customer: customer.id,
        invoice: invoice.id,
        currency,
        unit_amount: item.amount,
        quantity: item.quantity ?? 1,
        description: item.description,
      });
    }

    // Finalize, then email the hosted invoice to the customer.
    const finalized = await stripe.invoices.finalizeInvoice(invoice.id);
    const sent = await stripe.invoices.sendInvoice(finalized.id);

    return res.json({
      id: sent.id,
      status: sent.status,
      hostedInvoiceUrl: sent.hosted_invoice_url,
      invoicePdf: sent.invoice_pdf,
      amountDue: sent.amount_due,
    });
  } catch (err) {
    return next(err);
  }
});
