import os
from datetime import datetime
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from typing import Dict, Any, List
from psycopg2.extras import execute_values

load_dotenv()

class Database:
    def __init__(self):
        self.db_config = {
            'dbname': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432')
        }
        self.connection_pool = None

    def create_pool(self):
        """Create a connection pool"""
        try:
            self.db_config.update({
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5
            })
            self.connection_pool = pool.SimpleConnectionPool(5, 20, **self.db_config)
            print('Connection pool created successfully')
        except psycopg2.Error as e:
            print(f"Error creating connection pool: {e}")
            raise

    def get_connection(self):
        if self.connection_pool is None:
            self.create_pool()
        return self.connection_pool.getconn()

    def release_connection(self, conn):
        self.connection_pool.putconn(conn)

    def setup_database(self):
        """Initialize TimescaleDB"""
        conn = None
        cur = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()


            cur.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                timestamp TIMESTAMPTZ NOT NULL,
                value FLOAT,
                pattern TEXT,
            );
            """)

            # Create hypertable with chunk size
            # Assuming each row is 100 bytes, targeting roughly 100MB chunks
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
                time_bucket('1 hour', timestamp) as bucket,
                AVG(value) as avg_value,
                COUNT(*) as reading_count
            FROM sensor_data
            GROUP BY bucket;
            """)


            # Add retention policy (keep data for a year for now), can be tweaked.
            cur.execute("""
            SELECT add_retention_policy('sensor_data', 
                INTERVAL '12 months', 
                if_not_exists => TRUE);
            """)

            # Compression optimizations
            cur.execute("""
            ALTER TABLE sensor_data SET (
                timescaledb.compress,
                timescaledb.compress_orderby = 'timestamp DESC'
            );
            """)

            # Add compression policy
            cur.execute("""
            SELECT add_compression_policy('sensor_data', 
                INTERVAL '7 days',
                if_not_exists => TRUE);
            """)

            conn.commit()
            print('Database setup complete with optimizations')
        except psycopg2.Error as e:
            print(f"Error setting up database: {e}")
            raise
        finally:
            if cur:
                cur.close()
            if conn:
                self.release_connection(conn)

    def batch_store_data(self, data_points: List[Dict[str, Any]], batch_size: int = 1000):
        """Store multiple data points"""
        conn = None
        cur = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            # Prepare data for batch insert
            values = [(
                point.get('timestamp', datetime.now()),
                point.get('value'),
                point.get('pattern')
            ) for point in data_points]

            # Use execute_values for efficient batch insertion
            execute_values(
                cur,
                """
                INSERT INTO sensor_data 
                (timestamp, value, pattern)
                VALUES %s
                """,
                values,
                page_size=batch_size
            )
            conn.commit()
        except psycopg2.Error as e:
            print(f"Error storing data: {e}")
            raise
        finally:
            if cur:
                cur.close()
            if conn:
                self.release_connection(conn)

    def get_recent_data(self, hours: int = 24):
        """Retrieve recent data for a user"""
        conn = None
        cur = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            cur.execute("""
            SELECT timestamp, value, pattern
            FROM sensor_data
            WHERE timestamp > NOW() - INTERVAL '%s hours'
            ORDER BY timestamp DESC
            """, (hours,))

            return cur.fetchall()
        except psycopg2.Error as e:
            print(f"Error retrieving data: {e}")
            raise
        finally:
            if cur:
                cur.close()
            if conn:
                self.release_connection(conn)

    def close_pool(self):
        if self.connection_pool:
            self.connection_pool.closeall()
            print("Connection pool closed")