def test_auth_login_route_exists(client):
    resp = client.get("/auth/login")
    # Print all routes if not found
    if resp.status_code != 200:
        from flask import current_app
        print("Registered routes:")
        for rule in current_app.url_map.iter_rules():
            print(rule)
    assert resp.status_code == 200, f"/auth/login not found, got {resp.status_code}"
