"""M135: private skill-game sessions; never stored in public match_rooms.

The session, participant locks, deduplication receipts and result/rating commit
are atomic. Runtime leases distinguish server downtime from player inactivity.
"""


async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    await conn.executescript('''
        CREATE TABLE IF NOT EXISTS skillgame_runtimes (
            runtime_id TEXT PRIMARY KEY, last_seen REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skillgame_sessions (
            channel_id INTEGER NOT NULL, id TEXT NOT NULL,
            game_type TEXT NOT NULL CHECK(game_type IN ('battleship','minesweeper')),
            mode TEXT NOT NULL CHECK(mode IN ('ranked','practice')),
            difficulty TEXT, season_id INTEGER, status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0, secret_state TEXT, rules TEXT NOT NULL,
            created_at REAL NOT NULL, started_at REAL, expires_at REAL,
            runtime_id TEXT NOT NULL, generation_token TEXT,
            result TEXT, PRIMARY KEY(channel_id,id)
        );
        CREATE TABLE IF NOT EXISTS skillgame_players (
            channel_id INTEGER NOT NULL, session_id TEXT NOT NULL,
            username TEXT NOT NULL, mode TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(channel_id,session_id,username)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS skillgame_one_active_mode
            ON skillgame_players(channel_id,username) WHERE active=1;
        CREATE TABLE IF NOT EXISTS skillgame_queue (
            channel_id INTEGER NOT NULL, username TEXT NOT NULL,
            queued_at REAL NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY(channel_id,username)
        );
        CREATE TABLE IF NOT EXISTS skillgame_requests (
            channel_id INTEGER NOT NULL, username TEXT NOT NULL,
            request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            session_id TEXT, response TEXT, http_status INTEGER,
            created_at REAL NOT NULL,
            PRIMARY KEY(channel_id,username,request_id)
        );
        CREATE TABLE IF NOT EXISTS skillgame_results (
            channel_id INTEGER NOT NULL, session_id TEXT NOT NULL,
            game_type TEXT NOT NULL, mode TEXT NOT NULL,
            season_id INTEGER, outcome TEXT NOT NULL, reason TEXT NOT NULL,
            result TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY(channel_id,session_id)
        );
        CREATE TABLE IF NOT EXISTS skillgame_season_closures (
            channel_id INTEGER NOT NULL, game_type TEXT NOT NULL,
            season_id INTEGER NOT NULL, reason TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY(channel_id,season_id)
        );
        CREATE INDEX IF NOT EXISTS skillgame_sessions_status
            ON skillgame_sessions(channel_id,status,created_at);
        CREATE INDEX IF NOT EXISTS skillgame_runtime_deadlines
            ON skillgame_sessions(runtime_id,status,expires_at);
        CREATE INDEX IF NOT EXISTS skillgame_player_history
            ON skillgame_players(channel_id,username,active,session_id);
        CREATE INDEX IF NOT EXISTS skillgame_sessions_retention
            ON skillgame_sessions(channel_id,created_at);
        CREATE INDEX IF NOT EXISTS skillgame_requests_retention
            ON skillgame_requests(channel_id,created_at);
        CREATE INDEX IF NOT EXISTS skillgame_queue_age
            ON skillgame_queue(channel_id,queued_at);
    ''')
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M135.skillgames')")
    await conn.commit()
