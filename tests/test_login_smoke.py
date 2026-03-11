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
    # make sure non-admin users are not redirected to admin interface
    assert "/admin" not in rv.request.path

    # if login request contains a next parameter targeting a static file,
    # it should not redirect there
    rv2 = client.post(
        "/auth/login?next=/static/dist/app.css",
        data={"email": user.email, "password": "testpass"},
        follow_redirects=False,
    )
    assert rv2.status_code == 302
    location = rv2.headers.get("Location", "")
    assert "/static/dist/app.css" not in location

    # same test but with full absolute URL – must also be ignored
    absolute = f"http://127.0.0.1:5000/static/dist/app.css?x=y"
    rv3 = client.post(
        f"/auth/login?next={absolute}",
        data={"email": user.email, "password": "testpass"},
        follow_redirects=False,
    )
    assert rv3.status_code == 302
    location3 = rv3.headers.get("Location", "")
    assert "/static/dist/app.css" not in location3
