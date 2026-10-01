"""Expected failures exposed by application boundaries."""


class AtlasError(Exception):
    """A failure that can be shown to a CLI user without a traceback."""


class RepositoryError(AtlasError):
    """Repository access or complete snapshot retrieval failed."""


class IncompleteListingError(RepositoryError):
    """The reader cannot enumerate the snapshot within its service's limits."""


class CatalogError(AtlasError):
    """Catalog access, migration, or persistence failed."""


class RateLimitError(RepositoryError):
    """GitHub refused a request because a rate limit was reached."""


class ScanCancelled(AtlasError):
    """The user or server stopped a scan before it completed."""
