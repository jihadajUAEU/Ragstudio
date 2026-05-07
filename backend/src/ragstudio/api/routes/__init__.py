from ragstudio.api.routes import chunks, documents, evaluation_sets, health, jobs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    chunks.router,
    jobs.router,
    evaluation_sets.router,
]
