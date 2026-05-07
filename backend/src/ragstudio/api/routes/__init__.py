from ragstudio.api.routes import documents, evaluation_sets, health, jobs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    jobs.router,
    evaluation_sets.router,
]
