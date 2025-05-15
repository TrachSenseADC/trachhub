import os
from datetime import datetime
import psycopg2
from psycopg2 import pool, sql
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional, Tuple
from psycopg2.extras import execute_values

load_dotenv()

class Database:
    def __init__(self):
        self.db_config = {
            'dbname': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'keepalives':          1,
            'keepalives_idle':     30,
            'keepalives_interval': 10,
            'keepalives_count':    5,
        }
        self._pool: Optional[pool.SimpleConnectionPool] = None

    def _ensure_pool(self) -> pool.SimpleConnectionPool:
        if not self._pool:
            self._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                **self._db_config
            )
        return self._pool

    def get_connection(self) -> psycopg2.extensions.connection:
        return self._ensure_pool().getconn()

    def release_connection(self, conn: psycopg2.extensions.connection) -> None:
        if self._pool:
            self._pool.putconn(conn)

    def close_pool(self) -> None:
        if self._pool:
            self._pool.closeall()
            self._pool = None
            print("Connection pool closed")

    def setup_database(self):
        """Create TimescaleDB hypertable and set up initial schema"""
        conn = self.get_connection()

        try:
            with conn.cursor() as cur:
                cur = conn.cursor()

                # sensor_data table creation
                cur.execute("""
                CREATE TABLE IF NOT EXISTS sensor_data (
                    timestamp TIMESTAMPTZ NOT NULL,
                    value DOUBLE PRECISION,
                    pattern TEXT
                );
                """)

                # Create hypertable with chunk size
                cur.execute("""
                SELECT create_hypertable(
                    'sensor_data', 
                    'timestamp',
                    chunk_time_interval => INTERVAL '1 day',
                    if_not_exists => TRUE
                );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sensor_data_user_time 
                    ON sensor_data (timestamp DESC);
                """)

                cur.execute("""
                    CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_aggregates
                    WITH (timescaledb.continuous_aggregate='true')
                    AS SELECT
                        time_bucket('1 hour', timestamp) AS bucket,
                        AVG(value) AS avg_value,
                        COUNT(*) AS reading_count
                    FROM sensor_data
                    GROUP BY bucket;
                """)


                # retention policy to delete old data
                cur.execute("""
                SELECT add_retention_policy(
                    'sensor_data', 
                    INTERVAL '12 months', 
                    if_not_exists => TRUE
                    );
                """)

                # compression 
                cur.execute("""
                    ALTER TABLE sensor_data SET (
                        timescaledb.compress,
                        timescaledb.compress_orderby = 'timestamp DESC'
                    );
                """)
                cur.execute("""
                    SELECT add_compression_policy(
                        'sensor_data', 
                        INTERVAL '7 days',
                        if_not_exists => TRUE
                    );
                """)

            print('Database setup complete with optimizations')
        finally:
            self.release_connection(conn)

    def batch_store_data(self, data_points: List[Dict[str, Any]], batch_size: int = 1000) -> None:
        """Store multiple data points"""
        conn = self.get_connection()
        try:
            with conn, conn.cursor() as cur:
                records: List[Tuple[Any, ...]] = [
                    (
                        point.get('timestamp', datetime.utcnow()),
                        point.get('value'),
                        point.get('pattern')
                    )
                    for point in data_points
                ]

                execute_values(
                    cur,
                    """
                    INSERT INTO sensor_data 
                    (timestamp, value, pattern)
                    VALUES %s
                    """,
                    records,
                    page_size=batch_size
                )
        
        finally:
            self.release_connection(conn)

    def get_recent_data(self, hours: int = 24):
        """Retrieve recent data for a user"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("""
                SELECT timestamp, value, pattern
                FROM sensor_data
                WHERE timestamp > NOW() - INTERVAL %s
                ORDER BY timestamp DESC
                """), [f"{hours} hours"])
                return cur.fetchall()
        finally:
            self.release_connection(conn)
