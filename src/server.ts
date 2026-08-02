import express from 'express';
import { config, isTestMode } from './config';
import { webhooksRouter } from './routes/webhooks';
import { paymentsRouter } from './routes/payments';
import { billingRouter } from './routes/billing';
import { invoicingRouter } from './routes/invoicing';

const app = express();

/**
 * IMPORTANT ordering:
 * Mount the webhook router BEFORE express.json(). The webhook route needs the
 * raw request body for signature verification (it applies express.raw()
 * itself). Mounting the JSON parser first would consume the stream and break
 * verification.
 */
app.use('/webhooks', webhooksRouter);

// JSON parser for all normal API routes.
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ ok: true, mode: isTestMode ? 'test' : 'live' });
});

app.use('/payments', paymentsRouter);
app.use('/billing', billingRouter);
app.use('/invoicing', invoicingRouter);

// Centralized error handler — keeps Stripe error details out of responses.
app.use(
  (
    err: unknown,
    _req: express.Request,
    res: express.Response,
    _next: express.NextFunction,
  ) => {
    const message = err instanceof Error ? err.message : 'Internal error';
    console.error('[error]', message);
    res.status(500).json({ error: message });
  },
);

app.listen(config.port, () => {
  console.log(
    `Land Flipping CRM Stripe server listening on ${config.appBaseUrl} ` +
      `(port ${config.port}, ${isTestMode ? 'TEST' : 'LIVE'} mode)`,
  );
  if (!isTestMode) {
    console.warn(
      '⚠️  Running with a LIVE Stripe key. Real money will move. ' +
        'Use sk_test_... keys for development.',
    );
  }
});
