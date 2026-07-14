# License and Intended-Use Notes

## Intended use
NECTAR is educational and research software. Output is not medical nutrition therapy and is not
validated for individual patient care. Do not place recommendations in front of patients outside a
supervised research protocol with appropriate oversight (IRB, dietitian and physician review). See
`nectar/docs/SDD.md` Section 9.

## Data source licenses (verify current terms before redistribution)
- USDA FoodData Central, Nutrient Retention Factors: public domain (CC0). Free to use.
- RecipeNLG: non-commercial research and educational use only. Blocks commercial productization.
- Open Food Facts: Open Database License (ODbL); share-alike on redistributed databases.
- CIQUAL (ANSES): OpenData.
- McCance & Widdowson CoFID (UK): end-user license with an indemnification clause; reference only.
- FooDB, Phenol-Explorer: open-access research databases.
- International GI Database (Sydney): searchable, not bulk-redistributable.
- RxNorm (NLM): free APIs. DrugBank: non-commercial academic version free; commercial otherwise.
- Clinical guidelines (KDOQI, ADA, DASH, DGA, AHA): copyrighted; used as grounding references,
  paraphrased and cited, not redistributed verbatim.

Source manifest with links and trust tiers: `nutriscrape/config/sources.yaml`.

## Code
Application code in this repository is licensed under the Apache License, Version 2.0; see `LICENSE`
and `NOTICE`. Apache-2.0's explicit patent grant suits clinical software that may involve patented
methods. This license covers the code only: the third-party data-source terms above still govern any
data you ingest or redistribute (for example, RecipeNLG remains non-commercial, and Open Food Facts
data stays under ODbL share-alike).
