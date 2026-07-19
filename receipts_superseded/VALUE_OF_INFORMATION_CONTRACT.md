# Value of Information Contract (eagle-eye-value-of-information/1.0)

Model: conjugate Normal preposterior on log-delay. One future signal y' ~ N(theta, s^2);
posterior update exact; expected-min-loss after signal via deterministic 161-point quadrature
(normalized). Loss = exposure_rate * E[delay days] (lognormal mean, exact) + signed
per-intervention costs. Loss functions MUST be signed (sign_loss_function); tampered or
unsigned losses raise. Delay may be policy-forbidden: act_now_policy_forbids_delay.

Labels: "exact" ONLY when the posterior is Normal under the implemented model and signed
loss; otherwise MODEL_CONDITIONAL_ESTIMATE (t posteriors are normal-approximated and so
labeled in every executed cycle). No dollar value is emitted without loss_function_hash,
assumptions, uncertainty note, and receipt_hash.

Executed evidence: zero-information signal -> EVOI ~ 0; near-perfect signal maximizes EVOI;
cost/waiting dominance -> act_now; asymmetric losses flip decision_now; all test-locked.
