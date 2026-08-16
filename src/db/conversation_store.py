"""Conversation and message persistence — adapted for official workshop schema."""
import json
import psycopg


def create_conversation(
    conn: psycopg.Connection,
    conversation_id: str,   # UUID string
    user_id: str,
    region: str = "",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, status)
            VALUES (%s::uuid, %s, 'active')
            ON CONFLICT (conversation_id) DO NOTHING
            """,
            (conversation_id, user_id),
        )
    conn.commit()


def next_seq(conn: psycopg.Connection, conversation_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = %s::uuid",
            (conversation_id,),
        )
        return cur.fetchone()[0]


def append_message(
    conn: psycopg.Connection,
    message_id: str,        # UUID string
    conversation_id: str,   # UUID string
    seq: int,
    role: str,
    content,                # str or dict — stored as JSONB
) -> None:
    # messages.content is JSONB — wrap plain strings
    if isinstance(content, str):
        content_json = json.dumps({"text": content})
    else:
        content_json = json.dumps(content)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages (message_id, conversation_id, seq, role, content)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb)
            ON CONFLICT (message_id) DO NOTHING
            """,
            (message_id, conversation_id, seq, role, content_json),
        )
        cur.execute(
            "UPDATE conversations SET updated_at = now() WHERE conversation_id = %s::uuid",
            (conversation_id,),
        )
    conn.commit()


def get_messages(conn: psycopg.Connection, conversation_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT message_id, seq, role, content, created_at
            FROM messages
            WHERE conversation_id = %s::uuid
            ORDER BY seq
            """,
            (conversation_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "message_id": str(r[0]),
            "seq": r[1],
            "role": r[2],
            "content": r[3],
            "created_at": r[4].isoformat(),
        }
        for r in rows
    ]
