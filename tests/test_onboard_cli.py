from click.testing import CliRunner

from app.models import Tenant, TenantMembership, User


def test_onboard_tenant_command(app):
    runner = CliRunner()
    # run command in isolated filesystem with app context
    result = runner.invoke(
        app.cli,
        [
            "onboard-tenant",
            "--slug",
            "demo",
            "--name",
            "Demo Tenant",
            "--admin-email",
            "admin@demo.com",
            "--admin-password",
            "password123",
        ],
    )
    assert result.exit_code == 0
    assert "Created tenant 'demo'" in result.output or "already exists" in result.output
    with app.app_context():
        t = Tenant.query.filter_by(slug="demo").first()
        assert t is not None
        u = User.query.filter_by(email="admin@demo.com").first()
        assert u is not None
        mem = TenantMembership.query.filter_by(tenant_id=t.id, user_id=u.id).first()
        assert mem is not None
