import os
from a2wsgi import WSGIMiddleware
from app import app as flask_app

# Convert the Flask WSGI app to an ASGI app so Hypercorn can serve it natively
asgi_app = WSGIMiddleware(flask_app)
