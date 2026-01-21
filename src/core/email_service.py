# src/core/email_service.py
"""
Email service for sending scheduled query results
Supports SMTP, with beautiful HTML templates
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Email service using SMTP"""

    def __init__(self, config: Dict):
        self.enabled = config.get('enabled', False)

        if not self.enabled:
            logger.info("📧 Email service disabled")
            return

        smtp_config = config.get('smtp', {})
        self.smtp_host = smtp_config.get('host')
        self.smtp_port = smtp_config.get('port', 587)
        self.smtp_user = smtp_config.get('user')
        self.smtp_password = smtp_config.get('password')
        self.from_email = smtp_config.get('from_email', 'noreply@sqlatte.com')
        self.from_name = smtp_config.get('from_name', 'SQLatte')

        # Validate config
        if not all([self.smtp_host, self.smtp_port]):
            logger.warning("⚠️  Email service enabled but SMTP config incomplete")
            self.enabled = False
            return

        logger.info(f"✅ Email service initialized: {self.from_email}")

    async def send_email(
            self,
            recipients: List[str],
            subject: str,
            body: str,
            attachments: Optional[List[Dict]] = None,
            html: bool = True
    ):
        """
        Send email with optional attachments

        Args:
            recipients: List of email addresses
            subject: Email subject
            body: Email body (HTML or plain text)
            attachments: List of dicts with 'filename' and 'content' (bytes)
            html: Whether body is HTML
        """
        if not self.enabled:
            logger.warning("📧 Email service disabled - skipping email")
            return

        try:
            msg = MIMEMultipart()
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject

            # Add body
            if html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))

            # Add attachments
            if attachments:
                for attachment in attachments:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment['content'])
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename={attachment["filename"]}'
                    )
                    msg.attach(part)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                #server.starttls()   # Uncomment if using TLS for google smtp
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"✅ Email sent to {len(recipients)} recipients: {subject}")

        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            raise

    def create_report_email(
            self,
            schedule_name: str,
            rows_count: int,
            execution_time_ms: int,
            custom_body: Optional[str] = None
    ) -> str:
        """Create beautiful HTML email for scheduled report"""

        timestamp = datetime.now().strftime('%B %d, %Y at %H:%M')

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 600px;
                    margin: 40px auto;
                    background: white;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%);
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    color: white;
                    font-size: 28px;
                    font-weight: 600;
                }}
                .header .subtitle {{
                    margin: 10px 0 0 0;
                    color: rgba(255, 255, 255, 0.9);
                    font-size: 14px;
                }}
                .content {{
                    padding: 30px;
                }}
                .content h2 {{
                    margin: 0 0 20px 0;
                    color: #333;
                    font-size: 20px;
                }}
                .content p {{
                    margin: 0 0 15px 0;
                    color: #666;
                    line-height: 1.6;
                }}
                .stats {{
                    display: flex;
                    justify-content: space-around;
                    margin: 30px 0;
                    padding: 20px;
                    background: #f9f9f9;
                    border-radius: 8px;
                }}
                .stat {{
                    text-align: center;
                }}
                .stat-value {{
                    display: block;
                    font-size: 28px;
                    font-weight: 700;
                    color: #D4A574;
                    margin-bottom: 5px;
                }}
                .stat-label {{
                    display: block;
                    font-size: 12px;
                    color: #888;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }}
                .attachment-info {{
                    background: #e8f4f8;
                    padding: 15px;
                    border-radius: 8px;
                    border-left: 4px solid #3b82f6;
                    margin: 20px 0;
                }}
                .attachment-info p {{
                    margin: 0;
                    color: #1e3a8a;
                    font-size: 14px;
                }}
                .footer {{
                    padding: 20px 30px;
                    background: #fafafa;
                    border-top: 1px solid #eee;
                    text-align: center;
                }}
                .footer p {{
                    margin: 5px 0;
                    font-size: 12px;
                    color: #999;
                }}
                .footer a {{
                    color: #D4A574;
                    text-decoration: none;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: linear-gradient(135deg, #D4A574 0%, #A67C52 100%);
                    color: white;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: 600;
                    margin: 10px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>☕ SQLatte Report</h1>
                    <p class="subtitle">{schedule_name}</p>
                </div>

                <div class="content">
                    <h2>Your scheduled report is ready!</h2>

                    {"<p>" + custom_body + "</p>" if custom_body else ""}

                    <div class="stats">
                        <div class="stat">
                            <span class="stat-value">{rows_count:,}</span>
                            <span class="stat-label">Rows</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value">{execution_time_ms:,}ms</span>
                            <span class="stat-label">Execution Time</span>
                        </div>
                    </div>

                    <div class="attachment-info">
                        <p>📎 <strong>Report attached</strong> - Download the attachment to view your complete results.</p>
                    </div>
                </div>

                <div class="footer">
                    <p>Generated on {timestamp}</p>
                    <p style="margin-top: 10px;">
                        Powered by <a href="#">SQLatte</a> ☕
                    </p>
                    <p style="font-size: 11px; color: #bbb; margin-top: 15px;">
                        To modify or unsubscribe from this schedule, visit your SQLatte dashboard.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        return html

    def create_error_email(
            self,
            schedule_name: str,
            error_message: str,
            timestamp: datetime
    ) -> str:
        """Create error notification email"""

        time_str = timestamp.strftime('%B %d, %Y at %H:%M')

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 600px;
                    margin: 40px auto;
                    background: white;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                }}
                .header {{
                    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    color: white;
                    font-size: 28px;
                    font-weight: 600;
                }}
                .content {{
                    padding: 30px;
                }}
                .error-box {{
                    background: #fef2f2;
                    border: 1px solid #fecaca;
                    border-radius: 8px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .error-box h3 {{
                    margin: 0 0 10px 0;
                    color: #991b1b;
                    font-size: 16px;
                }}
                .error-box pre {{
                    margin: 0;
                    color: #7f1d1d;
                    font-size: 13px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                }}
                .footer {{
                    padding: 20px 30px;
                    background: #fafafa;
                    border-top: 1px solid #eee;
                    text-align: center;
                    font-size: 12px;
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>❌ Scheduled Query Failed</h1>
                </div>

                <div class="content">
                    <h2>{schedule_name}</h2>
                    <p>Your scheduled query failed to execute at {time_str}.</p>

                    <div class="error-box">
                        <h3>Error Details:</h3>
                        <pre>{error_message}</pre>
                    </div>

                    <p>The schedule will continue to run at the next scheduled time. If this issue persists, please check your query or contact support.</p>
                </div>

                <div class="footer">
                    <p>Powered by SQLatte ☕</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html


# Mock email service for testing
class MockEmailService:
    """Mock email service for testing (logs instead of sending)"""

    def __init__(self, config: Dict):
        self.enabled = True
        self.sent_emails = []
        logger.info("✅ Mock Email service initialized (testing mode)")

    async def send_email(
            self,
            recipients: List[str],
            subject: str,
            body: str,
            attachments: Optional[List[Dict]] = None,
            html: bool = True
    ):
        """Log email instead of sending"""
        email_log = {
            'recipients': recipients,
            'subject': subject,
            'body_length': len(body),
            'attachments_count': len(attachments) if attachments else 0,
            'timestamp': datetime.now().isoformat()
        }

        self.sent_emails.append(email_log)

        logger.info(f"📧 [MOCK] Email logged: {subject}")
        logger.info(f"   To: {', '.join(recipients)}")
        if attachments:
            logger.info(f"   Attachments: {', '.join([a['filename'] for a in attachments])}")

    def create_report_email(self, *args, **kwargs):
        """Use real implementation"""
        return EmailService.create_report_email(self, *args, **kwargs)

    def create_error_email(self, *args, **kwargs):
        """Use real implementation"""
        return EmailService.create_error_email(self, *args, **kwargs)