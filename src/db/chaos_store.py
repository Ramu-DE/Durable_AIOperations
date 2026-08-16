"""Chaos flag store — uses workshop_chaos.is_dead (official schema)."""
import psycopg


def is_region_disabled(conn: psycopg.Connection, region: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT is_dead FROM workshop_chaos WHERE region = %s", (region,))
        row = cur.fetchone()
    return bool(row[0]) if row else False


def disable_region(conn: psycopg.Connection, region: str, reason: str = "") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workshop_chaos (region, is_dead, killed_at, updated_at)
            VALUES (%s, TRUE, now(), now())
            ON CONFLICT (region) DO UPDATE
              SET is_dead = TRUE, killed_at = now(), updated_at = now()
            """,
            (region,),
        )
    conn.commit()


def enable_region(conn: psycopg.Connection, region: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workshop_chaos (region, is_dead, killed_at, updated_at)
            VALUES (%s, FALSE, NULL, now())
            ON CONFLICT (region) DO UPDATE
              SET is_dead = FALSE, killed_at = NULL, updated_at = now()
            """,
            (region,),
        )
    conn.commit()


def get_all_regions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT region, is_dead, killed_at, updated_at FROM workshop_chaos ORDER BY region")
        rows = cur.fetchall()
    return [
        {
            "region": r[0],
            "is_dead": r[1],
            "killed_at": r[2].isoformat() if r[2] else None,
            "updated_at": r[3].isoformat() if r[3] else None,
        }
        for r in rows
    ]
