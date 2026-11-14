# Manual check of gold answers (FR-5.4)

10 of the 24 answerable questions, picked with `random.Random(42)`. Unanswerable questions are left out (nothing to check).

**How to check:** open the file named in each cell reference, go to the sheet (tab) and the cell, and compare with the table. Then check the gold answer is what the question asks for. Tick the box, or write what is wrong next to it.

Columns in every sheet: C instrument, D ISIN, E industry / rating, F quantity, G market value (Rs lakhs), H % to AUM. The file stores % as a fraction (0.0560 = 5.60 %); the tables show percent.

| Id | Type | Gold answer | OK? |
|---|---|---|---|
| Q01 | lookup | 5.5967 % | [OK] |
| Q03 | lookup | 3.3895 % | [OK] |
| Q04 | lookup | 19,880.41 Rs lakhs | [Ok] |
| Q05 | lookup | 7.8505 % | [OK] |
| Q08 | aggregation | 19.2399 % | [OK] |
| Q09 | aggregation | 57.0053 % | [Ok] |
| Q10 | aggregation | 27.4111 % | [Ok] |
| Q20 | cross_scheme | BSLFEF (Large Cap) | [Ok] |
| Q21 | cross_scheme | PURE (Value Fund) | [Ok] |
| Q23 | cross_scheme | 29 | [OK] |

## Q01 · lookup

**Question:** What % of AUM does Aditya Birla Sun Life Flexi Cap Fund hold in ICICI Bank Ltd. as on 30 Sep 2026?

**Gold answer:** 5.5967 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H8` | BSLEQTY | ICICI Bank Ltd. | INE090A01021 | Banks | 156,610.49 | 5.5967 |

- [Ok] checked against the Excel

## Q03 · lookup

**Question:** What % of AUM does Aditya Birla Sun Life Small Cap Fund hold in TD Power Systems Ltd. as on 30 Sep 2026?

**Gold answer:** 3.3895 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLTA1'!H8` | BSLTA1 | TD Power Systems Ltd. | INE419M01035 | Electrical Equipment | 20,742.59 | 3.3895 |

- [Ok] checked against the Excel

## Q04 · lookup

**Question:** What is the market value, in Rs lakhs, of The Federal Bank Ltd. held by Aditya Birla Sun Life Midcap Fund as on 30 Sep 2026?

**Gold answer:** 19,880.41 Rs lakhs

**How it is computed** (`holding_value`): Market value of that holding in Rs lakhs (column G). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'MIDCAP'!G8` | MIDCAP | The Federal Bank Ltd. | INE171A01029 | Banks | 19,880.41 | 3.0352 |

- [Ok] checked against the Excel

## Q05 · lookup

**Question:** What % of AUM does Aditya Birla Sun Life Digital India Fund hold in Tech Mahindra Ltd. as on 30 Sep 2026?

**Gold answer:** 7.8505 %

**How it is computed** (`holding_pct`): % to AUM of that holding (column H). 1 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H9` | BSLNMF | Tech Mahindra Ltd. | INE669C01036 | IT - Software | 28,393.74 | 7.8505 |

- [Ok] checked against the Excel

## Q08 · aggregation

**Question:** What is the total % of AUM in equity holdings of the Banks industry for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026?

**Gold answer:** 19.2399 %

