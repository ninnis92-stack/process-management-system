# versioned API package
# the blueprint is created in `routes.py` so that the module can import it
# without circular dependencies.
# ensure routes module is imported so that all handlers are registered
from . import routes  # noqa: F401,E402
from .routes import api_v1_bp  # noqa: F401
