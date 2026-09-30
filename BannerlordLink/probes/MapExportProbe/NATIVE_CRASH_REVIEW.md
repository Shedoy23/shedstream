# Native crash review and bounded data-only candidate, 2026-09-30

## What is established

Installed photo revision `5526ABA0…` crashed after the manual command. Attempt
`20260930T123155Z-8d22cbc0e007406ca3ab854922f14ea9` left a JSON at WaitingForView,
viewEnabledEngineFrame 4495. SetEnable(true) returned and the JSON was written.
No persisted save-arm transition, PNG, or cleanup. Readiness observations were
only in memory between durable transitions, so the exact last native call is unknown.

Windows Application events identify TaleWorlds.Native.dll+0x323c14, exception
0xC0000005. Exception-stream metadata from the 73,681,375-byte minidump confirms
an attempted read at address 0x50, thread 45952, instruction 0x7FF981D83C14.
This is consistent with a null object plus member offset, but does not identify
the object or function. No symbolized stack or proof of use-after-free exists.
CrashUploader separately failed with managed UnauthorizedAccess.

Evidence is preserved outside Git at task-2/crash-evidence/20260930T123155Z-probe-v2:
exact JSON, rgl/error logs, Windows events, original dump copy and hash manifests.
Dump copy SHA256:
`9CE0235C44993100EFA6CD9E19E7CB1808A2854E4D3E8A3EA3EE90A78DA42569`.
No memory/stack contents were inspected. WER Report.wer access was denied;
available event and exception-stream metadata were sufficient to establish the AV.

## What actual consumers do, and what they do not prove

Installed 1.4.8 SceneTableau was read separately from
Modules/Native/bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.View.dll.
It creates a SceneView and color target with autoMipmaps=true, automatic depth
creation, and uses a scene's customcamera entity. Its tick calls EnsurePostfxSystem,
changes shadows/bloom/motion blur/cascade state, enables postfx and the view,
and updates its camera. The native-facing methods forward to the engine.

Cached SceneTextureProvider consumer in the existing GauntletUI decompilation
wraps the target in EngineTexture/TwoDimension.Texture, sets its size and
ticks the tableau through the UI provider lifecycle. Texture.CreateTableauTexture
uses another path: isTableau=true, PaintNeeded callback/UserData, a TableauView,
automatic depth, then associates that view with the texture. These are distinct
consumers; they are not evidence that a bare SceneView is registered identically.

The failed probe used no UI texture consumer, an explicit depth target,
postfx=false and the active campaign's shared Scene. Any of these may matter,
but the crash metadata cannot choose between missing native state, render
scheduling/culling, depth setup or unsupported shared-scene use. No safe
photo fix follows from simply copying additional setup calls. SceneTableau's
scene mutations would violate the live-campaign constraints. Its existence
also does not establish that a second render can safely share campaign state.

## Narrow change

Photo entry point always refuses, without consuming the one data attempt or
queuing native work. Renderer allocation, enabling, save-to-texture calls and
native release/clear tasks are removed from this candidate, including nested callbacks.
Previous photo implementation and both corrections remain in Git history.

Separate manual data command writes identity, bounds, five landmarks and a
16x16 node grid including endpoints. Rows increase world Y and columns world X.
It queries valid land-navmesh surface/campaign height, plus terrain height
when available. Invalid faces/heights are null, not fabricated Plain/zero.
Land-navmesh queries do not create a water mask. Samples are not photographs.

Maximum 256 samples, eight per application tick, yield after a query when the
2ms budget expires; whole sampling operation has a five-second managed timeout.
Map/campaign readiness is checked each batch, cancel between samples. Native
calls cannot be interrupted, and grid runtime behavior is still unverified.
The existing primary renderer is never called by this candidate. Borrowed
Scene is used for queries only; there is no native resource cleanup/lifetime work.

## Next bounded verification — pending explicit permission

Keep the module disabled while playing. After a new installation signal and
the game being closed, replace only the probe component with the corrected
DLL/XML, verifying hashes. Preserve the updated autopilot and other modules.
Load normally with the module enabled only for a separately authorized test.
On a paused, saved, ready campaign map run data confirmation once, wait at
least six seconds, inspect JSON/status, expected 256 coordinates and landmarks.
Stop on timeout/error; no photo capture, retries or scene loading.

Photographic export is unresolved. A future path should avoid another view
on the live shared Scene; an isolated scene/UI tableau would need its own
resource/performance/runtime approval and is not implemented or loaded here.
