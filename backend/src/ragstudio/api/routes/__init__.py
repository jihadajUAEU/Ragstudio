from ragstudio.api.routes import documents, health, jobs, settings, variants

ROUTERS = [health.router, settings.router, variants.router, documents.router, jobs.router]
