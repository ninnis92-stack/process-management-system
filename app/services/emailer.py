import smtplib
from email.message import EmailMessage
from typing import List, Optional
from flask import current_app


class EmailService:
    """Simple email adapter.

    Behavior:
      - If `EMAIL_ENABLED` is True and SMTP_HOST/SMTP_PORT are configured, attempts to send via SMTP.
      - Otherwise logs the outgoing message to `current_app.logger` for prototype use.
    """

    def __init__(self):
        cfg = current_app.config
        self.enabled = cfg.get("EMAIL_ENABLED", False)
        self.host = cfg.get("SMTP_HOST")
        self.port = int(cfg.get("SMTP_PORT", 25)) if cfg.get("SMTP_PORT") else None
        self.username = cfg.get("SMTP_USERNAME")
        self.password = cfg.get("SMTP_PASSWORD")
        self.from_addr = cfg.get("EMAIL_FROM", "no-reply@example.com")
        self.use_tls = cfg.get("SMTP_USE_TLS", False)
        self.timeout = int(cfg.get("SMTP_TIMEOUT", 10))
        self.test_domains = set(cfg.get("TEST_EMAIL_DOMAINS", [])) or set()

    def send_email(
        self, recipients: List[str], subject: str, text: str, html: Optional[str] = None
    ) -> dict:
        """Send email to recipients.

        Returns a dict with keys:
          - ok: True if all sends succeeded, False on error, None if nothing attempted
          - skipped: list of recipient emails skipped because they are test domains
          - error: error message when ok is False
        """
        recipients = list({r for r in recipients if r})
        if not recipients:
            current_app.logger.debug("EmailService: no recipients")
            return {"ok": None, "skipped": [], "error": "no_recipients"}

        # Split recipients into test-domain (skipped) and actual send targets
        to_send = []
        skipped = []
        for r in recipients:
            try:
                domain = r.split("@", 1)[1].lower()
            except Exception:
                domain = ""
            if domain in self.test_domains:
                skipped.append(r)
            else:
                to_send.append(r)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)
        msg.set_content(text or "")
        if html:
            msg.add_alternative(html, subtype="html")

        result = {"ok": None, "skipped": skipped}

        if not to_send:
            # Nothing to attempt; return skipped as the reason
            current_app.logger.info(
                f"EmailService: skipped sending to test domains: {skipped}"
            )
            result["ok"] = None
            return result

        if self.enabled and self.host and self.port:
            try:
                if self.use_tls:
                    s = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                    s.starttls()
                else:
                    s = smtplib.SMTP(self.host, self.port, timeout=self.timeout)

                if self.username and self.password:
                    s.login(self.username, self.password)

                # update message recipient header
                msg["To"] = ", ".join(to_send)
                s.send_message(msg)
                s.quit()
                current_app.logger.info(
                    f"EmailService: sent email to {len(to_send)} recipients (skipped {len(skipped)})"
                )
                result["ok"] = True
                return result
            except Exception as exc:
                current_app.logger.exception(
                    f"EmailService: failed to send email: {exc}"
                )
                result["ok"] = False
                result["error"] = str(exc)
                return result
        else:
            # Prototype mode: log the rendered email instead of sending
            current_app.logger.info("EmailService (prototype): would send email")
            current_app.logger.info(f"To (send): {to_send}")
            current_app.logger.info(f"To (skipped): {skipped}")
            current_app.logger.info(f"Subject: {subject}")
            current_app.logger.info(f"Body: {text}")
            if html:
                current_app.logger.info(f"HTML body present")
            result["ok"] = True
            return result
