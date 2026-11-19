# Data sources and terms

This repository's MIT license covers **code only**. No upstream dataset is committed. Downloads land in `packs/<slug>/data/raw/`, which is git-ignored. Each real-data run writes `source.json` next to the files with the URL or query, the retrieval time and a checksum where practical.

| Pack | Source | Access | License / terms | Citation |
|---|---|---|---|---|
| `uci-bike-demand` | [UCI Bike Sharing](https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset) | Direct ZIP download | CC BY 4.0 | Fanaee-T, H. (2013). Bike Sharing [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5W894 |
| `nasa-bengaluru-weather` | [NASA POWER Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) | Public API, no key | NASA open data, acknowledgement requested ([referencing](https://power.larc.nasa.gov/docs/referencing/)) | Data obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program. |
| `nasa-exoplanets` | [NASA Exoplanet Archive, PSCompPars](https://exoplanetarchive.ipac.caltech.edu/) | TAP query | Acknowledge the archive and cite the DOI ([acknowledgement](https://exoplanetarchive.ipac.caltech.edu/docs/acknowledge.html)) | NASA Exoplanet Archive, Planetary Systems Composite Parameters, doi:10.26133/NEA13, plus your access date |
| `uci-dry-bean` | [UCI Dry Bean](https://archive.ics.uci.edu/dataset/602/dry+bean+dataset) | Direct ZIP download (.xlsx inside) | CC BY 4.0 | Dry Bean [Dataset]. (2020). UCI Machine Learning Repository. https://doi.org/10.24432/C50S4B |
| `kaggle-olist-delivery` | [Brazilian E-Commerce by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | Kaggle download (free sign-in) or `kagglehub` | CC BY-NC-SA 4.0: non-commercial, share-alike, attribution | Olist and André Sionek (2018). Brazilian E-Commerce Public Dataset by Olist. Kaggle. |

## Discover catalog (metadata only)
`catalog/records/*.json` stores **metadata and links**, not data: title, publisher, field names, coverage, license and evidence URLs, all copied from the providers' public pages. Records include NYC Motor Vehicle Collisions (NYC Open Data), Chicago Traffic Crashes (City of Chicago), US Accidents (Kaggle, CC BY-NC-SA 4.0), Road Safety Data / STATS19 (DfT, OGL v3), UCI Metro Interstate Traffic Volume, Air Quality and Household Power, the Open-Meteo Historical Weather API (CC BY 4.0, commercial API use requires a key) and NASA GPM IMERG daily (via CMR). Each record's `license` block says what is known about reuse, and `unknown` where it hasn't been checked. Always read the provider's own terms before you use the data.

## Synthetic fixtures
Files in `packs/*/fixtures/` are **invented** by the `make_fixture.py` script beside them. They copy the real schema but no real records, and are covered by this repo's MIT license. Charts and scores made from them are labelled *SYNTHETIC SAMPLE* and say nothing about the real data.

## Publishing your own results
- Credit the source with the citation above in your README, notebook or post.
- For Olist, derived charts and tables inherit **CC BY-NC-SA 4.0**. Don't use them commercially, and share them under the same license.
- For live sources (NASA POWER, Exoplanet Archive), state the retrieval date. The upstream data changes.
