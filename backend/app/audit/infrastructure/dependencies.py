from elasticsearch import AsyncElasticsearch
from fastapi import Request


def get_audit_es_client(request: Request) -> AsyncElasticsearch | None:
    return getattr(request.app.state, "audit_es_client", None)
