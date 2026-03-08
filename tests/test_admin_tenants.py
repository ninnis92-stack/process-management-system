import pytest
from app.extensions import db
from app.models import User, Tenant, TenantMembership
from werkzeug.security import generate_password_hash


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def create_admin(app):
    with app.app_context():
        u = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()
        return u


def test_tenant_crud_and_membership(client, app):
    # prepare admin and another user
    admin = create_admin(app)
    with app.app_context():
        other = User(
            email="user@example.com",
            password_hash=generate_password_hash("pass"),
            department="B",
            is_active=True,
        )
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    rv = login_admin(client)
    assert rv.status_code == 200

    # overview page initially has only default tenant
    rv = client.get("/admin/tenants")
    assert rv.status_code == 200
    assert b"Default Workspace" in rv.data

    # create a new tenant
    rv = client.post(
        "/admin/tenants/new",
        data={"slug": "acme", "name": "Acme Corp", "is_active": "y"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    # flash message should mention the slug and success
    assert b"acme" in rv.data and b"created" in rv.data

    with app.app_context():
        t = Tenant.query.filter_by(slug="acme").first()
        assert t is not None
        tid = t.id

    # edit the tenant
    rv = client.post(
        f"/admin/tenants/{tid}/edit",
        data={"slug": "acme", "name": "Acme Co.", "is_active": ""},
        follow_redirects=True,
    )
    assert b"Tenant updated" in rv.data
    with app.app_context():
        t = db.session.get(Tenant, tid)
        assert t.name == "Acme Co."
        assert t.is_active is False

    # add membership
    rv = client.post(
        f"/admin/tenants/{tid}/members",
        data={"user_id": other_id, "role": "member", "is_active": "y"},
        follow_redirects=True,
    )
    assert b"Membership saved" in rv.data
    with app.app_context():
        m = TenantMembership.query.filter_by(tenant_id=tid, user_id=other_id).first()
        assert m is not None and m.role == "member"

    # remove membership
    rv = client.post(
        f"/admin/tenants/{tid}/members/{m.id}/delete",
        follow_redirects=True,
    )
    assert b"Membership removed" in rv.data
    with app.app_context():
        assert db.session.get(TenantMembership, m.id) is None

    # delete tenant
    rv = client.post(f"/admin/tenants/{tid}/delete", follow_redirects=True)
    assert b"Tenant deleted" in rv.data
    with app.app_context():
        assert db.session.get(Tenant, tid) is None


def test_user_list_tenant_filter(client, app):
    # create admin + two tenants + users
    with app.app_context():
        admin = User(
            email="admin-filter@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        t1 = Tenant(name="One", slug="one")
        t2 = Tenant(name="Two", slug="two")
        db.session.add_all([admin, t1, t2])
        db.session.commit()
        u1 = User(email="u1@example.com", password_hash=generate_password_hash("x"), department="A", tenant_id=t1.id)
        u2 = User(email="u2@example.com", password_hash=generate_password_hash("x"), department="A", tenant_id=t2.id)
        db.session.add_all([u1, u2])
        db.session.commit()

    # login as admin
    rv = client.post("/auth/login", data={"email":"admin-filter@example.com","password":"secret"}, follow_redirects=True)
    assert rv.status_code == 200

    # unfiltered list shows both users
    rv = client.get("/admin/users")
    assert b"u1@example.com" in rv.data
    assert b"u2@example.com" in rv.data

    # filter by first tenant
    rv = client.get(f"/admin/users?tenant_id={t1.id}")
    assert b"u1@example.com" in rv.data
    assert b"u2@example.com" not in rv.data

    # filter by second tenant
    rv = client.get(f"/admin/users?tenant_id={t2.id}")
    assert b"u1@example.com" not in rv.data
    assert b"u2@example.com" in rv.data


def test_user_list_search(client, app):
    # create admin + two users
    with app.app_context():
        admin = User(
            email="admin-search@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        t = Tenant(name="Searchland", slug="search")
        db.session.add_all([admin, t])
        db.session.commit()
        u1 = User(email="apple@example.com", password_hash=generate_password_hash("x"), department="A", tenant_id=t.id)
        u2 = User(email="banana@example.com", password_hash=generate_password_hash("x"), department="A", tenant_id=t.id)
        db.session.add_all([u1, u2])
        db.session.commit()

    rv = client.post("/auth/login", data={"email":"admin-search@example.com","password":"secret"}, follow_redirects=True)
    assert rv.status_code == 200

    # search for 'apple' should only show u1
    rv = client.get("/admin/users?q=apple")
    assert b"apple@example.com" in rv.data
    assert b"banana@example.com" not in rv.data

    # search with tenant filter too
    rv = client.get(f"/admin/users?q=apple&tenant_id={t.id}")
    assert b"apple@example.com" in rv.data
    assert b"banana@example.com" not in rv.data


def test_nonadmin_cannot_access_tenants(client, app):
    # create ordinary user
    with app.app_context():
        u = User(
            email="regular@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(u)
        db.session.commit()
    rv = client.post(
        "/auth/login",
        data={"email": "regular@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/admin/tenants", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Access denied" in rv.data
