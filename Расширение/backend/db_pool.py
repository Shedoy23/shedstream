"""
Persistent database connection pool для aiosqlite.

Использование:
    from db_pool import get_db_pool, close_db_pool
    
    # Получаем пул соединений
    pool = get_db_pool()
    
    # Используем соединение из пула
    async with pool.acquire() as conn:
        cursor = await conn.execute("SELECT * FROM viewers")
        rows = await cursor.fetchall()

# Важно закрыть пул при завершении приложения
import atexit
atexit.register(close_db_pool)
"""

import asyncio
import logging
import os
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class DBPool:
    """
    Пул соединений для aiosqlite.

    Логика:
    - Держит до max_size соединений.
    - acquire(): сначала пробует взять готовое; если очередь пуста и лимит не достигнут —
      создаёт новое; если лимит достигнут — ждёт с таймаутом.
    - release(): возвращает соединение в очередь; если соединение сломано — закрывает его.
    """

    def __init__(
        self,
        db_path: str,
        min_size: int = 1,
        max_size: int = 10,
        timeout: float = 10.0,
    ):
        self.db_path = db_path
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self._pool: Optional[asyncio.Queue] = None
        self._active: int = 0          # сколько соединений сейчас существует (в пуле + на руках)
        self._lock: Optional[asyncio.Lock] = None

    async def initialize(self) -> None:
        """Инициализирует пул: создаёт min_size соединений."""
        if self._pool is not None:
            logger.warning("DBPool уже инициализирован")
            return

        logger.info(f"Инициализация DBPool для {self.db_path} (min={self.min_size}, max={self.max_size})")
        self._pool = asyncio.Queue()
        self._lock = asyncio.Lock()

        for _ in range(self.min_size):
            conn = await self._open_connection()
            if conn is not None:
                await self._pool.put(conn)
                self._active += 1

        logger.info(f"DBPool инициализирован. Соединений: {self._active}")

    async def _open_connection(self) -> Optional[aiosqlite.Connection]:
        """Открывает одно соединение с нужными PRAGMA."""
        try:
            conn = await aiosqlite.connect(self.db_path, timeout=self.timeout)
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=10000")
            return conn
        except Exception as e:
            logger.error(f"DBPool: ошибка создания соединения: {e}")
            return None

    async def acquire(self, timeout: float = 30.0) -> aiosqlite.Connection:
        """
        Берёт соединение из пула.
        Если очередь пуста — создаёт новое (до max_size).
        Если лимит достигнут — ждёт освобождения с таймаутом.
        """
        if self._pool is None or self._lock is None:
            logger.warning("DBPool не инициализирован — автоматическая инициализация")
            await self.initialize()

        # 1. Быстрый путь: есть готовое соединение
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # 2. Лимит не достигнут — создаём новое
        async with self._lock:
            if self._active < self.max_size:
                conn = await self._open_connection()
                if conn is not None:
                    self._active += 1
                    return conn

        # 3. Лимит достигнут — ждём с таймаутом
        try:
            return await asyncio.wait_for(self._pool.get(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("DBPool: таймаут ожидания соединения")
            raise

    async def release(self, conn: aiosqlite.Connection) -> None:
        """Возвращает соединение в пул. Если сломано — закрывает и уменьшает счётчик."""
        if self._pool is None:
            return
        try:
            # Проверяем что соединение живое простым запросом
            await conn.execute("SELECT 1")
            await self._pool.put(conn)
        except Exception:
            # Соединение сломано — закрываем и убираем из счётчика
            async with self._lock:
                self._active -= 1
            try:
                await conn.close()
            except Exception:
                pass
            logger.warning("DBPool: сломанное соединение закрыто")

    async def close(self) -> None:
        """Закрывает все соединения в пуле."""
        if self._pool is None:
            return

        logger.info("Закрытие DBPool...")

        # Забираем все оставшиеся соединения
        while not self._pool.empty():
            try:
                conn = await asyncio.wait_for(self._pool.get(), timeout=1.0)
                await conn.close()
            except asyncio.TimeoutError:
                break
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения: {e}")

        self._pool = None
        logger.info("DBPool закрыт")

    async def __aenter__(self) -> "DBPool":
        """Контекстный менеджер для инициализации."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Контекстный менеджер для закрытия."""
        await self.close()


# Глобальный пул (для legacy-кода)
_global_pool: Optional[DBPool] = None


def get_db_pool(db_path: Optional[str] = None) -> DBPool:
    """
    Получает или создаёт глобальный пул соединений.

    Args:
        db_path: Путь к файлу БД (опционально, берётся из экземпляра Database если не указан).

    Returns:
        Глобальный пул соединений.
    """
    global _global_pool

    if _global_pool is not None:
        return _global_pool

    # Если db_path не указан, пытаемся получить из окружения
    if db_path is None:
        from database import get_db
        db = get_db()
        db_path = db.db_path

    _global_pool = DBPool(db_path=db_path, min_size=1, max_size=10, timeout=10.0)
    return _global_pool


async def close_db_pool() -> None:
    """Закрывает глобальный пул соединений."""
    global _global_pool

    if _global_pool is not None:
        await _global_pool.close()
        _global_pool = None


# Инициализация при импорте (для legacy-кода)
async def initialize_db_pool(db_path: Optional[str] = None) -> DBPool:
    """
    Инициализирует глобальный пул соединений.

    Args:
        db_path: Путь к файлу БД (опционально).

    Returns:
        Глобальный пул соединений.
    """
    global _global_pool

    if _global_pool is not None:
        return _global_pool

    pool = DBPool(
        db_path=db_path or os.getenv("DB_PATH", "data/rimworld.db"),
        min_size=1,
        max_size=10,
        timeout=10.0,
    )
    await pool.initialize()
    _global_pool = pool
    return pool


# Контекстный менеджер для работы с пулом
class DBPoolContext:
    """Контекстный менеджер для работы с пулом соединений."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "data/rimworld.db")
        self.pool: Optional[DBPool] = None
        self.conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> aiosqlite.Connection:
        """Возвращает соединение из пула."""
        self.pool = get_db_pool(self.db_path)
        await self.pool.initialize()
        self.conn = await self.pool.acquire()
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Возвращает соединение в пул."""
        if self.conn is not None:
            await self.pool.release(self.conn)
            self.conn = None


# Функция для миграции legacy-кода на pool
def migrate_to_pool(legacy_func):
    """
    Декоратор для миграции legacy-функций на использование пула.

    Пример:
        @migrate_to_pool
        async def get_viewer(username):
            async with aiosqlite.connect(db.db_path) as conn:
                ...
    """
    import functools

    @functools.wraps(legacy_func)
    async def wrapper(*args, **kwargs):
        db_path = kwargs.get("db_path") or (
            getattr(args[0], "db_path", None) if args else None
        )
        conn = None
        try:
            pool = get_db_pool(db_path)
            await pool.initialize()
            conn = await pool.acquire()
            return await legacy_func(conn=conn, **kwargs)
        finally:
            if conn is not None:
                await pool.release(conn)

    return wrapper
