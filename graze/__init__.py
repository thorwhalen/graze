"""Getting stuff from the internet (and caching locally, automatically)"""

from graze.base import (
    url_to_file_download,
    DFLT_GRAZE_DIR,
    Internet,
    Graze,
    GrazeWithDataRefresh,
    GrazeReturningFilepaths,
    graze,
    url_to_localpath,
    localpath_to_url,
    url_to_filepath,
    url_to_contents,
    key_egress_print_downloading_message,
)
from graze.util import handle_missing_dir, tiny_url
from graze.share_links import (
    ShareLinkKind,
    ResolvedShareLink,
    ShareLinkResolutionError,
    resolve_share_url,
    direct_download_url,
    share_link_resolvers,
    add_share_link_resolver,
)
from graze.content_kind import (
    ContentKindMismatch,
    SNIFF_BYTES,
    sniff_content_family,
    assert_content_kind,
    kind_checked,
)
from graze.graze_exceptional import (
    graze_cache,
    add_exception,
    list_exceptions,
)
