"""Import every model module so Base.metadata is always complete.

A string-based ForeignKey (e.g. `ForeignKey("diagnoses.id")` on Decision)
only resolves if the target table has already been registered on Base's
metadata -- which depends on that model's module having been imported by
*something*, *before* SQLAlchemy configures the mapper that references it.
Relying on whichever test file or script happens to run first to import the
right module transitively is exactly the kind of thing that works by
accident until it doesn't. Importing this module (done once, from the
bottom of src/db/base.py) makes registration unconditional instead.
"""

from src.detect import models as detect_models  # noqa: F401
from src.diagnose import models as diagnose_models  # noqa: F401
from src.execute import models as execute_models  # noqa: F401
from src.ingest import models as ingest_models  # noqa: F401
from src.ledger import models as ledger_models  # noqa: F401
from src.policy import models as policy_models  # noqa: F401
