# Manual check of gold answers: new test questions (FR-R1.6)

10 of the 52 answerable questions, picked with `random.Random(42)`. Unanswerable questions are left out (nothing to check).

**How to check:** open the file named in each cell reference, go to the sheet (tab) and the cell, and compare with the table. Then check the gold answer is what the question asks for. Tick the box, or write what is wrong next to it.

Columns in every sheet: C instrument, D ISIN, E industry / rating, F quantity, G market value (Rs lakhs), H % to AUM. The file stores % as a fraction (0.0560 = 5.60 %); the tables show percent.

| Id | Type | Gold answer | OK? |
|---|---|---|---|
| T002 | lookup | 5,007.70 Rs lakhs | [ ] |
| T007 | lookup | 1.7471 % | [ ] |
| T008 | lookup | 2,912.75 Rs lakhs | [ ] |
| T009 | lookup | 1.5858 % | [ ] |
| T015 | lookup | 3.8513 % | [ ] |
| T016 | aggregation | 4.5045 % | [ ] |
| T018 | aggregation | 68 | [ ] |
| T035 | debt | 2 item(s): 8.73% Eris Lifesciences Ltd. (07/12/2026) **; 8.73% Eris Lifesciences Ltd. (07/06/2027) ** | [ ] |
| T041 | debt | 4 item(s): India Universal Trust AL1 (20/09/2030) **; India Universal Trust AL2 (21/11/2030) **; India Universal Trust AL2 (21/09/2027) **; India Universal Trust AL1 (20/03/2027) ** | [ ] |
| T048 | cross_scheme | CIGAPR28 (CRISIL IBX Gilt Apr 2028 Index Fund) | [ ] |

## T002 · lookup

**Question:** What is the market value, in Rs lakhs, of 8.29% TATA Capital Ltd. (10/05/2027) held by Aditya Birla Sun Life CRISIL-IBX Financial Services 9-12 Months Debt Index Fund as on 30 September 2026?

**Gold answer:** 5,007.70 Rs lakhs

**How it is computed** (`holding_value`): Market value of that holding in Rs lakhs (column G). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'CSFSD12'!G10` | CSFSD12 | 8.29% TATA Capital Ltd. (10/05/2027) ** | INE976I07CT9 | ICRA AAA | 5,007.70 | 3.7691 |

- [ ] checked against the Excel

## T007 · lookup

**Question:** How much of the AUM of Aditya Birla Sun Life Retirement Fund - The 40s Plan (in %) is in Torrent Pharmaceuticals Ltd. as on 30 September 2026?

**Gold answer:** 1.7471 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLRF40'!H21` | BSLRF40 | Torrent Pharmaceuticals Ltd. | INE685A01028 | Pharmaceuticals & Biotechnology | 192.00 | 1.7471 |

- [ ] checked against the Excel

## T008 · lookup

**Question:** What is the market value, in Rs lakhs, of 8.00% Adani Power Ltd. (27/01/2028) held by Aditya Birla Sun Life Credit Risk Fund as on 30 September 2026?

**Gold answer:** 2,912.75 Rs lakhs

**How it is computed** (`holding_value`): Market value of that holding in Rs lakhs (column G). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLCBF'!G33` | BSLCBF | 8.00% Adani Power Ltd. (27/01/2028) ** | INE814H07190 | IND AA+ | 2,912.75 | 1.7578 |

- [ ] checked against the Excel

## T009 · lookup

**Question:** How much of the AUM of Aditya Birla Sun Life Dividend Yield Fund (in %) is in PNB Housing Finance Ltd. as on 30 Sep 2026?

**Gold answer:** 1.5858 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BDYP'!H28` | BDYP | PNB Housing Finance Ltd. | INE572E01012 | Finance | 2,191.37 | 1.5858 |

- [ ] checked against the Excel

## T015 · lookup

**Question:** As on 30 September 2026, what percentage of its AUM has Aditya Birla Sun Life CRISIL IBX 60:40 SDL + AAA PSU - Apr 2027 Index Fund invested in State Government Securities (01/03/2027)?

