---
id: mem-003
topic: vr-on-allegiancecore
class: verified
observed: 2026-11-24
recorded-by: port
evidence: knowledge/openxr-port-survey.md
---

# The VR client is built on AllegianceCore, not on this C++ fork

The operator decided on 2026-11-24, in the working session, to build the
OpenXR VR client on AllegianceCore (`dominusbelial/AllegianceCore-public`, a
C#/.NET 10 rewrite with an OpenGL MonoGame client), in a fork the operator
owns. VR in this C++ fork was rejected: it needs Direct3D 9 interop on a
32-bit renderer, and a modified build could play on the public lobby only
once upstream accepts it. The decision, what it rejected, the lobby checks
and the forum sources are in `knowledge/openxr-port-survey.md`. Work item:
`ragesaq-002` in `DAG.json`.
