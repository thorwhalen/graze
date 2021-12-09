"""Getting stuff from the internet (and caching locally, automatically)"""

from graze.base import (
    DFLT_GRAZE_DIR,
    Internet,
    Graze,
    GrazeWithDataRefresh,
    graze,
    url_to_filepath,
)
from graze.util import handle_missing_dir