**Gold answer:** 3.8513 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'CSPAPA27'!H24` | CSPAPA27 | State Government Securities (01/03/2027) | IN2920160420 | Sovereign | 5,032.16 | 3.8513 |

- [ ] checked against the Excel

## T016 · aggregation

**Question:** What is the total % of AUM in equity holdings of the Chemicals & Petrochemicals industry for Aditya Birla Sun Life Midcap Fund as on 30 September 2026?

**Gold answer:** 4.5045 %

**How it is computed** (`industry_total`): Sum of column H over the equity rows whose Industry (column E) is the one asked. 3 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'MIDCAP'!H14` | MIDCAP | Navin Fluorine International Ltd. | INE048G01026 | Chemicals & Petrochemicals | 16,862.59 | 2.5744 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'MIDCAP'!H51` | MIDCAP | Gujarat Fluorochemicals Ltd. | INE09N301011 | Chemicals & Petrochemicals | 6,871.92 | 1.0491 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'MIDCAP'!H60` | MIDCAP | SRF Ltd. | INE647A01010 | Chemicals & Petrochemicals | 5,770.02 | 0.8809 |

- [ ] checked against the Excel

## T018 · aggregation

**Question:** How many holdings are listed in the Equity & Equity Related section of the Value Fund as on 30 Sep 2026?

**Gold answer:** 68

