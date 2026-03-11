# top-level api package
# this allows us to import subpackages such as ``app.api.v1`` and also
# expose commonly-used symbols like the current blueprint.

from .v1 import api_v1_bp

__all__ = ["api_v1_bp"]
