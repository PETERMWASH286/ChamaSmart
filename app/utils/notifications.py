# app/utils/notifications.py
import os
import logging
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import africastalking

# Configure logging
logger = logging.getLogger(__name__)

class NotificationManager:
    def __init__(self, app=None):
        self.smtp_server = None
        self.smtp_port = None
        self.smtp_username = None
        self.smtp_password = None
        self.smtp_sender = None
        self.africastalking_username = None
        self.africastalking_api_key = None
        self.africastalking_sender = None
        
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app configuration"""
        # Email configuration
        self.smtp_server = app.config.get('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = app.config.get('SMTP_PORT', 587)
        self.smtp_username = app.config.get('SMTP_USERNAME')
        self.smtp_password = app.config.get('SMTP_PASSWORD')
        self.smtp_sender = app.config.get('DEFAULT_EMAIL_SENDER', app.config.get('SMTP_USERNAME'))
        
        # SMS Configuration
        self.africastalking_username = app.config.get('AFRICASTALKING_USERNAME')
        self.africastalking_api_key = app.config.get('AFRICASTALKING_API_KEY')
        self.africastalking_sender = app.config.get('AFRICASTALKING_SENDER_ID')

    def send_email(self, subject, recipients, body, html_body=None, attachments=None, cc=None, bcc=None, sender=None):
        try:
            # Print email details
            print("=== Email Details ===")
            print("Subject:", subject)
            print("From:", sender or self.smtp_sender)
            print("To:", recipients)
            if cc:
                print("Cc:", cc)
            if bcc:
                print("Bcc:", bcc)
            print("Body:", body)
            if html_body:
                print("HTML Body:", html_body)
            if attachments:
                print("Attachments:", attachments)
            print("=====================")
            sys.stdout.flush()
            
            msg = MIMEMultipart()
            msg['Subject'] = subject
            msg['From'] = sender or self.smtp_sender  # Use provided sender or default
            msg['To'] = ', '.join(recipients)
            
            if cc:
                msg['Cc'] = ', '.join(cc)
            if bcc:
                msg['Bcc'] = ', '.join(bcc)

            # Attach plain text body
            msg.attach(MIMEText(body, 'plain'))
            # Optionally attach HTML body
            if html_body:
                msg.attach(MIMEText(html_body, 'html'))

            # Attach any files provided
            if attachments:
                for file_path in attachments:
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                    msg.attach(part)

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                print("Attempting to send email...")
                sys.stdout.flush()
                server.send_message(msg)

            print("Email sent successfully to:", recipients)
            sys.stdout.flush()
            logger.info(f"Email sent to {recipients}")
            return True

        except Exception as e:
            print("Error sending email:", str(e))
            sys.stdout.flush()
            logger.error(f"Error sending email: {str(e)}")
            return False

    def send_sms(self, message, recipients, sender_id=None):
        """
        Send SMS via Africa's Talking
        :param message: SMS message content
        :param recipients: List of phone numbers (international format)
        :param sender_id: Optional sender ID (if approved)
        :return: Boolean indicating success
        """
        try:
            # Initialize Africa's Talking
            africastalking.initialize(
                self.africastalking_username,
                self.africastalking_api_key
            )
            
            # Get SMS service
            sms = africastalking.SMS

            # Prepare recipients
            recipients = [phone.strip() for phone in recipients]

            # Send SMS
            response = sms.send(
                message=message,
                recipients=recipients,
                sender_id=sender_id or self.africastalking_sender
            )

            if response['SMSMessageData']['Recipients']:
                logger.info(f"SMS sent to {recipients}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error sending SMS: {str(e)}")
            return False

# Initialize extension (you can import and initialize this in your app factory)
notification_manager = NotificationManager()
