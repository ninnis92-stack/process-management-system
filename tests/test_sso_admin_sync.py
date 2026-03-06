from app.auth.sso import sso_user_is_admin, token_has_mfa


def test_sso_admin_sync_from_group_claim():
    userinfo = {
        'email': 'user@example.com',
        'groups': ['employees', 'process-admins'],
    }
    config = {
        'SSO_ADMIN_SYNC_ENABLED': True,
        'SSO_ADMIN_CLAIM': 'groups',
        'SSO_ADMIN_CLAIM_VALUES': ['process-admins', 'org-admin'],
        'SSO_ADMIN_EMAILS': [],
        'ADMIN_EMAILS': [],
    }
    assert sso_user_is_admin(userinfo, config) is True


def test_sso_admin_sync_from_nested_claim():
    userinfo = {
        'email': 'user@example.com',
        'realm_access': {'roles': ['viewer', 'admin']},
    }
    config = {
        'SSO_ADMIN_SYNC_ENABLED': True,
        'SSO_ADMIN_CLAIM': 'realm_access.roles',
        'SSO_ADMIN_CLAIM_VALUES': ['admin'],
        'SSO_ADMIN_EMAILS': [],
        'ADMIN_EMAILS': [],
    }
    assert sso_user_is_admin(userinfo, config) is True


def test_sso_admin_sync_from_email_allowlist():
    userinfo = {'email': 'admin@example.com'}
    config = {
        'SSO_ADMIN_SYNC_ENABLED': False,
        'SSO_ADMIN_CLAIM': 'groups',
        'SSO_ADMIN_CLAIM_VALUES': ['admin'],
        'SSO_ADMIN_EMAILS': ['admin@example.com'],
        'ADMIN_EMAILS': [],
    }
    assert sso_user_is_admin(userinfo, config) is True


def test_sso_admin_sync_false_when_no_match():
    userinfo = {
        'email': 'user@example.com',
        'groups': ['employees'],
    }
    config = {
        'SSO_ADMIN_SYNC_ENABLED': True,
        'SSO_ADMIN_CLAIM': 'groups',
        'SSO_ADMIN_CLAIM_VALUES': ['process-admins'],
        'SSO_ADMIN_EMAILS': [],
        'ADMIN_EMAILS': [],
    }
    assert sso_user_is_admin(userinfo, config) is False


def test_token_has_mfa_from_default_amr_claim():
    userinfo = {'amr': ['pwd', 'mfa']}
    assert token_has_mfa(userinfo, {}) is True


def test_token_has_mfa_from_configured_nested_claim():
    userinfo = {'authentication': {'methods': ['password', 'strong-auth']}}
    config = {
        'SSO_MFA_CLAIM': 'authentication.methods',
        'SSO_MFA_CLAIM_VALUES': ['strong-auth'],
    }
    assert token_has_mfa(userinfo, config) is True


def test_token_has_mfa_false_when_claim_missing():
    userinfo = {'authentication': {'methods': ['password']}}
    config = {
        'SSO_MFA_CLAIM': 'authentication.methods',
        'SSO_MFA_CLAIM_VALUES': ['strong-auth'],
    }
    assert token_has_mfa(userinfo, config) is False
