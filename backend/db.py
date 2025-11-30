import os
import psycopg
from psycopg.rows import dict_row

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://semantic:semantic@localhost:5433/semantic_markets",
)

def get_conn():
    return psycopg.connect(DB_DSN, row_factory=dict_row)