**How it is computed** (`industry_total`): Sum of column H over the equity rows whose Industry (column E) is the one asked. 7 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H8` | BSLEQTY | ICICI Bank Ltd. | INE090A01021 | Banks | 156,610.49 | 5.5967 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H9` | BSLEQTY | HDFC Bank Ltd. | INE040A01034 | Banks | 109,397.87 | 3.9095 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H10` | BSLEQTY | Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 99,454.50 | 3.5542 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H12` | BSLEQTY | State Bank of India | INE062A01020 | Banks | 58,582.27 | 2.0935 |
| 5 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H30` | BSLEQTY | The Federal Bank Ltd. | INE171A01029 | Banks | 43,642.50 | 1.5596 |
| 6 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H32` | BSLEQTY | Axis Bank Ltd. | INE238A01034 | Banks | 42,910.00 | 1.5335 |
| 7 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H51` | BSLEQTY | AU Small Finance Bank Ltd. | INE949L01017 | Banks | 27,783.25 | 0.9929 |

- [Ok] checked against the Excel

## Q09 · aggregation

**Question:** What is the total % of AUM in equity holdings of the IT - Software industry for Aditya Birla Sun Life Digital India Fund as on 30 Sep 2026?

**Gold answer:** 57.0053 %

**How it is computed** (`industry_total`): Sum of column H over the equity rows whose Industry (column E) is the one asked. 19 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H8` | BSLNMF | Infosys Ltd. | INE009A01021 | IT - Software | 35,932.35 | 9.9348 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H9` | BSLNMF | Tech Mahindra Ltd. | INE669C01036 | IT - Software | 28,393.74 | 7.8505 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H10` | BSLNMF | Tata Consultancy Services Ltd. | INE467B01029 | IT - Software | 26,025.31 | 7.1957 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H13` | BSLNMF | Coforge Ltd. | INE591G01025 | IT - Software | 18,449.44 | 5.1010 |
| 5 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H14` | BSLNMF | Persistent Systems Ltd. | INE262H01021 | IT - Software | 17,779.20 | 4.9157 |
| 6 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H16` | BSLNMF | HCL Technologies Ltd. | INE860A01027 | IT - Software | 12,834.37 | 3.5485 |
| 7 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H17` | BSLNMF | LTM Ltd. | INE214T01019 | IT - Software | 12,114.17 | 3.3494 |
| 8 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H21` | BSLNMF | Hexaware Technologies Ltd. | INE093A01041 | IT - Software | 7,770.49 | 2.1484 |
| 9 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H22` | BSLNMF | Rategain Travel Technologies Ltd. | INE0CLI01024 | IT - Software | 6,835.14 | 1.8898 |
| 10 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H25` | BSLNMF | Sonata Software Ltd. | INE269A01021 | IT - Software | 5,577.45 | 1.5421 |
| 11 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H27` | BSLNMF | Capillary Technologies India Ltd. | INE0ILV01024 | IT - Software | 4,987.24 | 1.3789 |
| 12 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H28` | BSLNMF | KPIT Technologies Ltd. | INE04I401011 | IT - Software | 4,834.93 | 1.3368 |
| 13 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H29` | BSLNMF | Latent View Analytics Ltd. | INE0I7C01011 | IT - Software | 4,445.80 | 1.2292 |
| 14 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H34` | BSLNMF | Mastek Ltd. | INE759A01021 | IT - Software | 3,485.48 | 0.9637 |
| 15 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H38` | BSLNMF | Mphasis Ltd. | INE356A01018 | IT - Software | 2,154.40 | 0.5957 |
| 16 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H39` | BSLNMF | Oracle Financial Services Software Ltd. | INE881D01027 | IT - Software | 1,921.59 | 0.5313 |
| 17 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H46` | BSLNMF | Cognizant Technology Solutions Corporation | US1924461023 | IT - Software | 7,656.42 | 2.1169 |
| 18 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H47` | BSLNMF | Adobe Inc | US00724F1012 | IT - Software | 2,544.85 | 0.7036 |
| 19 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLNMF'!H48` | BSLNMF | Microsoft Corporation | US5949181045 | IT - Software | 2,434.89 | 0.6732 |

- [Ok] checked against the Excel

## Q10 · aggregation

**Question:** What share of AUM do the top 5 equity holdings (by % of AUM) of Aditya Birla Sun Life Large Cap Fund make up together, as on 30 Sep 2026?

**Gold answer:** 27.4111 %

**How it is computed** (`top_n_share`): Sum of column H over the n largest equity rows by % to AUM. 5 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H8` | BSLFEF | ICICI Bank Ltd. | INE090A01021 | Banks | 216,075.38 | 7.7356 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H9` | BSLFEF | HDFC Bank Ltd. | INE040A01034 | Banks | 204,580.43 | 7.3241 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H10` | BSLFEF | Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 135,264.21 | 4.8425 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H11` | BSLFEF | Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 114,675.00 | 4.1054 |
| 5 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H12` | BSLFEF | State Bank of India | INE062A01020 | Banks | 95,069.66 | 3.4035 |

- [Ok] checked against the Excel

## Q20 · cross_scheme

**Question:** Which holds more Infosys Ltd. as a % of AUM as on 30 Sep 2026: Aditya Birla Sun Life Flexi Cap Fund or Aditya Birla Sun Life Large Cap Fund?

**Gold answer:** BSLFEF (Large Cap)

**How it is computed** (`which_holds_more`): Compare column H (% to AUM) or column G (value) of the holding in each scheme. 2 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H13` | BSLEQTY | Infosys Ltd. | INE009A01021 | IT - Software | 56,291.08 | 2.0117 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLFEF'!H13` | BSLFEF | Infosys Ltd. | INE009A01021 | IT - Software | 89,469.00 | 3.2030 |

- [Ok] checked against the Excel

## Q21 · cross_scheme

**Question:** Which holds more HDFC Bank Ltd. as a % of AUM as on 30 Sep 2026: Aditya Birla Sun Life Flexi Cap Fund or Aditya Birla Sun Life Value Fund?

