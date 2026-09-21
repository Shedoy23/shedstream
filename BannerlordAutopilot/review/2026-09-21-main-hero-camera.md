# Камера основного героя: проверка 21.09.2026

Актуальная база da78a07 / d31fe4f из autopilot-bandit-gathering.
Предыдущее изменение d31fe4f делегирует формации RBM при включённом AI,
иначе сохраняет атаку автопилота. Код просмотрен, BattleMission проверяет
оба варианта. Живые боевые последствия здесь не подтверждены.

Установленный Agent.IsCameraAttachable допускает AI Controller в singleplayer.
MissionScreen.GetSpectatingData выбирает доступный Mission.MainAgent;
камера первого лица определяется CameraIsFirstPerson и равенством MainAgent.
Нативная камера обрабатывает mouse deltas в CalculateNewBearingAndElevationForFirstPerson.
Поэтому не нужны Harmony, подмена контроллера или запись направления взгляда.

Сохраняем CameraIsFirstPerson при передаче героя AI, включаем первый вид один раз.
Восстанавливаем при неактивном герое, смене MainAgent, окончании боя, F12,
диалоге и OnEndMission. Не переустанавливаем каждый кадр, оставляя native toggle.
Мышь и её влияние на AI в реальном бою, верхом и при столкновениях не проверены.

Тест сначала красный: пять FAIL на исходном коде, commit 414e4b6.
После исправления BattleMission exit 0, включая 20 camera assertions
для исходных первого/третьего лица и пяти путей завершения. Release 0/0.
DLL только локальная: BannerlordAutopilot/bin/Win64_Shipping_Client.
В игру новая камера НЕ установлена.
