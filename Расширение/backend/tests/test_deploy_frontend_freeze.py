"""
test_deploy_frontend_freeze.py — замок фронт-деплоя доказан исполнением.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_deploy_frontend_freeze.py

ЧТО ДОКАЗЫВАЕТ (план frontend freeze 11.09, раздел 4).
    Пока кандидат в Hosted Test и Review, фронт на прод выкатывать нельзя:
    деплой фронта сам двигает метку кэша в обеих оболочках, сервер и копия на
    CDN перестают совпадать, verify-candidate перестаёт проходить. Замок в
    scripts/deploy.ps1 был, но его никто не проверял, а пробный запуск
    (-DryRun) обходил его целиком: команда «покажи, что будет» печатала обычный
    план выката там, где настоящий запуск упёрся бы в замок.

    Проверяется запуском НАСТОЯЩЕГО scripts/deploy.ps1 в пробном режиме — он
    ничего не меняет ни локально, ни на сервере (случай [6] это проверяет).
    Флаг в самом скрипте тест не трогает: SHEDLINK_FORCE_FRONTEND_FREEZE=1
    взводит замок на время прогона, а снять его переменной нельзя никак —
    это отдельный случай [5].

ТЕСТЫ:
    [1] фронт при заморозке — блок в пробном запуске, код 1
    [2] запуск по умолчанию (бэкенд + фронт) — тоже блок
    [3] бэкенд отдельно проходит замок, код 0
    [4] -CriticalReason в пробном запуске: «пропустил бы», журнал обходов не тронут
    [5] переменная окружения не ослабляет замок: «0» ведёт себя как её отсутствие
    [6] пробные запуски ничего не меняют в рабочем дереве
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
ROOT = HERE.parent.parent.parent
SCRIPT = ROOT / "scripts" / "deploy.ps1"
OVERRIDE_LOG = ROOT / "scripts" / "deploy-freeze-overrides.log"
BLOCKED = "FRONTEND DEPLOY BLOCKED"
WOULD_OVERRIDE = "FREEZE WOULD BE OVERRIDDEN"
ENV = "SHEDLINK_FORCE_FRONTEND_FREEZE"

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


def _runs(cand) -> bool:
    """Кандидат годен, только если ЗАПУСКАЕТСЯ. Наличие файла ничего не значит:
    ярлык Store (`WindowsApps\\pwsh.exe`) — это точка повтора, она остаётся на
    месте и после удаления приложения, а сама папка `C:\\Program Files\\WindowsApps`
    закрыта правами, так что поиск по ней возвращает пусто даже когда pwsh там
    лежит. Единственный честный вопрос — «выполнится ли»."""
    if not cand:
        return False
    try:
        proc = subprocess.run([cand, "-NoProfile", "-NonInteractive",
                               "-Command", "$PSVersionTable.PSVersion.Major"],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip().isdigit()


def _find_pwsh():
    """PowerShell 7 так, как его найдёт человек: сначала PATH, потом обычные
    места установки. Из Python под git-bash PATH бывает без них — именно так
    первый прогон этого теста сказал «нет pwsh» на машине, где деплой идёт
    через pwsh каждый день. Windows PowerShell 5.1 — последний запасной."""
    local = os.environ.get("LOCALAPPDATA") or ""
    cands = [shutil.which("pwsh"),
             r"C:\Program Files\PowerShell\7\pwsh.exe",
             r"C:\Program Files\PowerShell\7-preview\pwsh.exe",
             # Установка из Microsoft Store: стабильный ярлык запуска в профиле.
             os.path.join(local, "Microsoft", "WindowsApps", "pwsh.exe") if local else None,
             shutil.which("powershell")]
    for cand in cands:
        if _runs(cand):
            return cand
    return None


PWSH = _find_pwsh()


def _run(args, force=None):
    env = dict(os.environ)
    env.pop(ENV, None)
    if force is not None:
        env[ENV] = force
    proc = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT)] + args,
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _tail(out: str) -> str:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return " | ".join(lines[-4:])[:400]


def _git_status() -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def _log_state():
    return (OVERRIDE_LOG.stat().st_size, OVERRIDE_LOG.stat().st_mtime) \
        if OVERRIDE_LOG.exists() else None


def main() -> int:
    if not PWSH:
        print("  FAIL нет PowerShell — замок нечем проверить, "
              "а пропуск был бы ложным зелёным")
        return 1
    print(f"  оболочка: {PWSH}")

    tree_before = _git_status()

    print("\n[1] Фронт при заморозке")
    rc, out = _run(["-Frontend", "-DryRun"], force="1")
    check("пробный запуск фронта упирается в замок", BLOCKED in out,
          f"замок не сработал — пробный запуск показал бы обычный выкат: {_tail(out)}")
    check("и заканчивается кодом 1", rc == 1, f"код {rc}")

    print("\n[2] Запуск по умолчанию (бэкенд + фронт)")
    rc, out = _run(["-DryRun"], force="1")
    check("по умолчанию тоже блок", BLOCKED in out and rc == 1,
          f"код {rc}: {_tail(out)}")

    print("\n[3] Бэкенд отдельно")
    rc, out = _run(["-Backend", "-DryRun"], force="1")
    check("бэкенд проходит замок", BLOCKED not in out,
          f"замок задел выкат бэкенда: {_tail(out)}")
    # Замок выше проверяется на любой машине: он срабатывает первым, до работы
    # с файлами. А вот «пробный выкат доезжает до конца» — про среду, а не про
    # замок: на Linux-раннере у deploy.ps1 нет ни tar с нужными ключами, ни
    # ожидаемых путей, и красный тут означал бы «не та ОС», а не «замок сломан».
    if sys.platform == "win32":
        check("пробный запуск бэкенда доходит до конца, код 0", rc == 0,
              f"код {rc}: {_tail(out)}")
    else:
        print(f"      не Windows: код {rc} не проверяем — деплой запускают с машины владельца")

    print("\n[4] Обход с причиной в пробном запуске")
    log_before = _log_state()
    rc, out = _run(["-Frontend", "-DryRun", "-CriticalReason", "freeze gate self-test"],
                   force="1")
    check("пробный запуск честно пишет «пропустил бы»", WOULD_OVERRIDE in out and rc == 0,
          f"код {rc}: {_tail(out)}")
    check("журнал обходов не тронут — пробный запуск ничего не пишет",
          _log_state() == log_before, "журнал изменился")

    print("\n[5] Переменная окружения не ослабляет замок")
    rc_none, out_none = _run(["-Frontend", "-DryRun"])
    rc_zero, out_zero = _run(["-Frontend", "-DryRun"], force="0")
    check("«0» ведёт себя как отсутствие переменной",
          (BLOCKED in out_none) == (BLOCKED in out_zero) and rc_none == rc_zero,
          f"без переменной: код {rc_none}, блок {BLOCKED in out_none}; "
          f"с «0»: код {rc_zero}, блок {BLOCKED in out_zero}")
    print(f"      состояние флага в скрипте сейчас: "
          f"{'заморожено' if BLOCKED in out_none else 'открыто'}")

    print("\n[6] Пробные запуски ничего не меняют")
    check("рабочее дерево то же, что до прогонов", _git_status() == tree_before,
          "пробный запуск что-то записал в дерево")

    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
