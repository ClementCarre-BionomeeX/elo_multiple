from __future__ import annotations

import sqlite3
from pathlib import Path


def create_connection(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS players(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS groups(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS group_members(
            group_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            PRIMARY KEY (group_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS games(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ruleset_id TEXT NOT NULL,
            config_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS matches(
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            participant_ids_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT
        );

        CREATE TABLE IF NOT EXISTS rounds(
            id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            teams_json TEXT NOT NULL,
            outcome_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rating_events(
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            round_id TEXT NOT NULL,
            deltas_json TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ratings_current(
            group_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            player_id TEXT NOT NULL,
            rating REAL NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (group_id, game_id, player_id)
        );
        """
    )
    conn.commit()

