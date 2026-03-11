from flask import Blueprint

requests_bp = Blueprint("requests", __name__)


from . import intake_routes  # noqa: F401,E402
from . import routes  # noqa: F401,E402
