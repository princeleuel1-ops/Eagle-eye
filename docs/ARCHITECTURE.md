---
type: architecture
title: Vertical Slice Architecture
---

# Flow

`fixture JSON -> deterministic kernel -> graph/risk/scenario/action -> evidence package -> connected browser UI`

The kernel uses only the Python standard library for deterministic local verification. The first UI is served by the same process so the end-to-end slice has one startup path.
