from authlib.integrations.flask_client import OAuth

oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)

    # Register OIDC provider
    oauth.register(
        name="oidc",
        server_metadata_url=app.con***REMOVED***g["OIDC_DISCOVERY_URL"],
        client_id=app.con***REMOVED***g["OIDC_CLIENT_ID"],
        client_secret=app.con***REMOVED***g["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": "openid email pro***REMOVED***le"},
    )