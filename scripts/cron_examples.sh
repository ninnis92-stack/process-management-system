#!/usr/bin/env bash
# Example cron entries to run reminder sender and refresh metrics.
# Adjust PATH and virtualenv activation as needed for your environment.

# Every hour: run reminder sender (will check SpecialEmailConfig.nudge_enabled)
0 * * * * cd /path/to/process-management-prototype && . .venv/bin/activate && FLASK_APP=app flask notify-reminders >> /var/log/process-mgmt/reminders.log 2>&1

# Every 5 minutes: refresh metrics gauge (owner + overdue counts)
*/5 * * * * cd /path/to/process-management-prototype && . .venv/bin/activate && python3 -c "from app import create_app; from app.metrics import update_owner_gauge; from app.extensions import db; app=create_app(); ctx=app.app_context(); ctx.push(); from app.models import Request as ReqModel; update_owner_gauge(db.session, ReqModel); ctx.pop()" >> /var/log/process-mgmt/metrics.log 2>&1

# On hosted platforms like Fly or Heroku, use their scheduler/add-on to run the equivalent commands.