**How it is computed** (`holding_count`): Number of holding rows in the section (Total / heading rows are not counted). 68 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C8` | PURE | HDFC Bank Ltd. | INE040A01034 | Banks | 32,547.08 | 4.8875 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C9` | PURE | Swiggy Ltd. | INE00H001014 | Retailing | 22,644.84 | 3.4005 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C10` | PURE | State Bank of India | INE062A01020 | Banks | 21,800.90 | 3.2738 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C11` | PURE | Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 20,938.13 | 3.1442 |
| 5 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C12` | PURE | Shriram Finance Ltd. | INE721A01047 | Finance | 20,661.68 | 3.1027 |
| 6 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C13` | PURE | Minda Corporation Ltd. | INE842C01021 | Auto Components | 20,654.26 | 3.1016 |
| 7 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C14` | PURE | ICICI Bank Ltd. | INE090A01021 | Banks | 19,701.58 | 2.9585 |
| 8 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C15` | PURE | Welspun Corp Ltd. | INE191B01025 | Industrial Products | 18,314.45 | 2.7502 |
| 9 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C16` | PURE | Tech Mahindra Ltd. | INE669C01036 | IT - Software | 17,702.51 | 2.6583 |
| 10 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C17` | PURE | Adani Enterprises Ltd. | INE423A01024 | Metals & Minerals Trading | 15,655.66 | 2.3510 |
| 11 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C18` | PURE | Bharat Heavy Electricals Ltd. | INE257A01026 | Electrical Equipment | 15,460.21 | 2.3216 |
| 12 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C19` | PURE | PNB Housing Finance Ltd. | INE572E01012 | Finance | 14,962.01 | 2.2468 |
| 13 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C20` | PURE | ITC Ltd. | INE154A01025 | Diversified FMCG | 14,650.24 | 2.2000 |
| 14 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C21` | PURE | NTPC Ltd. | INE733E01010 | Power | 13,365.54 | 2.0071 |
| 15 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C22` | PURE | Axis Bank Ltd. | INE238A01034 | Banks | 13,166.09 | 1.9771 |
| 16 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C23` | PURE | Apollo Hospitals Enterprise Ltd. | INE437A01024 | Healthcare Services | 12,974.82 | 1.9484 |
| 17 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C24` | PURE | Adani Ports and Special Economic Zone Ltd. | INE742F01042 | Transport Infrastructure | 12,588.10 | 1.8903 |
| 18 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C25` | PURE | HDFC Life Insurance Company Ltd. | INE795G01014 | Insurance | 12,523.78 | 1.8807 |
| 19 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C26` | PURE | Infosys Ltd. | INE009A01021 | IT - Software | 12,340.62 | 1.8532 |
| 20 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C27` | PURE | Grasim Industries Ltd. | INE047A01021 | Cement & Cement Products | 12,167.90 | 1.8272 |
| 21 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C28` | PURE | Kalpataru Projects International Ltd. | INE220B01022 | Construction | 11,899.14 | 1.7869 |
| 22 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C29` | PURE | Granules India Ltd. | INE101D01020 | Pharmaceuticals & Biotechnology | 11,877.94 | 1.7837 |
| 23 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C30` | PURE | Astral Ltd. | INE006I01046 | Industrial Products | 10,685.69 | 1.6046 |
| 24 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C31` | PURE | LTM Ltd. | INE214T01019 | IT - Software | 9,855.89 | 1.4800 |
| 25 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C32` | PURE | Cyient DLM Ltd. | INE055S01018 | Aerospace & Defense | 9,849.37 | 1.4790 |
| 26 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C33` | PURE | Tube Investments of India Ltd. | INE974X01010 | Auto Components | 9,801.96 | 1.4719 |
| 27 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C34` | PURE | Ambuja Cements Ltd. | INE079A01024 | Cement & Cement Products | 9,423.79 | 1.4151 |
| 28 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C35` | PURE | Multi Commodity Exchange of India Ltd. | INE745G01043 | Capital Markets | 9,335.91 | 1.4019 |
| 29 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C36` | PURE | Vedanta Aluminium Metal Ltd. | INE1CDF01017 | Non - Ferrous Metals | 9,207.74 | 1.3827 |
| 30 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C37` | PURE | Pitti Engineering Ltd. | INE450D01021 | Industrial Manufacturing | 9,007.95 | 1.3527 |
| 31 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C38` | PURE | Jindal Steel Ltd. | INE749A01030 | Ferrous Metals | 8,968.76 | 1.3468 |
| 32 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C39` | PURE | DLF Ltd. | INE271C01023 | Realty | 8,873.49 | 1.3325 |
| 33 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C40` | PURE | Carborundum Universal Ltd. | INE120A01034 | Industrial Products | 8,856.16 | 1.3299 |
| 34 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C41` | PURE | Mphasis Ltd. | INE356A01018 | IT - Software | 8,309.61 | 1.2478 |
| 35 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C42` | PURE | GMR Airports Ltd. | INE776C01039 | Transport Infrastructure | 7,752.12 | 1.1641 |
| 36 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C43` | PURE | Sonata Software Ltd. | INE269A01021 | IT - Software | 7,603.24 | 1.1418 |
| 37 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C44` | PURE | Cyient Ltd. | INE136B01020 | IT - Services | 7,352.18 | 1.1041 |
| 38 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C45` | PURE | Pricol Ltd. | INE726V01018 | Auto Components | 7,237.84 | 1.0869 |
| 39 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C46` | PURE | Sobha Ltd. | INE671H01015 | Realty | 7,136.48 | 1.0717 |
| 40 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C47` | PURE | Craftsman Automation Ltd. | INE00LO01017 | Auto Components | 7,060.23 | 1.0602 |
| 41 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C48` | PURE | Onesource Specialty Pharma Ltd. | INE013P01021 | Pharmaceuticals & Biotechnology | 6,701.19 | 1.0063 |
| 42 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C49` | PURE | Life Insurance Corporation of India | INE0J1Y01017 | Insurance | 6,574.57 | 0.9873 |
| 43 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C50` | PURE | Balrampur Chini Mills Ltd. | INE119A01028 | Agricultural Food & other Products | 6,437.56 | 0.9667 |
| 44 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C51` | PURE | Aptus Value Housing Finance India Ltd. | INE852O01025 | Finance | 6,293.95 | 0.9451 |
| 45 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C52` | PURE | Union Bank of India | INE692A01016 | Banks | 6,185.34 | 0.9288 |
| 46 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C53` | PURE | Anant Raj Ltd. | INE242C01024 | Realty | 5,940.25 | 0.8920 |
| 47 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C54` | PURE | Ajanta Pharma Ltd. | INE031B01049 | Pharmaceuticals & Biotechnology | 5,454.30 | 0.8191 |
| 48 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C55` | PURE | Asahi India Glass Ltd. | INE439A01020 | Auto Components | 5,208.20 | 0.7821 |
| 49 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C56` | PURE | PCBL Chemical Ltd. | INE602A01031 | Chemicals & Petrochemicals | 5,113.62 | 0.7679 |
| 50 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C57` | PURE | SBI Life Insurance Co. Ltd. | INE123W01016 | Insurance | 4,930.50 | 0.7404 |
| 51 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C58` | PURE | Gland Pharma Ltd. | INE068V01023 | Pharmaceuticals & Biotechnology | 4,920.72 | 0.7389 |
| 52 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C59` | PURE | Power Mech Projects Ltd. | INE211R01019 | Construction | 4,845.39 | 0.7276 |
| 53 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C60` | PURE | NMDC Ltd. | INE584A01023 | Minerals & Mining | 4,628.84 | 0.6951 |
| 54 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C61` | PURE | Adani Green Energy Ltd. | INE364U01010 | Power | 4,560.77 | 0.6849 |
| 55 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C62` | PURE | Angel One Ltd. | INE732I01021 | Capital Markets | 4,549.78 | 0.6832 |
| 56 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C63` | PURE | PI Industries Ltd. | INE603J01030 | Fertilizers & Agrochemicals | 4,442.73 | 0.6672 |
| 57 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C64` | PURE | Tata Steel Ltd. | INE081A01020 | Ferrous Metals | 4,440.27 | 0.6668 |
| 58 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C65` | PURE | Mahanagar Gas Ltd. | INE002S01010 | Gas | 4,059.46 | 0.6096 |
| 59 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C66` | PURE | Strides Pharma Science Ltd. | INE939A01011 | Pharmaceuticals & Biotechnology | 3,662.30 | 0.5500 |
| 60 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C67` | PURE | Ujjivan Small Finance Bank Ltd. | INE551W01018 | Banks | 3,639.50 | 0.5465 |
| 61 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C68` | PURE | Capillary Technologies India Ltd. | INE0ILV01024 | IT - Software | 3,384.41 | 0.5082 |
| 62 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C69` | PURE | Container Corporation of India Ltd. | INE111A01025 | Transport Services | 3,356.25 | 0.5040 |
| 63 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C70` | PURE | Adani Power Ltd. | INE814H01029 | Power | 3,316.84 | 0.4981 |
| 64 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C71` | PURE | Bharat Electronics Ltd. | INE263A01024 | Aerospace & Defense | 3,240.82 | 0.4867 |
| 65 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C72` | PURE | Praj Industries Ltd. | INE074A01025 | Industrial Manufacturing | 2,910.85 | 0.4371 |
| 66 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C73` | PURE | Piramal Finance Ltd. | INE202B01038 | Finance | 2,805.87 | 0.4213 |
| 67 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C74` | PURE | Samhi Hotels Ltd. | INE08U801020 | Leisure Services | 2,349.12 | 0.3528 |
| 68 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!C75` | PURE | Indiqube Spaces Ltd. | INE06ST01018 | Commercial Services & Supplies | 2,039.54 | 0.3063 |

