# Data dictionary — `pscomppars` (query subset)

**Grain:** one row per confirmed planet. `pscomppars` merges parameters from several references into one composite row, so values in a row can come from different papers.
**Primary key:** `pl_name`. **Join key to host star:** `hostname`.
**Query used:**
```sql
select pl_name,hostname,discoverymethod,disc_year,disc_facility,pl_rade,pl_orbper,pl_bmasse,sy_dist from pscomppars
```

| Column | Type | Units | Description | Missing? |
|---|---|---|---|---|
| `pl_name` | str | — | Planet name | never |
| `hostname` | str | — | Host star name | never |
| `discoverymethod` | str | — | Method of the discovery paper (Transit, Radial Velocity, Microlensing, Imaging, …) | never |
| `disc_year` | int | year | Year of discovery | rare |
| `disc_facility` | str | — | Observatory/mission of discovery | rare |
| `pl_rade` | float | Earth radii | Planet radius | **often** — most RV and microlensing planets |
| `pl_orbper` | float | days | Orbital period | sometimes — microlensing, imaging |
| `pl_bmasse` | float | Earth masses | Best mass estimate (mass or M·sin i) | often — most transit planets |
| `sy_dist` | float | parsecs | Distance to the system | occasionally |

## Missing-value convention
Empty cells in the CSV → `NaN`. There is no numeric fill marker. Missingness is **not random**: it depends on the discovery method, which is why the notebook reports it on the full catalog before filtering.

## Provenance
`data/raw/source.json` stores the query, the full TAP URL, row count, SHA-256 and UTC retrieval time. The archive updates weekly, so two runs on different days can differ — that is expected.