**Gold answer:** PURE (Value Fund)

**How it is computed** (`which_holds_more`): Compare column H (% to AUM) or column G (value) of the holding in each scheme. 2 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H9` | BSLEQTY | HDFC Bank Ltd. | INE040A01034 | Banks | 109,397.87 | 3.9095 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'PURE'!H8` | PURE | HDFC Bank Ltd. | INE040A01034 | Banks | 32,547.08 | 4.8875 |

- [Ok] checked against the Excel

## Q23 · cross_scheme

**Question:** How many equity holdings (same company in the Equity & Equity Related section) do Aditya Birla Sun Life Flexi Cap Fund and Aditya Birla Sun Life Large & Mid Cap Fund have in common as on 30 Sep 2026?

**Gold answer:** 29

**How it is computed** (`overlap_count`): Number of ISINs (column D) that appear in the equity sections of both schemes. 58 row(s).

| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |
|---|---|---|---|---|---|---|---|
| 1 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D14` | ADVG | Astral Ltd. | INE006I01046 | Industrial Products | 13,012.11 | 2.3225 |
| 2 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D63` | BSLEQTY | Astral Ltd. | INE006I01046 | Industrial Products | 21,016.74 | 0.7511 |
| 3 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D57` | ADVG | Larsen & Toubro Ltd. | INE018A01030 | Construction | 5,200.04 | 0.9282 |
| 4 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D41` | BSLEQTY | Larsen & Toubro Ltd. | INE018A01030 | Construction | 38,264.84 | 1.3675 |
| 5 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D15` | ADVG | Ajanta Pharma Ltd. | INE031B01049 | Pharmaceuticals & Biotechnology | 12,738.30 | 2.2737 |
| 6 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D76` | BSLEQTY | Ajanta Pharma Ltd. | INE031B01049 | Pharmaceuticals & Biotechnology | 14,150.34 | 0.5057 |
| 7 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D19` | ADVG | Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 11,314.30 | 2.0195 |
| 8 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D22` | BSLEQTY | Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 48,018.98 | 1.7160 |
| 9 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D28` | ADVG | State Bank of India | INE062A01020 | Banks | 9,192.82 | 1.6408 |
| 10 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D12` | BSLEQTY | State Bank of India | INE062A01020 | Banks | 58,582.27 | 2.0935 |
| 11 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D61` | ADVG | CG Power and Industrial Solutions Ltd. | INE067A01029 | Electrical Equipment | 4,514.23 | 0.8057 |
| 12 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D34` | BSLEQTY | CG Power and Industrial Solutions Ltd. | INE067A01029 | Electrical Equipment | 42,332.38 | 1.5128 |
| 13 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D36` | ADVG | Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 7,414.53 | 1.3234 |
| 14 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D14` | BSLEQTY | Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 55,610.00 | 1.9873 |
| 15 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D8` | ADVG | ICICI Bank Ltd. | INE090A01021 | Banks | 21,668.17 | 3.8676 |
| 16 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D8` | BSLEQTY | ICICI Bank Ltd. | INE090A01021 | Banks | 156,610.49 | 5.5967 |
| 17 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D79` | ADVG | Hindustan Petroleum Corporation Ltd. | INE094A01015 | Petroleum Products | 2,275.06 | 0.4061 |
| 18 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D49` | BSLEQTY | Hindustan Petroleum Corporation Ltd. | INE094A01015 | Petroleum Products | 29,779.75 | 1.0642 |
| 19 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D35` | ADVG | Meesho Ltd. | INE0VDM01015 | Retailing | 7,832.05 | 1.3979 |
| 20 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D37` | BSLEQTY | Meesho Ltd. | INE0VDM01015 | Retailing | 40,311.75 | 1.4406 |
| 21 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D34` | ADVG | Mahindra & Mahindra Ltd. | INE101A01026 | Automobiles | 8,131.56 | 1.4514 |
| 22 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D39` | BSLEQTY | Mahindra & Mahindra Ltd. | INE101A01026 | Automobiles | 39,387.28 | 1.4076 |
| 23 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D45` | ADVG | Metropolis Healthcare Ltd. | INE112L01020 | Healthcare Services | 6,159.13 | 1.0993 |
| 24 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D72` | BSLEQTY | Metropolis Healthcare Ltd. | INE112L01020 | Healthcare Services | 15,167.60 | 0.5420 |
| 25 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D17` | ADVG | Max Financial Services Ltd. | INE180A01020 | Insurance | 12,002.12 | 2.1423 |
| 26 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D64` | BSLEQTY | Max Financial Services Ltd. | INE180A01020 | Insurance | 20,601.00 | 0.7362 |
| 27 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D60` | ADVG | Tata Consumer Products Ltd. | INE192A01025 | Agricultural Food & other Products | 4,651.88 | 0.8303 |
| 28 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D36` | BSLEQTY | Tata Consumer Products Ltd. | INE192A01025 | Agricultural Food & other Products | 40,353.75 | 1.4421 |
| 29 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D39` | ADVG | Axis Bank Ltd. | INE238A01034 | Banks | 6,741.44 | 1.2033 |
| 30 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D32` | BSLEQTY | Axis Bank Ltd. | INE238A01034 | Banks | 42,910.00 | 1.5335 |
| 31 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D47` | ADVG | Persistent Systems Ltd. | INE262H01021 | IT - Software | 5,673.55 | 1.0127 |
| 32 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D29` | BSLEQTY | Persistent Systems Ltd. | INE262H01021 | IT - Software | 44,192.52 | 1.5793 |
| 33 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D62` | ADVG | Bharti Airtel Ltd. | INE397D01024 | Telecom - Services | 4,308.69 | 0.7691 |
| 34 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D23` | BSLEQTY | Bharti Airtel Ltd. | INE397D01024 | Telecom - Services | 47,439.00 | 1.6953 |
| 35 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D71` | ADVG | SBFC Finance Ltd. | INE423Y01016 | Finance | 3,372.11 | 0.6019 |
| 36 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D61` | BSLEQTY | SBFC Finance Ltd. | INE423Y01016 | Finance | 22,224.80 | 0.7942 |
| 37 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D52` | ADVG | Apollo Hospitals Enterprise Ltd. | INE437A01024 | Healthcare Services | 5,473.33 | 0.9769 |
| 38 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D58` | BSLEQTY | Apollo Hospitals Enterprise Ltd. | INE437A01024 | Healthcare Services | 24,496.50 | 0.8754 |
| 39 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D32` | ADVG | Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 8,607.94 | 1.5364 |
| 40 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D17` | BSLEQTY | Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 51,888.38 | 1.8543 |
| 41 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D66` | ADVG | Tech Mahindra Ltd. | INE669C01036 | IT - Software | 4,012.31 | 0.7162 |
| 42 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D31` | BSLEQTY | Tech Mahindra Ltd. | INE669C01036 | IT - Software | 42,984.48 | 1.5361 |
| 43 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D10` | ADVG | APL Apollo Tubes Ltd. | INE702C01027 | Industrial Products | 15,735.28 | 2.8086 |
| 44 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D33` | BSLEQTY | APL Apollo Tubes Ltd. | INE702C01027 | Industrial Products | 42,729.46 | 1.5270 |
| 45 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D31` | ADVG | Jindal Steel Ltd. | INE749A01030 | Ferrous Metals | 8,827.20 | 1.5756 |
| 46 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D26` | BSLEQTY | Jindal Steel Ltd. | INE749A01030 | Ferrous Metals | 45,396.00 | 1.6223 |
| 47 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D21` | ADVG | Eternal Ltd. | INE758T01015 | Retailing | 10,779.50 | 1.9240 |
| 48 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D44` | BSLEQTY | Eternal Ltd. | INE758T01015 | Retailing | 35,639.65 | 1.2736 |
| 49 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D20` | ADVG | GMR Airports Ltd. | INE776C01039 | Transport Infrastructure | 11,248.75 | 2.0078 |
| 50 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D38` | BSLEQTY | GMR Airports Ltd. | INE776C01039 | Transport Infrastructure | 39,409.87 | 1.4084 |
| 51 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D38` | ADVG | Trent Ltd. | INE849A01020 | Retailing | 7,318.59 | 1.3063 |
| 52 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D21` | BSLEQTY | Trent Ltd. | INE849A01020 | Retailing | 48,469.45 | 1.7321 |
| 53 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D56` | ADVG | Bajaj Finserv Ltd. | INE918I01026 | Finance | 5,234.67 | 0.9343 |
| 54 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D43` | BSLEQTY | Bajaj Finserv Ltd. | INE918I01026 | Finance | 36,351.00 | 1.2991 |
| 55 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D63` | ADVG | Adani Energy Solutions Ltd. | INE931S01010 | Power | 4,235.37 | 0.7560 |
| 56 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D46` | BSLEQTY | Adani Energy Solutions Ltd. | INE931S01010 | Power | 32,865.00 | 1.1745 |
| 57 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'ADVG'!D9` | ADVG | AU Small Finance Bank Ltd. | INE949L01017 | Banks | 19,326.93 | 3.4497 |
| 58 | `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!D51` | BSLEQTY | AU Small Finance Bank Ltd. | INE949L01017 | Banks | 27,783.25 | 0.9929 |

- [Ok] checked against the Excel
