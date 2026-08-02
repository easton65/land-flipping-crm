import { stripe } from '../stripe';

/**
 * Find an existing Stripe Customer by email, or create one.
 *
 * In a real CRM you should store the returned `customer.id` on your own
 * contact/lead record and look it up from there — email search is a
 * convenient fallback, not a primary key. Two contacts can share an email,
 * and Stripe does not enforce email uniqueness.
 */
export async function findOrCreateCustomer(params: {
  email: string;
  name?: string;
  /** Your CRM's internal record id, stored as metadata for cross-reference. */
  crmContactId?: string;
  metadata?: Record<string, string>;
}) {
  const { email, name, crmContactId, metadata } = params;

  const existing = await stripe.customers.list({ email, limit: 1 });
  if (existing.data.length > 0) {
    return existing.data[0];
  }

  return stripe.customers.create({
    email,
    name,
    metadata: {
      ...(crmContactId ? { crm_contact_id: crmContactId } : {}),
      ...metadata,
    },
  });
}
