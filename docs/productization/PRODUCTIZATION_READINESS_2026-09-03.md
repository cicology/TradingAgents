# Oryares Trading Desk: Productization Readiness

**Assessment date:** 3 September 2026
**Decision:** Do not launch live trading or sell signals yet. Productize first as an evidence-first research and paper-trading workspace for XAU/USD, BTC/USD, EUR/USD, GBP/USD, and USD/JPY.

## Executive verdict

Oryares is a credible **research prototype**, not a launch-ready financial product. The repository proves that an agent workflow, market-data access, risk checks, reporting, MT5 connectivity, and a Binance bridge can be assembled. It does not yet prove that the system has a repeatable edge, sizes positions safely, records the full trade lifecycle, survives realistic failure modes, protects customer data, or can be operated as a reliable service.

Estimated readiness by launch definition:

| Launch definition | Readiness | Verdict |
|---|---:|---|
| Developer research prototype | 45% | Working but fragile |
| Internal paper-trading alpha | 30% | Reachable after the safety baseline |
| Invite-only paper/research beta | 18% | Recommended first external release |
| Public paid research SaaS | 10% | Product, compliance, privacy, and operations missing |
| Customer-facing live automation | 5% | Not responsibly launchable |

The percentages are decision aids, not test coverage or financial forecasts. They reflect observable implementation across safety, evidence, product surface, operations, QA/security, and compliance.

## What exists today

- A Python command-line trading desk with multi-agent analysis, risk review, reports, Kelly sizing, and market adapters.
- MT5 and Binance execution paths, including environment-gated live-order switches.
- Paper-first product direction, roadmap, Phase 0 plan, and delivery tracker.
- Seven dry-run ledger records, all rejected `HOLD` decisions. There is no closed-trade outcome history or performance evidence.
- Compilable Python source and a functioning `universe` command.

## Why it is not ready

### Safety and execution

Live execution remains reachable through CLI flags plus `DESK_ALLOW_LIVE_ORDERS=1`. The current implementation also has safety-critical defects: the LLM confidence can drive capped Kelly sizing from assumed reward/risk; risk-agent size limits are not consistently enforced; MT5 stop handling can omit a stop; minimum-lot rounding can exceed the risk budget; Binance quantity can bypass shared portfolio sizing; and close events are not wired back into risk state. MetaTrader's own documentation warns that accepting an order request is not proof of execution, so order, deal, rejection, partial-fill, and reconciliation states must be modeled explicitly ([MQL5 OrderSend](https://www.mql5.com/en/docs/trading/ordersend)).

### Evidence and model governance

There is no deterministic backtest engine, walk-forward evaluation, leakage test, paper broker with reproducible fills, or promotion report. This is the largest product gap. Backtest selection itself can overfit; the Probability of Backtest Overfitting literature exists precisely because ordinary hold-outs can be unreliable for investment simulations ([Bailey et al.](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253)).

