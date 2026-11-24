---
id: mem-002
topic: renderer-d3d9-win32
class: verified
observed: 2026-11-24
recorded-by: port
evidence: knowledge/openxr-port-survey.md
---

# Renderer is fixed-function D3D9, build is 32-bit only

At upstream `c106531` the engine creates a plain D3D9 device
(`src/engine/D3DDevice9.cpp:119`) and every VS2022 project is Win32 only.
OpenXR has no D3D9 binding, so VR needs an interop path or a renderer port.
Detail, seams and options: `knowledge/openxr-port-survey.md`.
