import dotenv from 'dotenv';

dotenv.config();

/**
 * Centralized, validated environment configuration.
 * Fails fast at startup if a required secret is missing so we never run
 * half-configured against Stripe.
 */
function required(name: string): string {
  const value = process.env[name];
  if (!value || value.trim() === '') {
    throw new Error(
      `Missing required environment variable "${name}". ` +
        `Copy .env.example to .env and fill it in.`,
    );
  }
  return value;
}

function optional(name: string, fallback = ''): string {
  return process.env[name]?.trim() || fallback;
}

export const config = {
  stripeSecretKey: required('STRIPE_SECRET_KEY'),
  stripePublishableKey: optional('STRIPE_PUBLISHABLE_KEY'),
  stripeWebhookSecret: required('STRIPE_WEBHOOK_SECRET'),
  appBaseUrl: optional('APP_BASE_URL', 'http://localhost:4242'),
  port: Number(optional('PORT', '4242')),
  prices: {
    proMonthly: optional('PRICE_ID_PRO_MONTHLY'),
    proYearly: optional('PRICE_ID_PRO_YEARLY'),
  },
} as const;

/** True when running against Stripe test mode (sk_test_...). */
export const isTestMode = config.stripeSecretKey.startsWith('sk_test_');
