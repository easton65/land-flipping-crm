import Stripe from 'stripe';
import { config } from './config';

/**
 * Single shared Stripe client for the whole app.
 *
 * We intentionally do NOT pin `apiVersion` here — the installed `stripe`
 * package pins its own tested version, and your account's dashboard API
 * version determines the shape of webhook Event payloads. Keep the two in
 * sync by upgrading the SDK and bumping the account version together, then
 * testing. See docs/STRIPE_INTEGRATION_PLAN.md for the upgrade checklist.
 */
export const stripe = new Stripe(config.stripeSecretKey, {
  // Identifies this integration in Stripe's logs — helpful for support.
  appInfo: {
    name: 'Land Flipping CRM',
    version: '0.1.0',
  },
  // Automatically retry transient network errors with backoff.
  maxNetworkRetries: 2,
  timeout: 20_000,
});
