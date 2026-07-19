"""WITHDRAWN (V4 blocker 5): this script's "cross-generator" label was wrong.

What it actually did was an in-family parameter shift of the SAME generative
family, evaluated with default_config() instead of the signed champion, and
gated on NLL alone. The claim "prior transfer survives a generator swap" is
WITHDRAWN.

Honest replacements:
  scripts/run_parameter_shift_eval.py        (in-family shift, correctly labeled)
  scripts/run_independent_generator_eval.py  (structurally independent family)
"""
import sys

print("WITHDRAWN: 'cross-generator' was an in-family parameter shift.")
print("Use scripts/run_parameter_shift_eval.py or scripts/run_independent_generator_eval.py.")
sys.exit(2)
