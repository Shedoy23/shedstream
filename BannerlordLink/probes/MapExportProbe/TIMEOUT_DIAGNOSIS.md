# SceneView timeout: evidence and local correction

## Failed runtime attempt (before correction)

Attempt `20260930T111609Z-6529659805d9443db471eb9c1a23c7a6`, original
`%LOCALAPPDATA%/ShedLink/MapExportProbe/<attempt>/probe.json`, 5681 bytes.
Status `phase_timeout`; no PNG, no `viewReadyToRenderBeforeEnable` field.
Identity, bounds and five landmarks were recorded. Cleanup was queued and
reference release attempted; no managed/cleanup exception recorded.

The exact JSON and old local DLL were copied to ignored `runtime-evidence/<attempt>/`.
Original/copy JSON SHA256 both:
`B76212C94BF2271933A19F80D2500A0EB83686D9D36CE3148DB583CE02C6AE0D`.
Old DLL SHA256:
`1A6572682EFCBD2A821743D5762D627E45B91DBA233C3768A4C7180E52E4A193`.
Original output and installed DLL have not been changed by this correction.

## Cause supported by control flow

The old probe explicitly disabled its new view in Begin, then waited in
WaitingForView for CheckSceneReadyToRender before enabling it. The missing
report field proves it never passed this check; capture/save was never armed.
There were already SetScene, SetCamera, color and depth targets. Thus this was
not a PNG decoder/file-path failure, nor an omitted scene/depth assignment.

Installed 1.4.8 targeted decompilation (`inspection/MapScreen.cs`, lines 870–913):
HandleIfSceneIsReady waits five EngineFrameNo advances, enables the view based
on top-screen/conversation state, then calls HandleIfBlockerStatesDisabled.
That method (lines 800–804) checks ReadyToRender AND CheckSceneReadyToRender.
It does not require those checks to pass before SetEnable(true).

Existing `D:/shedlink-build/bl-decomp/TaleWorlds.MountAndBlade.View.decompiled.cs`:
SceneTableau.CreateTexture (lines 6999–7008) creates a standalone SceneView,
assigns its scene and render target, and enables automatic depth creation.
PopupSceneContinuousRenderFunction (around lines 7110–7136) calls SetEnable(true)
without a readiness prerequisite; IsReady is a separate ReadyToRender query.
This is an actual offscreen consumer without a SceneLayer registration step.
The probe uses an explicit depth target instead of automatic depth creation.

Likely root cause: readiness/render progression gated on an explicitly disabled
view. Native implementation is not visible: SceneView readiness and View enable
are EngineApplicationInterface forwarding methods. This remains a strong
ordering hypothesis, not a proved native precondition.

## Narrow correction and remaining limits

Enable only the owned offscreen view, with disk saving disabled, after complete
setup. Wait for five engine frame advances and both readiness checks; then arm
one save window. Record phase, frame numbers and latest readiness results so a
future timeout identifies the actual stalled stage. Do not disable at merely
the next application tick: wait for the engine frame counter to advance.

No scene resource checks, postfx initialization, lighting/entity/visibility changes,
screen layer registration, or modifications of the player's camera are added.
An engine-frame advance is not a GPU completion callback. The bounded save
window, PNG export and native resource lifetime still need a separately
authorized runtime attempt with the corrected DLL loaded normally.

No repeat capture, installation, restart, push or deploy during this work.
