# src/core/scheduler_manager.py
"""
Scheduler Manager for executing scheduled queries
Uses APScheduler for background job execution
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from typing import Dict, Optional
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)


class SchedulerManager:
    """
    Manages scheduled query execution using APScheduler
    """

    def __init__(
            self,
            schedules_db,
            query_executor,
            email_service,
            timezone: str = 'UTC'
    ):
        """
        Initialize scheduler

        Args:
            schedules_db: ScheduledQueriesDB instance
            query_executor: Function to execute queries
            email_service: EmailService instance
            timezone: Default timezone
        """
        self.schedules_db = schedules_db
        self.query_executor = query_executor
        self.email_service = email_service
        self.default_timezone = timezone

        # Configure APScheduler
        jobstores = {
            'default': MemoryJobStore()
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone=timezone
        )

        logger.info(f"✅ SchedulerManager initialized (timezone: {timezone})")

    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("🚀 Scheduler started")

    def shutdown(self):
        """Shutdown the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("🛑 Scheduler stopped")

    async def load_schedules(self):
        """Load all enabled schedules from database"""
        try:
            schedules = await self.schedules_db.get_all_enabled_schedules()

            logger.info(f"📋 Loading {len(schedules)} active schedules...")

            for schedule in schedules:
                try:
                    self.add_scheduled_job(schedule)
                except Exception as e:
                    logger.error(f"❌ Failed to load schedule {schedule['id']}: {e}")

            logger.info(f"✅ Loaded {len(schedules)} schedules")

        except Exception as e:
            logger.error(f"❌ Failed to load schedules: {e}")

    def add_scheduled_job(self, schedule: Dict):
        """
        Add or update scheduled job

        Args:
            schedule: Schedule dict from database
        """
        try:
            schedule_id = schedule['id']

            # Parse cron expression
            trigger = CronTrigger.from_crontab(
                schedule['cron_expression'],
                timezone=schedule.get('timezone', self.default_timezone)
            )

            # Calculate next run time
            next_run = trigger.get_next_fire_time(None, datetime.now(timezone.utc))

            # Add job
            self.scheduler.add_job(
                func=self._execute_scheduled_query,
                trigger=trigger,
                args=[schedule_id],
                id=schedule_id,
                replace_existing=True,
                name=schedule['name']
            )

            # Update next_run in database
            asyncio.create_task(
                self.schedules_db.update_schedule(
                    schedule_id,
                    {'next_run': next_run.isoformat() if next_run else None}
                )
            )

            logger.info(f"✅ Scheduled: {schedule['name']} (next run: {next_run})")

        except Exception as e:
            logger.error(f"❌ Failed to add schedule {schedule.get('name')}: {e}")
            raise

    def remove_job(self, schedule_id: str):
        """Remove scheduled job"""
        try:
            self.scheduler.remove_job(schedule_id)
            logger.info(f"✅ Removed schedule: {schedule_id}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to remove job {schedule_id}: {e}")

    async def _execute_scheduled_query(self, schedule_id: str):
        """
        Execute a scheduled query

        Args:
            schedule_id: Schedule ID to execute
        """
        started_at = datetime.now()
        execution_id = None

        try:
            # Get schedule
            schedule = await self.schedules_db.get_schedule(schedule_id)

            if not schedule or not schedule['enabled']:
                logger.warning(f"⚠️  Schedule {schedule_id} not found or disabled")
                return

            logger.info(f"▶️  Executing: {schedule['name']}")

            # Execute query
            result = await self.query_executor(
                query_id=schedule['query_id'],
                user_id=schedule['user_id']
            )

            completed_at = datetime.now()

            # Log execution
            execution = await self.schedules_db.add_execution_log(
                schedule_id=schedule_id,
                status='success',
                started_at=started_at,
                completed_at=completed_at,
                rows_returned=len(result['data']) if result else 0
            )
            execution_id = execution['id']

            # Format result
            from src.core.result_formatters import format_result

            formatted = format_result(
                columns=result['columns'],
                data=result['data'],
                format_type=schedule['format'],
                schedule_name=schedule['name']
            )

            # Create email body
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            email_body = self.email_service.create_report_email(
                schedule_name=schedule['name'],
                rows_count=len(result['data']),
                execution_time_ms=duration_ms,
                custom_body=schedule.get('email_body')
            )

            # Send email
            await self.email_service.send_email(
                recipients=schedule['email_recipients'],
                subject=schedule.get('email_subject') or f"SQLatte Report: {schedule['name']}",
                body=email_body,
                attachments=[{
                    'filename': formatted['filename'],
                    'content': formatted['content']
                }],
                html=True
            )

            # Log email delivery
            for recipient in schedule['email_recipients']:
                await self.schedules_db.log_email_delivery(
                    execution_id=execution_id,
                    recipient=recipient,
                    status='sent'
                )

            # Update schedule stats
            await self.schedules_db.update_schedule_stats(
                schedule_id=schedule_id,
                last_run=completed_at
            )

            logger.info(f"✅ Executed: {schedule['name']} ({len(result['data'])} rows, {duration_ms}ms)")

        except Exception as e:
            completed_at = datetime.now()
            error_message = str(e)

            logger.error(f"❌ Execution failed for {schedule_id}: {error_message}")

            # Log failure
            try:
                schedule = await self.schedules_db.get_schedule(schedule_id)

                execution = await self.schedules_db.add_execution_log(
                    schedule_id=schedule_id,
                    status='failed',
                    started_at=started_at,
                    completed_at=completed_at,
                    error_message=error_message
                )
                execution_id = execution['id']

                # Send error notification
                if schedule and self.email_service.enabled:
                    error_body = self.email_service.create_error_email(
                        schedule_name=schedule['name'],
                        error_message=error_message,
                        timestamp=completed_at
                    )

                    await self.email_service.send_email(
                        recipients=schedule['email_recipients'],
                        subject=f"❌ Failed: {schedule['name']}",
                        body=error_body,
                        html=True
                    )

                    # Log email
                    for recipient in schedule['email_recipients']:
                        await self.schedules_db.log_email_delivery(
                            execution_id=execution_id,
                            recipient=recipient,
                            status='sent'
                        )

            except Exception as log_error:
                logger.error(f"❌ Failed to log error: {log_error}")

    async def execute_now(self, schedule_id: str):
        """
        Manually execute a schedule immediately

        Args:
            schedule_id: Schedule ID to execute
        """
        logger.info(f"▶️  Manual execution requested: {schedule_id}")
        await self._execute_scheduled_query(schedule_id)

    def get_job_info(self, schedule_id: str) -> Optional[Dict]:
        """Get information about a scheduled job"""
        try:
            job = self.scheduler.get_job(schedule_id)
            if job:
                return {
                    'id': job.id,
                    'name': job.name,
                    'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger)
                }
        except Exception:
            pass
        return None

    def get_all_jobs(self) -> list:
        """Get all scheduled jobs"""
        jobs = self.scheduler.get_jobs()
        return [
            {
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None
            }
            for job in jobs
        ]


