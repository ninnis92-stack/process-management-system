from flask import url_for

def test_request_new_includes_stimulus_controllers(client, app):
    # create and log in a user so the protected route is accessible
    from werkzeug.security import generate_password_hash
    from app.extensions import db
    from app.models import User

    user = User(
        email="frontend_user@example.com",
        password_hash=generate_password_hash("secret", method="pbkdf2:sha256"),
        department="A",
        name="Frontend User",
    )
    db.session.add(user)
    db.session.commit()
    rv = client.post(
        "/auth/login",
        data={"email": user.email, "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    resp = client.get(url_for('requests.request_new'))
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # ensure the form has the onboarding and field-focus controllers attached
    assert 'data-controller="onboarding field-focus"' in html
    # offcanvas help markup should exist
    assert 'id="onboardingHelp"' in html
