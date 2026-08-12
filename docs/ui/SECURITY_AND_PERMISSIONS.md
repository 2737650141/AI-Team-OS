# Security & Permissions UI

Settings contains three plain-language cards: Safe, Standard (Recommended), and Maximum. The cards
explain behavior and suitable scenarios without exposing policy JSON. The first Maximum selection
opens one concise confirmation describing automated actions and the remaining hard boundaries.
That acknowledgement is remembered; later restarts do not ask again.

A lightweight permission badge is always visible in the top bar and links directly to the panel.
Dashboard shows the current global mode. Task Detail shows both the mode at task start and the live
current mode for traceability.

When confirmation is genuinely required, the approval card leads with one human sentence and only
two primary choices: Allow and Reject. Tool, risk, target and reason fields are under Advanced.
There is no “Always allow”; persistent behavior is changed only through the three global modes.

Recent Automatic Actions shows what was executed without interruption. It is an audit view, not
semantic memory, and it contains no secret values.
