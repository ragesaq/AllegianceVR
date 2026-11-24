# OpenXR port survey: how Allegiance renders, and where VR can attach

**Owner:** ragesaq · **Started:** 2026-11-24 · **Last reviewed:** 2026-11-24 · **Review by:** 2027-02-24

**Status:** in progress. The VR client will be built on AllegianceCore, not on this C++ fork (see Decision below).

## What this answers

Where an OpenXR VR client can attach to the Allegiance engine, which rendering path to take, what the main risks
are, and which parts of the community VR-modding workflow apply to a game whose source we own. Also, which codebase
the VR client is built on, and whether a VR build of the C++ client could play on the public FreeAllegiance lobby.

## Decision: build the VR client on AllegianceCore

- **Build the VR client on [AllegianceCore](https://github.com/dominusbelial/AllegianceCore-public), in a fork
  owned by ragesaq, not on this C++ fork.** *(decided 2026-11 by ragesaq, in the working session of 2026-11-24:
  "lets start by going allegiancecore, i'll make a fork")*
- Rejected: **VR in this C++ fork.** It needs a Direct3D 9 interop path on a 32-bit, fixed-function renderer
  (sections below), and a modified build can play on the public servers only once upstream accepts the change
  (Public lobby access, below). The operator judged that, if the VR client could not join the public lobby in any
  case, the easier codebase was the better start.
- What informed it *(derived from the AllegianceCore README and folder layout read 2026-11-24 at `b76d6c0`, not from
  a build)*: AllegianceCore is a C#/.NET 10 rewrite whose MonoGame client renders through OpenGL with shaders and
  builds for 64-bit. OpenXR has an OpenGL binding (`XR_KHR_opengl_enable`), so the Direct3D 9 problem and the
  32-bit runtime question do not arise. Its client has one project per platform over a shared game library, so a VR
  head is a new project beside them. Risks kept with the decision: one author and a fast-moving codebase; MonoGame
  does not readily expose its GL context or textures; and AllegianceCore runs its own server and HTTP lobby, with
  no sign in its documents that it can join the FreeAllegiance lobby.
- This note keeps the C++ engine survey below as the record of the path not taken. Work on the AllegianceCore path
  is tracked by `ragesaq-002` in `DAG.json`.

## Public lobby access for a modified C++ client

- The lobby admits a client only after Steam confirms its authentication ticket (`src/lobby/CSteamValidation.cpp:147`,
  `fValid` is true only for `k_EAuthSessionResponseOK`), and each game server checks the ticket again
  (`src/FedSrv/CSteamValidation.cpp`). *(read 2026-11 at `c106531`)*
- The lobby turns away a client whose lobby version differs (`src/lobby/client.cpp:290`), and sends a client whose
  `FileList.txt` checksum differs to auto-update (`src/lobby/client.cpp:272`). The auto-updater handles
  `Allegiance.exe` (`src/AutoUpdate/AutoUpdate.cpp:195`), so an update would likely replace a modified executable;
  the live `FileList.txt` was not seen. *(read 2026-11 at `c106531`)*
- The open code never checks the executable itself. The client sends a DRM checksum that is empty except in the
  official Steam build (`src/clintlib/clintlib.cpp:1489`), and no open server code verifies it. Deployed servers may
  run code that is not public. *(read 2026-11 at `c106531`)*
- Community policy: only pre-approved builds may play on the production lobby, patches reach the official build
  after development-team approval, gameplay changes go to a community vote, and beta builds run on a separate
  development lobby. The page is flagged out of date (it describes ASGS, replaced in 2012). *(read:
  [FreeAllegiance Wiki, Development](https://www.freeallegiance.org/FAW/index.php/Development))*
- The Steam-era lead developer invited changes as GitHub pull requests: "Everyone is welcome to submit changes."
  *(read: [forum, "Gameplay Vote!", January 2020](https://www.freeallegiance.org/forums/viewtopic.php?t=73471&start=10))*
- Earlier VR and head-tracking requests were turned down for lack of developers, not as cheating; a 2017 reply
  pointed to [VK9](https://github.com/disks86/VK9), a Direct3D 9 to Vulkan layer. *(read: forum threads
  [Allegiance VR](https://www.freeallegiance.org/forums/viewtopic.php?t=72139) and
  [Head Tracking Support?](https://www.freeallegiance.org/forums/viewtopic.php?t=43160))* No forum post about
  modified clients after the move to Steam, or about AllegianceCore, was found by the forum search on 2026-11-24.
- So a VR build of the C++ client could play publicly only as an upstream-accepted option. Until then it could use
  the beta lobby or private servers. *(derived from the rows above)*

## Current state

- The renderer is Direct3D 9, fixed-function. The device is created with plain `Direct3DCreate9`, not D3D9Ex
  (`src/engine/D3DDevice9.cpp:119`). The source has no vertex or pixel shaders. *(read 2026-11, upstream `c106531`,
  spot-checked)*
- Every VS2022 project builds Win32 (32-bit) only. The solution's `x64` entries map to `Win32` project configurations
  (`VS2022/Allegiance.sln:262`). *(read 2026-11, spot-checked)*
- OpenXR has no D3D9 graphics binding. Its Windows bindings are D3D11, D3D12, Vulkan and OpenGL. *(read: OpenXR
  specification, [XR_KHR_D3D11_enable](https://registry.khronos.org/OpenXR/specs/1.0/html/xrspec.html#XR_KHR_D3D11_enable))*
- No rendering path was chosen for this C++ engine: the VR client moved to AllegianceCore (Decision, above). Work
  item: `ragesaq-002` in `DAG.json`.

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
| D3D9 on Vulkan through a translation layer (VK9 then, DXVK now) | Run the D3D9 calls on Vulkan and use OpenXR's Vulkan binding | No renderer rewrite | Needs access to the layer's Vulkan images; DXVK's 32-bit support not checked | Raised on the forum in 2017; not evaluated |

### Proposed first milestone (derived)

A "virtual screen" in the headset. Create the device as D3D9Ex behind a flag, start an OpenXR session with a D3D11
device, and each frame copy the existing mono backbuffer through the shared texture into an `XrCompositionLayerQuad`.
If VR fails to start, the game launches flat. This proves the 32-bit runtime question, the interop, the frame loop
and the fallback before any stereo work. Milestone 2 is per-eye rendering of the 3D layer, with the head pose fed
through `m_orientationHead`.

## Open questions

- **Do the OpenXR runtimes the operator uses accept a 32-bit process?** This applies to the C++ path only;
  AllegianceCore builds for 64-bit. The C++ build is Win32 only. Some runtimes may
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
- 2026-11-24: read the lobby's client checks, the FreeAllegiance wiki and forums on modified clients, and the
  AllegianceCore README. ragesaq decided to build the VR client on AllegianceCore.
