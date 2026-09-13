# Vendored ISO 20022 schemas (demo bundle)

Pinned XSDs are committed here so the POC works without network access. They cover the
three payment families and the trade-finance messages in scope; where a version-upgrade
impact scenario is demonstrated, both a baseline and a later version are included.

| Family | Baseline | Later version |
| --- | --- | --- |
| pain — customer payment initiation | `pain.001.001.09` | `pain.001.001.12` |
| pacs — FI to FI clearing and settlement | `pacs.008.001.08` | `pacs.008.001.10` |
| camt — cash management reporting | `camt.053.001.08` | `camt.053.001.10` |
| tsrv — trade undertakings (guarantees, standby LCs) | `tsrv.001.001.01` | — |
| tsmt — trade services management | `tsmt.011.001.03` | `tsmt.011.001.04` |

These are the published ISO 20022 message definitions, unmodified. They are used to
validate messages and to read element cardinality (`minOccurs`, `use="required"`), which
is what lets the comparator grade a newly added **mandatory** field as BREAKING rather
than informational.

`src/connectors/schema_bundle.py` registers the bundle into the standards library at
runtime, and `src/connectors/iso20022_connector.py` falls back to it when the ISO 20022
GitHub release cannot be reached. For anything beyond the demo, sync the full schema set
from the official ISO 20022 site rather than relying on this bundle.
