# RBM AI compatibility

User authorized installing selected combat AI and adapting our autopilot.
Prior d31fe4f parent forced Charge/FireAtWill and IsAIControlled=false each second
for all field formations. That overrides the tactical formation behaviors that
the newly installed RBM provides. Optional reflection reads loaded RBMConfig only;
there is no hard dependency or forced Assembly.Load. Enabled RBM AI gets native
DelegateCommandToAI; absent/disabled RBM retains existing charge behavior.

Dynamic-assembly test exercises actual optional discovery, both boolean values,
order preservation and F12 ownership restoration. Red 2 FAIL; green all cases.
Campaign regressions 502/0, installed-game contract 492/492.
RBM uses source-based local AI-only package, with locale parse fix and gated clan
cleanup. See third-party local-build/README.md for exact scope and reproduction.
No live correctness claim: real campaign and Harmony patch activation need a launch.