# Helper function to create cron expression from frequency
def create_cron_expression(frequency: str, time: str = "09:00", day_of_week: Optional[str] = None) -> str:
    """
    Create cron expression from frequency

    Args:
        frequency: 'daily', 'weekly', 'monthly'
        time: Time in HH:MM format (24-hour)
        day_of_week: For weekly (0=Monday, 6=Sunday)

    Returns:
        Cron expression string
    """
    hour, minute = time.split(':')

    if frequency == 'daily':
        # Run every day at specified time
        return f"{minute} {hour} * * *"

    elif frequency == 'weekly':
        # Run every week on specified day
        dow = day_of_week if day_of_week else '1'  # Default Monday
        return f"{minute} {hour} * * {dow}"

    elif frequency == 'monthly':
        # Run on 1st of every month
        return f"{minute} {hour} 1 * *"

    else:
        # Default to daily
        return f"{minute} {hour} * * *"

# Example cron expressions:
# "0 9 * * *"        - Every day at 9:00 AM
# "0 9 * * 1"        - Every Monday at 9:00 AM
# "0 9 1 * *"        - 1st of every month at 9:00 AM
# "0 */6 * * *"      - Every 6 hours
# "0 9 * * 1-5"      - Weekdays at 9:00 AM
# "30 8,12,17 * * *" - At 8:30, 12:30, 17:30 every day