export const CONTENT = {
  claims: {
    hero: "Run AI work without waiting for credit resets.",
    settlement: "Deterministic settlement with auditable state transitions.",
    topup: "Top-up and wallet state are idempotent and observable."
  },
  faq: [
    {
      q: "How does top-up settlement work?",
      a: "Top-up settlement is idempotent by topup_id and updates wallet credits exactly once."
    },
    {
      q: "Why does OpenVegas show low-balance suggestions?",
      a: "Suggestions are triggered when balance drops below configured USD-equivalent threshold and are suppressed during cooldown windows."
    },
    {
      q: "Is checkout state visible?",
      a: "Yes. Top-up pages expose checkout, status, and reconciliation state with explicit terminal statuses."
    }
  ]
};
