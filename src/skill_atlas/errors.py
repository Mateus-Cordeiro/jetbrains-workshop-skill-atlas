"""Expected failures exposed by application boundaries."""


class AtlasError(Exception):
    """A failure that can be shown to a CLI user without a traceback."""


class RepositoryError(AtlasError):
    """Repository access or complete snapshot retrieval failed."""


class IncompleteListingError(RepositoryError):
    """The reader cannot enumerate the snapshot within its service's limits."""


class CatalogError(AtlasError):
    """Catalog access, migration, or persistence failed."""


class GroupingError(AtlasError):
    """Explicit group generation failed without changing saved groups."""
