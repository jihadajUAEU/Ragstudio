from ragstudio.api.routes import chunks, documents, evaluation_sets, health, jobs, query, runs, settings, variants

ROUTERS = [
    health.router,
    settings.router,
    variants.router,
    documents.router,
    chunks.router,
    jobs.router,
    evaluation_sets.router,
    query.router,
    runs.router,
]
