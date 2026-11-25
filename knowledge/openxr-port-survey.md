# OpenXR port survey: how Allegiance renders, and where VR can attach

**Owner:** ragesaq · **Started:** 2026-11-24 · **Last reviewed:** 2026-11-24 · **Review by:** 2027-02-24

**Status:** in progress

## What this answers

Where an OpenXR VR client can attach to the Allegiance engine, which rendering path to take, what the main risks
are, and which parts of the community VR-modding workflow apply to a game whose source we own.

## Current state

- The renderer is Direct3D 9, fixed-function. The device is created with plain `Direct3DCreate9`, not D3D9Ex
  (`src/engine/D3DDevice9.cpp:119`). The source has no vertex or pixel shaders. *(read 2026-11, upstream `c106531`,
  spot-checked)*
- Every VS2022 project builds Win32 (32-bit) only. The solution's `x64` entries map to `Win32` project configurations
  (`VS2022/Allegiance.sln:262`). *(read 2026-11, spot-checked)*
- OpenXR has no D3D9 graphics binding. Its Windows bindings are D3D11, D3D12, Vulkan and OpenGL. *(read: OpenXR
  specification, [XR_KHR_D3D11_enable](https://registry.khronos.org/OpenXR/specs/1.0/html/xrspec.html#XR_KHR_D3D11_enable))*
- No rendering path is chosen yet. Work item: `ragesaq-002` in `DAG.json`.

## How it applies here

### Engine seams (read 2026-11 at `c106531`)

| Concern | Where | Notes |
|---|---|---|
| Device creation | `src/engine/D3DDevice9.cpp:119`, `CreateDevice` at :310–600 | FLIP or DISCARD swap effect. Resources in `D3DPOOL_MANAGED` (`VBIBManager.cpp`, `VRAMManager.cpp`, `surface.cpp`) |
| Present | `src/engine/D3DDevice9.cpp:884`, reached from `EngineWindow::DoIdle` (`src/engine/enginewindow.cpp:1122`, `RenderFrame` then `RenderFinished`) | Frame-loop hook point |
| Projection | `src/engine/camera.cpp:85–100` | Symmetric, from one `m_focus`. VR needs asymmetric per-eye projection |
| View matrix | `src/engine/camera.cpp:103–115`; set through `src/engine/device3d.cpp`: `GenerateProjectionTransform` (:483) calls `SetTransform(D3DTS_PROJECTION, ...)` at :530, and `GenerateViewTransform` (:533) calls `SetTransform(D3DTS_VIEW, ...)` at :553 | A software full matrix (`GetFullMatrix`, about :575) drives clipping and culling and must match |
| 3D layer setup | `src/engine/context.cpp:916` `Begin3DLayer` | Calls `Camera::Update` then sets both matrices |
| Game camera | `CameraControl`, `src/WinTrek/WinTrek.cpp:285` | Already has a head-look hook: `SetHeadOrientation` (:302) feeds `m_orientationHead`, combined with ship orientation at :426. Spot-checked |
| Comfort hazards | `src/WinTrek/WinTrek.cpp` :336–370 transitions, :375–395 afterburner shake, :398–422 aleph FOV warp | Disable or soften in VR mode |
| Second camera | "posters" camera, same orientation | Drives backdrop, stars and lens flare. Needs per-eye treatment too |
| HUD and 2D UI | Retained image tree, layers assembled at `src/WinTrek/WinTrek.cpp:3109–3231` (HUD group about :3172, console :3229) | `src/WinTrek/indicator.cpp:167` and :441 draw projected target markers through `Begin3DLayer` |
| Input | DirectInput8, `src/engine/dinput.cpp:1633`; mapping in `src/WinTrek/trekinput.cpp`; flight read in `SenseJoystick` (`WinTrek.cpp:8253`) | No existing head tracking or TrackIR code |
| Build | `VS2022/Allegiance.sln` (v143), links `d3d9`, `d3dx9`, `dinput8`; needs the June 2010 DirectX SDK (`README.md`) | CMake 3.24 also present |

Rows not marked "spot-checked" came from a delegated source read on 2026-11-24. Re-open the file before relying on
a line number.

### Rendering path options (derived from the rows above and the OpenXR binding list)

| Option | What it takes | For | Against | State |
|---|---|---|---|---|
| D3D9Ex shared texture to a D3D11 OpenXR swapchain | Switch to `Direct3DCreate9Ex`, move managed-pool resources to the default pool, render each eye into a shared render target, open it in D3D11 with `OpenSharedResource`, copy into the swapchain | Smallest change that keeps the fixed-function renderer | An extra copy and a sync each frame at 90 Hz. Device-loss handling changes once the managed pool is gone | Leading candidate |
| D3D9On12 with the D3D12 binding | Create the device through D3D9On12 and unwrap its resources | Smaller device-creation change | Less confidence that the driver path holds up | Fallback |
| Port the renderer to D3D11 | Replace the fixed-function pipeline with shaders | Clean long-term answer | Large | Not now |

### Proposed first milestone (derived)

A "virtual screen" in the headset. Create the device as D3D9Ex behind a flag, start an OpenXR session with a D3D11
device, and each frame copy the existing mono backbuffer through the shared texture into an `XrCompositionLayerQuad`.
If VR fails to start, the game launches flat. This proves the 32-bit runtime question, the interop, the frame loop
and the fallback before any stereo work. Milestone 2 is per-eye rendering of the 3D layer, with the head pose fed
through `m_orientationHead`.

## Open questions

- **Do the OpenXR runtimes the operator uses accept a 32-bit process?** The build is Win32 only. Some runtimes may
  ship only a 64-bit runtime DLL. Not verified. Check each runtime's loader before milestone 1, because an x64 build
  of Allegiance would be a project of its own.
- What is one Allegiance world unit in metres? It sets the stereo separation and the cockpit scale.
- Will a modified client be accepted on community servers, given the linked `src/Lib/AllegianceSecurity`?

## Community workflow: VR-Mod-Vibecoding-Wizard

[bigbossafman/VR-Mod-Vibecoding-Wizard](https://github.com/bigbossafman/VR-Mod-Vibecoding-Wizard) (MIT) is a single
agent skill file, a prompt workflow with no code. *(read 2026-11)*

| Part | Applies here? | Why (derived) |
|---|---|---|
| Camera ownership before stereo; head pose applied last in the frame | Yes | Matches the `CameraControl` seam |
| Stereo preference: runtime per-eye view and projection, then single-pass, then two passes | Yes | Two passes of the 3D layer is the realistic start on a fixed-function engine |
| OpenXR first, actions bound by name, one interaction profile per controller family | Yes | |
| HUD inventory: classify each element and give each class a treatment | Yes | The HUD is a retained tree, so elements can be listed |
| Feature flags, safe mode, a desktop simulator, in-game assertions, comfort and nausea protocol | Yes | |
| Proxy DLLs, injectors, signature and memory scanning, finding the camera by frame capture | No | We own the source |
| Physics hands, holstered weapons, full-body IK | Mostly no | Assumes a first-person game; Allegiance is a seated cockpit sim |
| Its own `docs/` layout (TARGET_PROFILE, PHASE_PLAN, DECISIONS) | No | This repository's `DAG.json`, `memory/` and `knowledge/` already do that job |

## Timeline

- 2026-11-24: survey of upstream `c106531` and of the wizard repository. No code changed.
