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
from graze.util import handle_missing_dir
