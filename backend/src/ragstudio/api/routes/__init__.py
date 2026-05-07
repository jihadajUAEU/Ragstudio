from ragstudio.api.routes import health, settings, variants

ROUTERS = [health.router, settings.router, variants.router]
