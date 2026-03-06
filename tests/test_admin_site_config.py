import pytest
from app.extensions import db
from app.models import User, Department, SiteConfig
from werkzeug.security import generate_password_hash


def login_admin(client, email='admin@example.com', password='secret'):
    return client.post('/auth/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_departments_crud_and_site_config(app, client):
    with app.app_context():
        # create admin user
        u = User(email='admin@example.com', password_hash=generate_password_hash('secret'), department='B', is_active=True, is_admin=True)
        db.session.add(u)
        db.session.commit()

    # login as admin
    rv = login_admin(client)
    assert rv.status_code == 200

    # admin index exposes email form generation controls
    rv = client.get('/admin/')
    assert rv.status_code == 200
    assert b'Email Form Generation' in rv.data
    assert b'Manage Email Form Settings' in rv.data

    # departments list (empty)
    rv = client.get('/admin/departments')
    assert rv.status_code == 200

    # create new department
    rv = client.post('/admin/departments/new', data={'code': 'X', 'name': 'Dept X', 'order': '10', 'active': 'y'}, follow_redirects=True)
    assert rv.status_code == 200
    assert b'Department created' in rv.data

    # verify created in DB
    with app.app_context():
        d = Department.query.filter_by(code='X').first()
        assert d is not None
        did = d.id

    # edit department
    rv = client.post(f'/admin/departments/{did}/edit', data={'code': 'X', 'name': 'Dept X Updated', 'order': '11', 'active': ''}, follow_redirects=True)
    assert rv.status_code == 200
    assert b'Department updated' in rv.data

    with app.app_context():
        d = Department.query.get(did)
        assert d.name == 'Dept X Updated'
        assert d.order == 11

    # delete department
    rv = client.post(f'/admin/departments/{did}/delete', follow_redirects=True)
    assert rv.status_code in (200, 302)
    # endpoint returns json OK on success
    assert b'"ok":' in rv.data or rv.status_code == 302

    # Site config GET
    rv = client.get('/admin/site_config')
    assert rv.status_code == 200

    # Save site config with banner and rolling quotes
    post_data = {
        'brand_name': 'Acme Flow',
        'theme_preset': 'forest',
        'banner_html': '<div class="site-banner">Welcome</div>',
        'rolling_enabled': 'y',
        'rolling_csv': 'Quote one\nQuote two',
    }
    rv = client.post('/admin/site_config', data=post_data, follow_redirects=True)
    assert rv.status_code == 200
    assert b'Site configuration saved' in rv.data

    # Confirm site config persisted and visible in dashboard
    with app.app_context():
        cfg = SiteConfig.get()
        assert cfg.brand_name == 'Acme Flow'
        assert cfg.theme_preset == 'forest'
        assert cfg.banner_html is not None
        assert cfg.rolling_quotes_enabled is True
        assert isinstance(cfg.rolling_quotes, list)

    # Dashboard should include the banner or the first rolling quote
    rv = client.get('/dashboard')
    assert rv.status_code == 200
    assert b'Acme Flow' in rv.data
    assert b'Welcome' in rv.data or b'Quote one' in rv.data
