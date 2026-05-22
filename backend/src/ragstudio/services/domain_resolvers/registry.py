from __future__ import annotations

from collections.abc import Iterable

from ragstudio.services.domain_resolvers.base import DomainResolver, ResolverContext
from ragstudio.services.domain_resolvers.hadith import HadithResolver

_RESOLVERS: tuple[DomainResolver, ...] = (HadithResolver(),)


def resolvers_for_context(context: ResolverContext) -> Iterable[DomainResolver]:
    for resolver in _RESOLVERS:
        if resolver.can_resolve(context):
            yield resolver


def resolver_key(context: ResolverContext) -> str:
    domain = (context.domain_metadata.domain or "generic").strip().casefold()
    semantics = context.reference_semantics
    reference_type = (semantics.reference_type if semantics else None) or "unknown"
    chunk_unit = (semantics.chunk_unit if semantics else None) or "unknown"
    return f"{domain}:{reference_type}:{chunk_unit}".casefold()
