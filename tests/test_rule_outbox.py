import pytest
from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config.update({"TESTING": True})
    return app


def test_rule_fires_and_enqueues_event(app):
    from app.extensions import db
    from app.models import AutomationRule, Request as ReqModel, IntegrationEvent

    with app.app_context():
        # ensure tables exist for this prototype test environment
        AutomationRule.__table__.create(bind=db.engine, checkfirst=True)
        ReqModel.__table__.create(bind=db.engine, checkfirst=True)
        IntegrationEvent.__table__.create(bind=db.engine, checkfirst=True)

        # create a request
        req = ReqModel(title='T', request_type='X', description='d', priority='low', due_at=None)
        db.session.add(req)
        db.session.commit()

        # create a simple rule that triggers on manual_fire and posts webhook
        r = AutomationRule(name='t', triggers_json=['manual_fire'], conditions_json={}, actions_json=[{"action":"webhook","event_name":"automation.test.webhook"}], is_active=True)
        db.session.add(r)
        db.session.commit()

        # call evaluate
        from app.services.rule_engine import evaluate_rules_for_event
        fired = evaluate_rules_for_event('manual_fire', req)
        assert r.id in fired

        # check IntegrationEvent created
        ev = IntegrationEvent.query.filter_by(event_name='automation.test.webhook').first()
        assert ev is not None
        assert ev.status == 'pending'

        # run the outbox worker to process pending events
        from app.services.connector_worker import process_pending_integration_events
        processed = process_pending_integration_events(limit=10)
        assert processed >= 1
        ev = IntegrationEvent.query.filter_by(event_name='automation.test.webhook').first()
        assert ev.status == 'delivered'
