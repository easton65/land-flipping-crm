/**
 * Minimal in-memory store of processed webhook event IDs.
 *
 * Stripe can deliver the same event more than once, so we skip events we've
 * already handled. This in-memory Set is fine for a single process / local
 * dev, but it is LOST on restart and NOT shared across instances.
 *
 * For production, replace this with a durable, atomic check — e.g. insert the
 * event id into a `processed_stripe_events(id primary key)` table (or Redis
 * SETNX) and treat a uniqueness violation as "already processed".
 */
const processed = new Set<string>();

export function alreadyProcessed(eventId: string): boolean {
  return processed.has(eventId);
}

export function markProcessed(eventId: string): void {
  processed.add(eventId);
}
