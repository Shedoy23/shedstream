"""Компенсация зрителю крустиками — ручная, по решению владельца (25.09.2026).

Зачем: до этого компенсаций не было ни одной, и начислить было нечем, кроме
ручного UPDATE — а ручной UPDATE не пишет доход и не объясняет зрителю, откуда
деньги. Здесь те же функции ядра, что у возвратов: `add_points_tx`,
`record_income_tx` (источник `compensation`), `add_notice_tx` — в ОДНОЙ
транзакции BEGIN IMMEDIATE. Зритель увидит тост «<причина> Крустики вернулись: +N💎».

Защита от двойного начисления: одна и та же причина одному зрителю второй раз
не проходит (ищется уведомление kind='compensation' с тем же текстом).

Запуск на проде (из папки backend, чтобы подхватились модули и .env):
    cd /root/twitch-extension/backend
    ../venv/bin/python ../scripts/compensate-viewer.py --db viewers.db \
        --channel 98319857 --user НИК --amount 60000 --reason "Текст для зрителя."
    ... --apply        # без него — пробный прогон с откатом
Код возврата: 0 — начислено (или пробный прогон прошёл), 1 — отказ.
"""
import argparse
import asyncio
import os
import sys


async def run(args):
    backend = os.path.dirname(os.path.abspath(args.db))
    sys.path.insert(0, backend)
    from database import Database
    from notices import add_notice_tx

    db = Database(args.db)
    await db.init_pool()
    try:
        return await credit(db, add_notice_tx, args)
    finally:
        await db._pool.close()      # иначе потоки соединений держат процесс


async def credit(db, add_notice_tx, args):
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            user = args.user.lower()
            row = await (await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (args.channel, user))).fetchone()
            if row is None:
                print(f"ОТКАЗ: зрителя {user} на канале {args.channel} нет — проверь ник")
                await conn.rollback()
                return 1
            dup = await (await conn.execute(
                "SELECT id, created_at FROM viewer_notices WHERE channel_id=? AND username=? "
                "AND kind='compensation' AND text=?", (args.channel, user, args.reason))).fetchone()
            if dup:
                print(f"ОТКАЗ: эта компенсация уже начислена (уведомление #{dup[0]}, {dup[1]})")
                await conn.rollback()
                return 1
            before = row[0]
            await db.add_points_tx(conn, user, args.amount, args.channel)
            await db.record_income_tx(conn, args.channel, user, "compensation", args.amount)
            await add_notice_tx(conn, args.channel, user, "compensation", args.reason, args.amount)
            after = (await (await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                (args.channel, user))).fetchone())[0]
            if after - before != args.amount:
                print(f"ОТКАЗ: баланс изменился на {after - before}, а не на {args.amount} — откат")
                await conn.rollback()
                return 1
            if not args.apply:
                await conn.rollback()
                print(f"ПРОБНЫЙ ПРОГОН (откат): {user} {before} → {after} (+{args.amount}💎)")
                return 0
            await conn.commit()
            print(f"НАЧИСЛЕНО: {user} {before} → {after} (+{args.amount}💎)")
            return 0
        except Exception:
            await conn.rollback()
            raise


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--channel", type=int, required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--amount", type=int, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if args.amount <= 0:
        print("ОТКАЗ: сумма должна быть положительной")
        return 1
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
