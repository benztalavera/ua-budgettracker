"""For hosting panels that explicitly support Python WSGI apps."""

from tracker import create_app

application = create_app()