- [ ] checked against the Excel

## T035 · debt

**Question:** List all holdings of the Medium Term Fund rated IND AA as on 30 Sep 2026.

**Gold answer:** 2 item(s): 8.73% Eris Lifesciences Ltd. (07/12/2026) **; 8.73% Eris Lifesciences Ltd. (07/06/2027) **

**How it is computed** (`instruments_by_rating`): Instrument names (column C) of the non-equity rows whose rating (column E) matches. 2 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLMTP'!E47` | BSLMTP | 8.73% Eris Lifesciences Ltd. (07/12/2026) ** | INE406M08011 | IND AA | 2,404.75 | 0.7136 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLMTP'!E48` | BSLMTP | 8.73% Eris Lifesciences Ltd. (07/06/2027) ** | INE406M08029 | IND AA | 2,401.74 | 0.7127 |

- [ ] checked against the Excel

## T041 · debt

**Question:** List all holdings of Aditya Birla Sun Life Banking & PSU Debt Fund rated IND AAA(SO) as on 30 Sep 2026.

**Gold answer:** 4 item(s): India Universal Trust AL1 (20/09/2030) **; India Universal Trust AL2 (21/11/2030) **; India Universal Trust AL2 (21/09/2027) **; India Universal Trust AL1 (20/03/2027) **

**How it is computed** (`instruments_by_rating`): Instrument names (column C) of the non-equity rows whose rating (column E) matches. 4 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLSTF'!E103` | BSLSTF | India Universal Trust AL1 (20/09/2030) ** | INE16J715035 | IND AAA(SO) | 1,759.95 | 0.2085 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLSTF'!E104` | BSLSTF | India Universal Trust AL2 (21/11/2030) ** | INE1CBK15037 | IND AAA(SO) | 724.22 | 0.0858 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLSTF'!E105` | BSLSTF | India Universal Trust AL2 (21/09/2027) ** | INE1CBK15029 | IND AAA(SO) | 405.27 | 0.0480 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLSTF'!E106` | BSLSTF | India Universal Trust AL1 (20/03/2027) ** | INE16J715027 | IND AAA(SO) | 387.05 | 0.0459 |

- [ ] checked against the Excel

## T048 · cross_scheme

**Question:** As on 30 Sep 2026, does the Nifty SDL Sep 2027 Index Fund or the CRISIL IBX Gilt Apr 2028 Index Fund have a bigger share of its AUM in Government of India (21/09/2027)?

**Gold answer:** CIGAPR28 (CRISIL IBX Gilt Apr 2028 Index Fund)

**How it is computed** (`which_holds_more`): Compare column H (% to AUM) or column G (value) of the holding in each scheme. 2 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'NSDSEP27'!H17` | NSDSEP27 | Government of India (21/09/2027) | IN0020070069 | Sovereign | 18.34 | 0.4244 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'CIGAPR28'!H9` | CIGAPR28 | Government of India (21/09/2027) | IN0020070069 | Sovereign | 425.94 | 20.2735 |

- [ ] checked against the Excel
