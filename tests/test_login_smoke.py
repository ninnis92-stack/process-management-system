def test_login_smoke(client, app):
    from werkzeug.security import generate_password_hash
    from app.extensions import db
    from app.models import User

    # create a user
    user = User(
        email="smoke_user@example.com",
        password_hash=generate_password_hash("testpass", method="pbkdf2:sha256"),
        department="A",
        name="Smoke User",
    )
    db.session.add(user)
    db.session.commit()

    # attempt login
    rv = client.post(
        "/auth/login",
        data={"email": user.email, "password": "testpass"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Temporary database error" not in body
    assert "current transaction is aborted" not in body
