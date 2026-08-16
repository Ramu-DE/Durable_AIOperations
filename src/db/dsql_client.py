"""Aurora DSQL connection factory using IAM token authentication."""
import os
import boto3
import psycopg


def _generate_token(endpoint: str, region: str) -> str:
    # Build session explicitly from env vars so any AWS_* overrides take effect
    # even when an EC2 instance role exists (instance role is lower priority but
    # boto3's default session may have cached it before env vars were set).
    session_kwargs = {}
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        session_kwargs["aws_access_key_id"]     = os.environ["AWS_ACCESS_KEY_ID"]
        session_kwargs["aws_secret_access_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
    if os.environ.get("AWS_SESSION_TOKEN"):
        session_kwargs["aws_session_token"] = os.environ["AWS_SESSION_TOKEN"]
    session = boto3.Session(**session_kwargs)
    client = session.client("dsql", region_name=region)
    return client.generate_db_connect_admin_auth_token(
        Hostname=endpoint,
        Region=region,
        ExpiresIn=900,
    )


def get_connection(endpoint: str | None = None) -> psycopg.Connection:
    """Return a psycopg3 connection to Aurora DSQL.

    Reads DSQL_ENDPOINT and AWS_DEFAULT_REGION from env if not supplied.
    IAM token is generated fresh each call; connections should be short-lived.
    """
    endpoint = endpoint or os.environ["DSQL_ENDPOINT"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    token = _generate_token(endpoint, region)

    conninfo = (
        f"host={endpoint} port=5432 dbname=postgres user=admin "
        f"password={token} sslmode=require"
    )
    conn = psycopg.connect(conninfo, autocommit=False)
    return conn
