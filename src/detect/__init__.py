"""Statistical degradation detection. No LLM, no judgment call delegated to
a model -- see CLAUDE.md's AI-usage boundaries: distributional change is a
statistics problem, and an LLM here would be slower, non-reproducible, and
no more accurate than the beta-binomial significance test in
significance.py. This module only ever detects and records; it never
authorises or blocks spend -- src/policy/engine.py is still the only code
that does that.
"""