The LLM layer has free-model fallback but no schema-enforced output, prompt/model version registry, evaluation suite, adversarial tests, cost/latency telemetry, or provider policy enforcement. Adopt a lightweight `Govern -> Map -> Measure -> Manage` control loop from the NIST AI RMF and its GenAI profile ([NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework), [NIST GenAI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)). Test at minimum for prompt injection, sensitive information disclosure, improper output handling, excessive agency, misinformation, and unbounded consumption ([OWASP GenAI Top 10](https://genai.owasp.org/llm-top-10/)).

### Product and market

There is no customer-facing application, API, authentication, onboarding, entitlement model, support workflow, or analytics. More importantly, broad “AI builds, backtests, and executes strategies” positioning is already occupied. QuantConnect markets an integrated pipeline with point-in-time, fee, slippage, and spread-aware backtests; Capitalise.ai offers code-free automation and simulated trading; Composer offers AI strategy creation, backtesting, and execution ([QuantConnect](https://www.quantconnect.com/), [Capitalise.ai](https://capitalise.ai/), [Composer](https://www.composer.trade/)).

Oryares should therefore differentiate on **auditability and promotion discipline**, not generic AI automation: every recommendation should show its data vintage, strategy version, prompt/model version, risk vetoes, assumptions, simulated fill, and promotion status.

### Deployment and operations

There is no root CI/CD pipeline, deployable service, environment strategy, monitoring, alerting, backup/restore procedure, SBOM, vulnerability gate, incident runbook, or rollback plan. MT5's Python integration communicates with an installed terminal, so the execution adapter is Windows-bound ([MQL5 Python integration](https://www.mql5.com/en/docs/python_metatrader5)). The correct product architecture is a cloud control plane plus a separately secured Windows execution connector—not a single generic Linux container.

### Privacy, regulation, and payments

If the product stores identity, broker-account metadata, positions, trade history, prompts, or support records, it needs a data inventory, lawful-purpose mapping, minimization, retention/deletion rules, access/export workflows, encryption, vendor review, and incident handling. The current OpenRouter client does not enforce Zero Data Retention, even though OpenRouter supports per-request `provider.zdr=true`; OpenRouter also retains request metadata and routes prompts through provider touchpoints ([OpenRouter data collection](https://openrouter.ai/docs/guides/privacy/data-collection), [OpenRouter ZDR](https://openrouter.ai/docs/guides/features/zdr)).

South Africa's FAIS regime regulates advice and intermediary services, and the FSCA describes advice as guiding a consumer to a specific financial product and intermediation as acting between a consumer and product supplier. External launch copy and functionality therefore require South African financial-services counsel and an explicit licensing/perimeter decision—not a disclaimer alone ([South African Government: FAIS purpose](https://www.gov.za/about-sa/finance), [FSCA digital-platform research](https://www.fsca.co.za/Regulatory%20Frameworks/FinTechDocuments/Fintech_Digital-Platforms_An_investigation_into_Fintech_Digital_platform_activity_in_South_Africa_and_their_regulatory_implications.pdf)).

Do not integrate payments before the business model is approved by the provider. Stripe lists investment, brokerage, currency-exchange, cryptocurrency, and other financial services as categories requiring contact and additional due diligence, and prohibits deceptive “get rich quick” claims ([Stripe restricted businesses](https://stripe.com/legal/restricted-businesses)). Use hosted checkout and never handle raw card data if approval is obtained.

## Recommended product direction

Launch **Oryares Lab**, an invite-only research and paper-trading workspace:

1. Five fixed markets: XAU/USD, BTC/USD, EUR/USD, GBP/USD, USD/JPY.
2. Two fixed programs: `15m intraday` and `1h swing`.
3. Evidence panels: data freshness, assumptions, strategy/prompt/model versions, risk vetoes, simulated fills, and closed-trade attribution.
4. Promotion states: `research -> backtest-passed -> paper-qualified -> demo-qualified -> live-eligible`.
5. No personalized advice, profit promise, copy-trading, custody, or live order execution in the first external release.

### Scope decisions from the requested skills

- **RAG:** Do not add it now. The core inputs are structured market data. Add retrieval only for licensed research/news with source-level access controls and independent retrieval evaluation.
- **GSAP:** No launch dependency. There is no frontend yet. If used later, restrict it to transform/opacity transitions, respect reduced-motion settings, and never animate critical risk values in a way that delays comprehension.
- **Payments:** Defer until the product perimeter and merchant underwriting are approved. Then use hosted subscription checkout, signed webhooks, idempotency, test/live separation, and entitlement reconciliation.
- **AI engineering:** Make LLMs advisory only. Deterministic code owns sizing, order policy, state transitions, and promotion decisions.

## Target architecture

```text
Market data feeds
      |
      v
Canonical data + freshness/quality gates
      |
      +--> deterministic feature/strategy engine
      |             |
      |             v
      |        LLM analyst panel (advisory, schema-bound, versioned)
      |             |
      +-------------+
                    v
            deterministic risk engine
                    |
          +---------+----------+
          |                    |
          v                    v
  paper broker + ledger    Windows MT5 connector
  (first release)          (disabled until promotion)
          |                    |
          +---------+----------+
                    v
       immutable audit/evaluation store
                    |
                    v
       API + research dashboard + alerts
```

The control plane should run independently of broker terminals. Every connector must be least-privilege, fail closed, idempotent, and reconcilable. A global kill switch must override all strategy and model decisions.

## Productization gates

### Gate 0 - Safety baseline

- Remove public live flags or compile live adapters out of default builds.
- Replace LLM-derived sizing with deterministic strategy/risk inputs.
- Fix stop, minimum-volume, max-size, exposure, close-event, and order-state handling.
- Add unit tests for every safety invariant and a single authoritative risk policy.

### Gate 1 - Reproducible evidence

- Canonical market schema and immutable run manifest.
- SQLite/Postgres ledger with orders, fills, positions, exits, costs, and attribution.
- Deterministic backtest plus time-split and walk-forward evaluation.
- Promotion report covering slippage, fees, spread, leakage, stability, drawdown, calibration, and failed experiments.

### Gate 2 - Paper alpha

- Paper broker with deterministic fixtures, rejection/partial-fill simulation, restart recovery, and reconciliation.
- Run XAU/USD first; add BTC and FX only after the same acceptance tests pass.
- Collect a minimum evidence window defined by trade count, regimes, and operational uptime—not calendar time alone.

### Gate 3 - Invite-only product beta

- API, authentication, tenant isolation, dashboard, onboarding, audit export, privacy controls, support, and usage limits.
- E2E tests for signup, strategy run, risk veto, paper order, reconciliation, export, deletion, and incident-mode shutdown.
- CI/CD with build, unit/integration/E2E, lint/type, secret, dependency, container, migration, and rollback gates.

### Gate 4 - Paid research launch

- Counsel-approved positioning and customer terms.
- Merchant/provider pre-approval, hosted checkout, signed/idempotent webhooks, entitlement checks, refunds, and reconciliation.
- Production monitoring, SLOs, on-call/incident runbooks, backup restore tests, and vulnerability response.

### Gate 5 - Demo/live eligibility

- Separate formal approval. Requires broker-specific certification, shadow/demo evidence, kill-switch drills, order/fill reconciliation, capital limits, and the resolved regulatory perimeter.

## Technical-debt register

Priority score uses `(Impact + Risk) x (6 - Effort)`, with each input scored 1-5.

| Rank | Debt / gap | I | R | E | Score | Required treatment |
|---:|---|---:|---:|---:|---:|---|
| 1 | Unsafe sizing/stop/minimum-volume paths | 5 | 5 | 2 | 40 | Block launch; fix with invariant tests |
| 2 | Live execution reachable in prototype UX | 5 | 5 | 2 | 40 | Remove from default build; two-person promotion gate |
| 3 | No automated tests or root CI | 5 | 5 | 3 | 30 | Establish unit, integration, E2E, security gates |
| 4 | Unpinned lower-bound dependencies and ungoverned gitlinks | 3 | 4 | 2 | 28 | Lock, scan, license/SBOM, update policy |
| 5 | Product universe/programs differ from implemented code | 4 | 4 | 3 | 24 | One canonical registry and contract tests |
| 6 | Payment/commercial model not underwritten | 3 | 4 | 3 | 21 | Counsel + provider approval before integration |
| 7 | Privacy/regulatory perimeter undefined | 5 | 5 | 4 | 20 | Data map, POPIA controls, legal opinion, approved copy |
| 8 | LLM lacks schemas, evals, versioning, and budgets | 5 | 4 | 4 | 18 | Structured outputs, registry, TEVV, limits, ZDR |
| 9 | MT5 deployment requires a Windows connector | 4 | 5 | 4 | 18 | Separate control plane and hardened connector |
| 10 | No complete outcome ledger or performance evidence | 5 | 5 | 5 | 10 | Foundational data/evaluation program |

## Testing and release tracker

Use the repository tracker as the source of delivery truth. Add these release epics and do not start a later gate until all prior acceptance criteria are evidenced:

| Epic | Exit evidence | Release blocker |
|---|---|---|
| E0 Safety isolation | Live paths unreachable; risk invariants green | Yes |
| E1 Data and ledger | Reproducible run + complete trade lifecycle | Yes |
| E2 Evaluation | Leakage-safe backtest/walk-forward report | Yes |
| E3 Paper broker | Deterministic fills, restart and reconciliation tests | Yes |
| E4 Product surface | Auth, tenant isolation, audit/export/delete E2E | Yes |
| E5 Operations | CI/CD, observability, restore, rollback, incident drill | Yes |
| E6 Commercial/compliance | Counsel sign-off + payment-provider approval | Yes |
| E7 Demo/live | Broker certification + demo evidence + kill-switch drill | Yes for live only |

For one experienced full-time engineer with founder availability, a realistic planning range is roughly **14-22 engineering weeks to an invite-only paper beta** and **24-40 weeks to a public paid paper/research product**. These are inference-based planning ranges, not commitments; team size, data licensing, counsel, payment underwriting, and broker integration can move them substantially. A customer-facing live execution date should not be forecast until Gate 4 is complete.

## Immediate next sprint

1. Make live execution unreachable in standard builds.
2. Write failing tests for all known safety defects, then fix them.
3. Introduce the canonical five-instrument/two-program registry.
4. Build the immutable run manifest and complete paper ledger.
5. Ship the first deterministic XAU/USD backtest and paper-broker vertical slice.
6. Add root CI and a launch-gate dashboard tied to evidence, not task completion alone.

## Final judgment

The concept makes sense if the product promise is **“trustworthy, auditable AI-assisted market research that must earn promotion”**. It does not make sense to launch as another autonomous AI trading bot before evidence, safety, and regulatory controls exist. The shortest responsible route to market is a narrow invite-only paper product; the live connectors should be treated as quarantined integration experiments until independently promoted.
