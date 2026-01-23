# src/core/scheduled_queries_db.py
"""
Database layer for scheduled queries
Handles CRUD operations for schedules and execution history
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from uuid import UUID, uuid4
import json
import logging

logger = logging.getLogger(__name__)


class ScheduledQueriesDB:
    """
    In-memory storage for scheduled queries
    Can be extended to PostgreSQL later
    """

    def __init__(self):
        self.schedules: Dict[str, Dict] = {}
        self.executions: Dict[str, List[Dict]] = {}
        self.email_deliveries: Dict[str, List[Dict]] = {}
        logger.info("✅ ScheduledQueriesDB initialized (in-memory)")

    # ============================================
    # SCHEDULES
    # ============================================

    async def create_schedule(self, schedule_data: Dict) -> Dict:
        """Create new scheduled query"""
        schedule_id = str(uuid4())

        schedule = {
            'id': schedule_id,
            'user_id': schedule_data.get('user_id'),
            'query_id': schedule_data.get('query_id'),
            'name': schedule_data.get('name'),
            'description': schedule_data.get('description'),

            # Schedule
            'frequency': schedule_data.get('frequency'),
            'cron_expression': schedule_data.get('cron_expression'),
            'timezone': schedule_data.get('timezone', 'UTC'),

            # Delivery
            'email_recipients': schedule_data.get('email_recipients', []),
            'email_subject': schedule_data.get('email_subject'),
            'email_body': schedule_data.get('email_body'),
            'format': schedule_data.get('format', 'excel'),

            # Status
            'enabled': schedule_data.get('enabled', True),
            'last_run': None,
            'next_run': None,
            'run_count': 0,

            # Metadata
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }

        self.schedules[schedule_id] = schedule
        self.executions[schedule_id] = []

        logger.info(f"✅ Created schedule: {schedule['name']} (ID: {schedule_id})")
        return schedule

    async def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        """Get schedule by ID"""
        return self.schedules.get(schedule_id)

    async def get_schedules(
            self,
            user_id: str,
            enabled: Optional[bool] = None
    ) -> List[Dict]:
        """Get all schedules for user"""
        schedules = [
            s for s in self.schedules.values()
            if s['user_id'] == user_id
        ]

        if enabled is not None:
            schedules = [s for s in schedules if s['enabled'] == enabled]

        # Sort by created_at desc
        schedules.sort(key=lambda x: x['created_at'], reverse=True)

        return schedules

    async def get_all_schedules(
            self,
            enabled: Optional[bool] = None
    ) -> List[Dict]:
        """
        Get ALL schedules from all users (admin mode)
        """
        schedules = list(self.schedules.values())

        if enabled is not None:
            schedules = [s for s in schedules if s['enabled'] == enabled]

        # Sort by created_at desc
        schedules.sort(key=lambda x: x['created_at'], reverse=True)

        return schedules

    async def get_all_enabled_schedules(self) -> List[Dict]:
        """Get all enabled schedules (for scheduler)"""
        return [
            s for s in self.schedules.values()
            if s['enabled']
        ]

    async def update_schedule(self, schedule_id: str, updates: Dict) -> Dict:
        """Update schedule"""
        if schedule_id not in self.schedules:
            raise ValueError(f"Schedule not found: {schedule_id}")

        schedule = self.schedules[schedule_id]

        # Update fields
        for key, value in updates.items():
            if key in schedule and key not in ['id', 'user_id', 'created_at']:
                schedule[key] = value

        schedule['updated_at'] = datetime.now().isoformat()

        logger.info(f"✅ Updated schedule: {schedule_id}")
        return schedule

    async def update_schedule_stats(
            self,
            schedule_id: str,
            last_run: datetime,
            next_run: Optional[datetime] = None
    ):
        """Update schedule run statistics"""
        if schedule_id not in self.schedules:
            return

        schedule = self.schedules[schedule_id]
        schedule['last_run'] = last_run.isoformat()
        if next_run:
            schedule['next_run'] = next_run.isoformat()
        schedule['run_count'] += 1
        schedule['updated_at'] = datetime.now().isoformat()

    async def delete_schedule(self, schedule_id: str) -> bool:
        """Delete schedule"""
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
            if schedule_id in self.executions:
                del self.executions[schedule_id]
            logger.info(f"✅ Deleted schedule: {schedule_id}")
            return True
        return False

    # ============================================
    # EXECUTIONS
    # ============================================

    async def add_execution_log(
            self,
            schedule_id: str,
            status: str,
            started_at: datetime,
            completed_at: Optional[datetime] = None,
            rows_returned: Optional[int] = None,
            error_message: Optional[str] = None
    ) -> Dict:
        """Log execution"""
        execution_id = str(uuid4())

        duration_ms = None
        if completed_at and started_at:
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        execution = {
            'id': execution_id,
            'schedule_id': schedule_id,
            'status': status,
            'started_at': started_at.isoformat(),
            'completed_at': completed_at.isoformat() if completed_at else None,
            'duration_ms': duration_ms,
            'rows_returned': rows_returned,
            'error_message': error_message,
            'error_stack': None
        }

        if schedule_id not in self.executions:
            self.executions[schedule_id] = []

        self.executions[schedule_id].insert(0, execution)  # Most recent first

        # Keep only last 100 executions per schedule
        if len(self.executions[schedule_id]) > 100:
            self.executions[schedule_id] = self.executions[schedule_id][:100]

        logger.info(f"✅ Logged execution: {execution_id} - {status}")
        return execution

    async def get_executions(
            self,
            schedule_id: str,
            limit: int = 50
    ) -> List[Dict]:
        """Get execution history for schedule"""
        executions = self.executions.get(schedule_id, [])
        return executions[:limit]

    async def get_execution_stats(self, schedule_id: str) -> Dict:
        """Get execution statistics"""
        executions = self.executions.get(schedule_id, [])

        if not executions:
            return {
                'total_runs': 0,
                'success_count': 0,
                'failure_count': 0,
                'success_rate': 0,
                'avg_duration_ms': 0
            }

        success_count = len([e for e in executions if e['status'] == 'success'])
        failure_count = len([e for e in executions if e['status'] == 'failed'])

        durations = [e['duration_ms'] for e in executions if e['duration_ms']]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            'total_runs': len(executions),
            'success_count': success_count,
            'failure_count': failure_count,
            'success_rate': (success_count / len(executions)) * 100 if executions else 0,
            'avg_duration_ms': avg_duration
        }

    # ============================================
    # EMAIL DELIVERIES
    # ============================================

    async def log_email_delivery(
            self,
            execution_id: str,
            recipient: str,
            status: str,
            error_message: Optional[str] = None
    ):
        """Log email delivery status"""
        delivery = {
            'id': str(uuid4()),
            'execution_id': execution_id,
            'recipient': recipient,
            'status': status,
            'sent_at': datetime.now().isoformat(),
            'error_message': error_message
        }

        if execution_id not in self.email_deliveries:
            self.email_deliveries[execution_id] = []

        self.email_deliveries[execution_id].append(delivery)
        logger.info(f"✅ Logged email delivery: {recipient} - {status}")

    async def get_email_deliveries(self, execution_id: str) -> List[Dict]:
        """Get email deliveries for execution"""
        return self.email_deliveries.get(execution_id, [])


# PostgreSQL implementation (for production)
class ScheduledQueriesDBPostgres:
    """
    PostgreSQL storage for scheduled queries
    Use when analytics.enabled = true
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool = None
        logger.info("✅ ScheduledQueriesDBPostgres initialized")

    async def initialize(self):
        """Initialize database connection pool"""
        import asyncpg
        self.pool = await asyncpg.create_pool(self.connection_string)
        await self._create_tables()

    async def _create_tables(self):
        """Create tables if they don't exist"""
        async with self.pool.acquire() as conn:
            # Scheduled Queries table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_queries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    query_id VARCHAR(255) NOT NULL,

                    name VARCHAR(255) NOT NULL,
                    description TEXT,

                    frequency VARCHAR(50) NOT NULL,
                    cron_expression VARCHAR(100) NOT NULL,
                    timezone VARCHAR(100) DEFAULT 'UTC',

                    email_recipients TEXT[] NOT NULL,
                    email_subject VARCHAR(255),
                    email_body TEXT,
                    format VARCHAR(20) DEFAULT 'excel',

                    enabled BOOLEAN DEFAULT TRUE,
                    last_run TIMESTAMP,
                    next_run TIMESTAMP,
                    run_count INTEGER DEFAULT 0,

                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Execution History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schedule_executions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    schedule_id UUID NOT NULL,

                    status VARCHAR(20) NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    duration_ms INTEGER,

                    rows_returned INTEGER,
                    file_size_bytes INTEGER,

                    error_message TEXT,
                    error_stack TEXT,

                    FOREIGN KEY (schedule_id) REFERENCES scheduled_queries(id) ON DELETE CASCADE
                )
            """)

            # Email Deliveries table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS email_deliveries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    execution_id UUID NOT NULL,

                    recipient VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    sent_at TIMESTAMP,

                    error_message TEXT,

                    FOREIGN KEY (execution_id) REFERENCES schedule_executions(id) ON DELETE CASCADE
                )
            """)

            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedules_user_enabled 
                ON scheduled_queries(user_id, enabled)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_schedules_next_run 
                ON scheduled_queries(next_run) WHERE enabled = TRUE
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_executions_schedule 
                ON schedule_executions(schedule_id, started_at DESC)
            """)

            logger.info("✅ Database tables created/verified")

    # Implement same methods as ScheduledQueriesDB but with PostgreSQL
    # (Full implementation would follow same pattern as analytics_db_postgres.py)

    async def create_schedule(self, schedule_data: Dict) -> Dict:
        """Create new scheduled query in PostgreSQL"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO scheduled_queries (
                    user_id, query_id, name, description,
                    frequency, cron_expression, timezone,
                    email_recipients, email_subject, email_body, format,
                    enabled
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING *
            """,
                                      schedule_data['user_id'],
                                      schedule_data['query_id'],
                                      schedule_data['name'],
                                      schedule_data.get('description'),
                                      schedule_data['frequency'],
                                      schedule_data['cron_expression'],
                                      schedule_data.get('timezone', 'UTC'),
                                      schedule_data['email_recipients'],
                                      schedule_data.get('email_subject'),
                                      schedule_data.get('email_body'),
                                      schedule_data.get('format', 'excel'),
                                      schedule_data.get('enabled', True)
                                      )

            return dict(row)

    # ... (other methods would be implemented similarly)


# ============================================
# POSTGRESQL IMPLEMENTATION (FULL)
# ============================================

class ScheduledQueriesDBPostgres:
    """
    PostgreSQL storage for scheduled queries with FULL implementation
    Auto-creates tables, handles job persistence
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool = None
        logger.info("✅ ScheduledQueriesDBPostgres initialized")

    async def initialize(self):
        """Initialize database connection pool and create tables"""
        import asyncpg
        try:
            self.pool = await asyncpg.create_pool(self.connection_string)
            await self._create_tables()
            logger.info("✅ ScheduledQueriesDBPostgres tables ready")
        except Exception as e:
            logger.error(f"❌ Failed to initialize PostgreSQL scheduler DB: {e}")
            raise

    async def _create_tables(self):
        """Create all scheduler-related tables"""
        async with self.pool.acquire() as conn:
            # Scheduled Queries table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_queries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    query_id VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    frequency VARCHAR(50) NOT NULL,
                    cron_expression VARCHAR(100) NOT NULL,
                    timezone VARCHAR(100) DEFAULT 'UTC',
                    email_recipients TEXT[] NOT NULL,
                    email_subject VARCHAR(255),
                    email_body TEXT,
                    format VARCHAR(20) DEFAULT 'excel',
                    enabled BOOLEAN DEFAULT TRUE,
                    last_run TIMESTAMP,
                    next_run TIMESTAMP,
                    run_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # APScheduler Job States table - Let SQLAlchemy manage this
            # APScheduler's SQLAlchemyJobStore will create the table with correct types
            # We don't manually create it to avoid type mismatches

            # Execution History table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schedule_executions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    schedule_id UUID NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    duration_ms INTEGER,
                    rows_returned INTEGER,
                    file_size_bytes INTEGER,
                    error_message TEXT,
                    error_stack TEXT,
                    FOREIGN KEY (schedule_id) REFERENCES scheduled_queries(id) ON DELETE CASCADE
                )
            """)

            # Email Deliveries table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS email_deliveries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    execution_id UUID NOT NULL,
                    recipient VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    sent_at TIMESTAMP DEFAULT NOW(),
                    error_message TEXT,
                    FOREIGN KEY (execution_id) REFERENCES schedule_executions(id) ON DELETE CASCADE
                )
            """)

            # Create indexes
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_user_enabled ON scheduled_queries(user_id, enabled)")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON scheduled_queries(next_run) WHERE enabled = TRUE")
            # APScheduler will create its own indexes for apscheduler_jobs table
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_executions_schedule ON schedule_executions(schedule_id, started_at DESC)")

            logger.info("✅ All scheduler tables created/verified")

    # Copy all methods from ScheduledQueriesDB with PostgreSQL implementation
    async def create_schedule(self, schedule_data: Dict) -> Dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO scheduled_queries (
                    user_id, query_id, name, description,
                    frequency, cron_expression, timezone,
                    email_recipients, email_subject, email_body, format, enabled
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING *
            """, schedule_data['user_id'], schedule_data['query_id'], schedule_data['name'],
                                      schedule_data.get('description'), schedule_data['frequency'],
                                      schedule_data['cron_expression'],
                                      schedule_data.get('timezone', 'UTC'), schedule_data['email_recipients'],
                                      schedule_data.get('email_subject'), schedule_data.get('email_body'),
                                      schedule_data.get('format', 'excel'), schedule_data.get('enabled', True))

            return self._row_to_dict(row)

    async def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM scheduled_queries WHERE id = $1", schedule_id)
            return self._row_to_dict(row) if row else None

    async def get_schedules(self, user_id: str, enabled: Optional[bool] = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            if enabled is not None:
                rows = await conn.fetch(
                    "SELECT * FROM scheduled_queries WHERE user_id = $1 AND enabled = $2 ORDER BY created_at DESC",
                    user_id, enabled)
            else:
                rows = await conn.fetch("SELECT * FROM scheduled_queries WHERE user_id = $1 ORDER BY created_at DESC",
                                        user_id)
            return [self._row_to_dict(row) for row in rows]

    async def get_all_schedules(self, enabled: Optional[bool] = None) -> List[Dict]:
        async with self.pool.acquire() as conn:
            if enabled is not None:
                rows = await conn.fetch("SELECT * FROM scheduled_queries WHERE enabled = $1 ORDER BY created_at DESC",
                                        enabled)
            else:
                rows = await conn.fetch("SELECT * FROM scheduled_queries ORDER BY created_at DESC")
            return [self._row_to_dict(row) for row in rows]

    async def get_all_enabled_schedules(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM scheduled_queries WHERE enabled = TRUE ORDER BY next_run NULLS LAST")
            return [self._row_to_dict(row) for row in rows]

    async def update_schedule(self, schedule_id: str, updates: Dict) -> Dict:
        allowed_fields = ['name', 'description', 'frequency', 'cron_expression', 'timezone',
                          'email_recipients', 'email_subject', 'email_body', 'format',
                          'enabled', 'last_run', 'next_run', 'run_count']

        set_clauses = []
        values = []
        param_count = 1

        for key, value in updates.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = ${param_count}")
                values.append(value)
                param_count += 1

        if not set_clauses:
            return await self.get_schedule(schedule_id)

        set_clauses.append(f"updated_at = ${param_count}")
        values.append(datetime.now())
        param_count += 1
        values.append(schedule_id)

        query = f"UPDATE scheduled_queries SET {', '.join(set_clauses)} WHERE id = ${param_count} RETURNING *"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *values)
            return self._row_to_dict(row)

    async def update_schedule_stats(self, schedule_id: str, last_run: datetime, next_run: Optional[datetime] = None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE scheduled_queries 
                SET last_run = $1, next_run = $2, run_count = run_count + 1, updated_at = NOW()
                WHERE id = $3
            """, last_run, next_run, schedule_id)

    async def delete_schedule(self, schedule_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM scheduled_queries WHERE id = $1", schedule_id)
            return result.split()[-1] == '1'

    async def add_execution_log(self, schedule_id: str, status: str, started_at: datetime,
                                completed_at: Optional[datetime] = None, rows_returned: Optional[int] = None,
                                error_message: Optional[str] = None) -> Dict:
        duration_ms = int((completed_at - started_at).total_seconds() * 1000) if completed_at and started_at else None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO schedule_executions (schedule_id, status, started_at, completed_at, duration_ms, rows_returned, error_message)
                VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *
            """, schedule_id, status, started_at, completed_at, duration_ms, rows_returned, error_message)
            return self._row_to_dict(row)

    async def get_executions(self, schedule_id: str, limit: int = 50) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM schedule_executions WHERE schedule_id = $1 ORDER BY started_at DESC LIMIT $2",
                schedule_id, limit)
            return [self._row_to_dict(row) for row in rows]

    async def get_execution_stats(self, schedule_id: str) -> Dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as total_runs,
                       COUNT(*) FILTER (WHERE status = 'success') as success_count,
                       COUNT(*) FILTER (WHERE status = 'failed') as failure_count,
                       AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) as avg_duration_ms
                FROM schedule_executions WHERE schedule_id = $1
            """, schedule_id)

            if not row or row['total_runs'] == 0:
                return {'total_runs': 0, 'success_count': 0, 'failure_count': 0, 'success_rate': 0,
                        'avg_duration_ms': 0}

            total = row['total_runs']
            success = row['success_count'] or 0
            return {
                'total_runs': total,
                'success_count': success,
                'failure_count': row['failure_count'] or 0,
                'success_rate': (success / total * 100) if total > 0 else 0,
                'avg_duration_ms': int(row['avg_duration_ms']) if row['avg_duration_ms'] else 0
            }

    async def log_email_delivery(self, execution_id: str, recipient: str, status: str,
                                 error_message: Optional[str] = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO email_deliveries (execution_id, recipient, status, error_message) VALUES ($1, $2, $3, $4)",
                execution_id, recipient, status, error_message)

    async def get_email_deliveries(self, execution_id: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM email_deliveries WHERE execution_id = $1 ORDER BY sent_at DESC",
                                    execution_id)
            return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row) -> Dict:
        result = dict(row)
        # Convert UUIDs to strings
        for key in ['id', 'schedule_id', 'execution_id']:
            if key in result:
                result[key] = str(result[key])
        # Convert timestamps to ISO strings
        for key in ['created_at', 'updated_at', 'started_at', 'completed_at', 'last_run', 'next_run', 'sent_at']:
            if key in result and result[key] and isinstance(result[key], datetime):
                result[key] = result[key].isoformat()
        return result

    async def close(self):
        if self.pool:
            await self.pool.close()