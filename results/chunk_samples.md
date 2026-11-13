# Chunk samples (Phase 2)

Month 2026-09-30. For each chunker, the first 2 chunks of each sample scheme (`BSLEQTY`, `BSLCBF`). Long chunks are cut after 20 lines here only; the real chunk keeps all of its text.

## fixed_size

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (13 chunks)

**`fixed_size:2026-09-30:BSLEQTY:0`**: 258 tokens, 7 holding rows, rows 8–14 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: ALL
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60
HDFC Bank Ltd. | INE040A01034 | Banks | 15436415 | 109397.87 | 3.91
Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 23850000 | 99454.50 | 3.55
Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 5706067 | 67731.02 | 2.42
State Bank of India | INE062A01020 | Banks | 6105500 | 58582.27 | 2.09
Infosys Ltd. | INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Bl
```

**`fixed_size:2026-09-30:BSLEQTY:1`**: 258 tokens, 8 holding rows, rows 13–20 of sheet `BSLEQTY`

```text
| INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 6700000 | 55610.00 | 1.99
Bharat Forge Ltd. | INE465A01025 | Auto Components | 2800000 | 53928.00 | 1.93
Lenskart Solutions Ltd. | INE956O01016 | Retailing | 7750000 | 53091.38 | 1.90
Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 2072385 | 51888.38 | 1.85
United Spirits Ltd. | INE854D01024 | Beverages | 3736609 | 50593.69 | 1.81
HCL Technologies Ltd. | INE860A01027 | IT - Software | 4103703 | 50475.55 | 1.80
Shriram Finance Ltd. | INE721A01047 | Finance | 5000000 | 49135.00 | 1.76
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (12 chunks)

**`fixed_size:2026-09-30:BSLCBF:0`**: 258 tokens, 5 holding rows, rows 8–16 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: ALL
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Nexus Select Trust | INE0NDH25011 | Realty | 1210418 | 2025.03 | 1.22
Embassy Office Parks Reit | INE041025011 | Realty | 382865 | 1663.24 | 1.00
[Debt Instruments > a) Listed/awaiting listing on the stock exchanges]
9.10% SK Finance Ltd. (10/08/2029) ** | INE124N07820 | IND AA- | 9300 | 9156.63 | 5.53
8.73% Eris Lifesciences Ltd. (07/06/2027) ** | INE406M08029 | IND AA | 7400 | 7405.37 | 4.47
Jubilant Bevco Ltd. (31/05/2028) (ZCB) | INE1D4P08019 |
```

**`fixed_size:2026-09-30:BSLCBF:1`**: 258 tokens, 7 holding rows, rows 15–21 of sheet `BSLCBF`

```text
47
Jubilant Bevco Ltd. (31/05/2028) (ZCB) | INE1D4P08019 | CRISIL AA | 6500 | 7311.03 | 4.41
JTPM Metal Traders Ltd. (29/09/2028) (ZCB) ** | INE02PE08036 | CRISIL AA | 5877 | 6342.04 | 3.83
8.45% Adani Airport Holdings Ltd. (12/02/2029) ** | INE0GCN07054 | IND AA- | 6000 | 5939.24 | 3.58
5.00% GMR Airports Ltd. (13/02/2027) ** | INE776C08083 | CRISIL AA- | 5200 | 5523.46 | 3.33
7.46% REC Ltd. (30/06/2028) ** | INE020B08EK4 | ICRA AAA | 5000 | 4980.05 | 3.01
6.66% Small Industries Development Bank of India (25/10/2028) ** | INE556F
```

## row_wise

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (86 chunks)

**`row_wise:2026-09-30:BSLEQTY:0`**: 101 tokens, 1 holding rows, rows 8–8 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: ICICI Bank Ltd. | ISIN: INE090A01021 | Industry/Rating: Banks | Qty: 11849171 | Value (Rs L): 156610.49 | % to AUM: 5.60
```

**`row_wise:2026-09-30:BSLEQTY:1`**: 101 tokens, 1 holding rows, rows 9–9 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: HDFC Bank Ltd. | ISIN: INE040A01034 | Industry/Rating: Banks | Qty: 15436415 | Value (Rs L): 109397.87 | % to AUM: 3.91
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (57 chunks)

**`row_wise:2026-09-30:BSLCBF:0`**: 98 tokens, 1 holding rows, rows 8–8 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: Nexus Select Trust | ISIN: INE0NDH25011 | Industry/Rating: Realty | Qty: 1210418 | Value (Rs L): 2025.03 | % to AUM: 1.22
```

**`row_wise:2026-09-30:BSLCBF:1`**: 98 tokens, 1 holding rows, rows 9–9 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: Embassy Office Parks Reit | ISIN: INE041025011 | Industry/Rating: Realty | Qty: 382865 | Value (Rs L): 1663.24 | % to AUM: 1.00
```

## header_window

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (9 chunks)

**`header_window:2026-09-30:BSLEQTY:0`**: 392 tokens, 10 holding rows, rows 8–17 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60
HDFC Bank Ltd. | INE040A01034 | Banks | 15436415 | 109397.87 | 3.91
Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 23850000 | 99454.50 | 3.55
Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 5706067 | 67731.02 | 2.42
State Bank of India | INE062A01020 | Banks | 6105500 | 58582.27 | 2.09
Infosys Ltd. | INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 6700000 | 55610.00 | 1.99
Bharat Forge Ltd. | INE465A01025 | Auto Components | 2800000 | 53928.00 | 1.93
Lenskart Solutions Ltd. | INE956O01016 | Retailing | 7750000 | 53091.38 | 1.90
Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 2072385 | 51888.38 | 1.85
```

**`header_window:2026-09-30:BSLEQTY:1`**: 388 tokens, 10 holding rows, rows 18–27 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
United Spirits Ltd. | INE854D01024 | Beverages | 3736609 | 50593.69 | 1.81
HCL Technologies Ltd. | INE860A01027 | IT - Software | 4103703 | 50475.55 | 1.80
Shriram Finance Ltd. | INE721A01047 | Finance | 5000000 | 49135.00 | 1.76
Trent Ltd. | INE849A01020 | Retailing | 1848850 | 48469.45 | 1.73
Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 5098639 | 48018.98 | 1.72
Bharti Airtel Ltd. | INE397D01024 | Telecom - Services | 2700000 | 47439.00 | 1.70
Ather Energy Ltd. | INE0LEZ01016 | Automobiles | 3300000 | 47025.00 | 1.68
Dr. Lal Path labs Ltd. | INE600L01024 | Healthcare Services | 2350000 | 46694.50 | 1.67
Jindal Steel Ltd. | INE749A01030 | Ferrous Metals | 4000000 | 45396.00 | 1.62
Welspun Corp Ltd. | INE191B01025 | Industrial Products | 1650000 | 44830.50 | 1.60
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (6 chunks)

**`header_window:2026-09-30:BSLCBF:0`**: 510 tokens, 10 holding rows, rows 8–21 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: Equity & Equity Related; Debt Instruments
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Nexus Select Trust | INE0NDH25011 | Realty | 1210418 | 2025.03 | 1.22
Embassy Office Parks Reit | INE041025011 | Realty | 382865 | 1663.24 | 1.00
[Debt Instruments > a) Listed/awaiting listing on the stock exchanges]
9.10% SK Finance Ltd. (10/08/2029) ** | INE124N07820 | IND AA- | 9300 | 9156.63 | 5.53
8.73% Eris Lifesciences Ltd. (07/06/2027) ** | INE406M08029 | IND AA | 7400 | 7405.37 | 4.47
Jubilant Bevco Ltd. (31/05/2028) (ZCB) | INE1D4P08019 | CRISIL AA | 6500 | 7311.03 | 4.41
JTPM Metal Traders Ltd. (29/09/2028) (ZCB) ** | INE02PE08036 | CRISIL AA | 5877 | 6342.04 | 3.83
8.45% Adani Airport Holdings Ltd. (12/02/2029) ** | INE0GCN07054 | IND AA- | 6000 | 5939.24 | 3.58
5.00% GMR Airports Ltd. (13/02/2027) ** | INE776C08083 | CRISIL AA- | 5200 | 5523.46 | 3.33
7.46% REC Ltd. (30/06/2028) ** | INE020B08EK4 | ICRA AAA | 5000 | 4980.05 | 3.01
6.66% Small Industries Development Bank of India (25/10/2028) ** | INE556F08KZ3 | CRISIL AAA | 5000 | 4889.67 | 2.95
```

**`header_window:2026-09-30:BSLCBF:1`**: 524 tokens, 10 holding rows, truncated, rows 22–31 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: Debt Instruments
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Debt Instruments > a) Listed/awaiting listing on the stock exchanges]
7.79% Tata Capital Housing Finance Ltd. (18/06/2030) ** | INE033L07IU8 | ICRA AAA | 4467 | 4401.38 | 2.66
9.25% Hinduja Leyland Finance Ltd. (09/07/2031) | INE146O08399 | CRISIL AA+ | 3500 | 3480.25 | 2.10
6.66% National Bank for Agriculture and Rural Development (12/10/2028) ** | INE261F08EP4 | ICRA AAA | 3500 | 3426.77 | 2.07
9.50% Kogta Financial (India) Ltd. (30/10/2027) ** | INE192U07376 | CARE AA- | 3250 | 3222.27 | 1.94
11.46% Gaursons India Pvt. Ltd. (26/12/2028) ** | INE1BEC07011 | ICRA A- | 3200 | 3194.72 | 1.93
9.45% Vedanta Ltd. (05/06/2028) ** | INE205A08053 | CRISIL AA+ | 3000 | 3033.65 | 1.83
8.75% JSW Energy Ltd. (20/03/2028) ** | INE121E08047 | ICRA AA | 3000 | 3006.98 | 1.81
8.50% SIS Ltd. (26/03/2028) ** | INE285J07058 | CRISIL AA- | 3000 | 2998.73 | 1.81
8.32% Hero Housing Finance Ltd. (30/08/2027) ** | INE800X07097 | ICRA AA+ | 3000 | 2990.64 | 1.80
8.50% IKF Finance Ltd. (10/03/2028) ** | INE859C07253 | IND AA- | 30000 | 2974.71 | 1.80
```

## scheme_level

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (1 chunks)

**`scheme_level:2026-09-30:BSLEQTY:0`**: 2,831 tokens, 86 holding rows, truncated, rows 8–103 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: ALL
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60
HDFC Bank Ltd. | INE040A01034 | Banks | 15436415 | 109397.87 | 3.91
Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 23850000 | 99454.50 | 3.55
Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 5706067 | 67731.02 | 2.42
State Bank of India | INE062A01020 | Banks | 6105500 | 58582.27 | 2.09
Infosys Ltd. | INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 6700000 | 55610.00 | 1.99
Bharat Forge Ltd. | INE465A01025 | Auto Components | 2800000 | 53928.00 | 1.93
Lenskart Solutions Ltd. | INE956O01016 | Retailing | 7750000 | 53091.38 | 1.90
Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 2072385 | 51888.38 | 1.85
United Spirits Ltd. | INE854D01024 | Beverages | 3736609 | 50593.69 | 1.81
HCL Technologies Ltd. | INE860A01027 | IT - Software | 4103703 | 50475.55 | 1.80
Shriram Finance Ltd. | INE721A01047 | Finance | 5000000 | 49135.00 | 1.76
Trent Ltd. | INE849A01020 | Retailing | 1848850 | 48469.45 | 1.73
Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 5098639 | 48018.98 | 1.72
... (74 more lines)
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (1 chunks)

**`scheme_level:2026-09-30:BSLCBF:0`**: 2,503 tokens, 57 holding rows, truncated, rows 8–88 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: ALL
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Nexus Select Trust | INE0NDH25011 | Realty | 1210418 | 2025.03 | 1.22
Embassy Office Parks Reit | INE041025011 | Realty | 382865 | 1663.24 | 1.00
[Debt Instruments > a) Listed/awaiting listing on the stock exchanges]
9.10% SK Finance Ltd. (10/08/2029) ** | INE124N07820 | IND AA- | 9300 | 9156.63 | 5.53
8.73% Eris Lifesciences Ltd. (07/06/2027) ** | INE406M08029 | IND AA | 7400 | 7405.37 | 4.47
Jubilant Bevco Ltd. (31/05/2028) (ZCB) | INE1D4P08019 | CRISIL AA | 6500 | 7311.03 | 4.41
JTPM Metal Traders Ltd. (29/09/2028) (ZCB) ** | INE02PE08036 | CRISIL AA | 5877 | 6342.04 | 3.83
8.45% Adani Airport Holdings Ltd. (12/02/2029) ** | INE0GCN07054 | IND AA- | 6000 | 5939.24 | 3.58
5.00% GMR Airports Ltd. (13/02/2027) ** | INE776C08083 | CRISIL AA- | 5200 | 5523.46 | 3.33
7.46% REC Ltd. (30/06/2028) ** | INE020B08EK4 | ICRA AAA | 5000 | 4980.05 | 3.01
6.66% Small Industries Development Bank of India (25/10/2028) ** | INE556F08KZ3 | CRISIL AAA | 5000 | 4889.67 | 2.95
7.79% Tata Capital Housing Finance Ltd. (18/06/2030) ** | INE033L07IU8 | ICRA AAA | 4467 | 4401.38 | 2.66
9.25% Hinduja Leyland Finance Ltd. (09/07/2031) | INE146O08399 | CRISIL AA+ | 3500 | 3480.25 | 2.10
6.66% National Bank for Agriculture and Rural Development (12/10/2028) ** | INE261F08EP4 | ICRA AAA | 3500 | 3426.77 | 2.07
9.50% Kogta Financial (India) Ltd. (30/10/2027) ** | INE192U07376 | CARE AA- | 3250 | 3222.27 | 1.94
... (49 more lines)
```

## section_aware

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (9 chunks)

**`section_aware:2026-09-30:BSLEQTY:0`**: 485 tokens, 13 holding rows, rows 8–20 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60
HDFC Bank Ltd. | INE040A01034 | Banks | 15436415 | 109397.87 | 3.91
Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 23850000 | 99454.50 | 3.55
Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 5706067 | 67731.02 | 2.42
State Bank of India | INE062A01020 | Banks | 6105500 | 58582.27 | 2.09
Infosys Ltd. | INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 6700000 | 55610.00 | 1.99
Bharat Forge Ltd. | INE465A01025 | Auto Components | 2800000 | 53928.00 | 1.93
Lenskart Solutions Ltd. | INE956O01016 | Retailing | 7750000 | 53091.38 | 1.90
Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 2072385 | 51888.38 | 1.85
United Spirits Ltd. | INE854D01024 | Beverages | 3736609 | 50593.69 | 1.81
HCL Technologies Ltd. | INE860A01027 | IT - Software | 4103703 | 50475.55 | 1.80
Shriram Finance Ltd. | INE721A01047 | Finance | 5000000 | 49135.00 | 1.76
```

**`section_aware:2026-09-30:BSLEQTY:1`**: 487 tokens, 13 holding rows, rows 21–33 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Trent Ltd. | INE849A01020 | Retailing | 1848850 | 48469.45 | 1.73
Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 5098639 | 48018.98 | 1.72
Bharti Airtel Ltd. | INE397D01024 | Telecom - Services | 2700000 | 47439.00 | 1.70
Ather Energy Ltd. | INE0LEZ01016 | Automobiles | 3300000 | 47025.00 | 1.68
Dr. Lal Path labs Ltd. | INE600L01024 | Healthcare Services | 2350000 | 46694.50 | 1.67
Jindal Steel Ltd. | INE749A01030 | Ferrous Metals | 4000000 | 45396.00 | 1.62
Welspun Corp Ltd. | INE191B01025 | Industrial Products | 1650000 | 44830.50 | 1.60
Grasim Industries Ltd. | INE047A01021 | Cement & Cement Products | 1450000 | 44397.55 | 1.59
Persistent Systems Ltd. | INE262H01021 | IT - Software | 837138 | 44192.52 | 1.58
The Federal Bank Ltd. | INE171A01029 | Banks | 13750000 | 43642.50 | 1.56
Tech Mahindra Ltd. | INE669C01036 | IT - Software | 2820504 | 42984.48 | 1.54
Axis Bank Ltd. | INE238A01034 | Banks | 3500000 | 42910.00 | 1.53
APL Apollo Tubes Ltd. | INE702C01027 | Industrial Products | 1951028 | 42729.46 | 1.53
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (9 chunks)

**`section_aware:2026-09-30:BSLCBF:0`**: 125 tokens, 2 holding rows, rows 8–9 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Nexus Select Trust | INE0NDH25011 | Realty | 1210418 | 2025.03 | 1.22
Embassy Office Parks Reit | INE041025011 | Realty | 382865 | 1663.24 | 1.00
```

**`section_aware:2026-09-30:BSLCBF:1`**: 478 tokens, 9 holding rows, rows 14–22 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: Debt Instruments
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Debt Instruments > a) Listed/awaiting listing on the stock exchanges]
9.10% SK Finance Ltd. (10/08/2029) ** | INE124N07820 | IND AA- | 9300 | 9156.63 | 5.53
8.73% Eris Lifesciences Ltd. (07/06/2027) ** | INE406M08029 | IND AA | 7400 | 7405.37 | 4.47
Jubilant Bevco Ltd. (31/05/2028) (ZCB) | INE1D4P08019 | CRISIL AA | 6500 | 7311.03 | 4.41
JTPM Metal Traders Ltd. (29/09/2028) (ZCB) ** | INE02PE08036 | CRISIL AA | 5877 | 6342.04 | 3.83
8.45% Adani Airport Holdings Ltd. (12/02/2029) ** | INE0GCN07054 | IND AA- | 6000 | 5939.24 | 3.58
5.00% GMR Airports Ltd. (13/02/2027) ** | INE776C08083 | CRISIL AA- | 5200 | 5523.46 | 3.33
7.46% REC Ltd. (30/06/2028) ** | INE020B08EK4 | ICRA AAA | 5000 | 4980.05 | 3.01
6.66% Small Industries Development Bank of India (25/10/2028) ** | INE556F08KZ3 | CRISIL AAA | 5000 | 4889.67 | 2.95
7.79% Tata Capital Housing Finance Ltd. (18/06/2030) ** | INE033L07IU8 | ICRA AAA | 4467 | 4401.38 | 2.66
```

## hierarchical

### BSLEQTY: ADITYA BIRLA SUN LIFE FLEXI CAP FUND (86 chunks)

**`hierarchical:2026-09-30:BSLEQTY:0`**: 101 tokens, 1 holding rows, parent `hierarchical:2026-09-30:BSLEQTY:p0`, rows 8–8 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: ICICI Bank Ltd. | ISIN: INE090A01021 | Industry/Rating: Banks | Qty: 11849171 | Value (Rs L): 156610.49 | % to AUM: 5.60
```

**`hierarchical:2026-09-30:BSLEQTY:1`**: 101 tokens, 1 holding rows, parent `hierarchical:2026-09-30:BSLEQTY:p0`, rows 9–9 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: HDFC Bank Ltd. | ISIN: INE040A01034 | Industry/Rating: Banks | Qty: 15436415 | Value (Rs L): 109397.87 | % to AUM: 3.91
```

**`hierarchical:2026-09-30:BSLEQTY:p0`** (parent of the first child): 2,750 tokens, 83 holding rows, truncated, rows 8–93 of sheet `BSLEQTY`

```text
Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60
HDFC Bank Ltd. | INE040A01034 | Banks | 15436415 | 109397.87 | 3.91
Kotak Mahindra Bank Ltd. | INE237A01036 | Banks | 23850000 | 99454.50 | 3.55
Reliance Industries Ltd. | INE002A01018 | Petroleum Products | 5706067 | 67731.02 | 2.42
State Bank of India | INE062A01020 | Banks | 6105500 | 58582.27 | 2.09
Infosys Ltd. | INE009A01021 | IT - Software | 5662517 | 56291.08 | 2.01
Sona Blw Precision Forgings Ltd. | INE073K01018 | Auto Components | 6700000 | 55610.00 | 1.99
Bharat Forge Ltd. | INE465A01025 | Auto Components | 2800000 | 53928.00 | 1.93
Lenskart Solutions Ltd. | INE956O01016 | Retailing | 7750000 | 53091.38 | 1.90
Mankind Pharma Ltd. | INE634S01028 | Pharmaceuticals & Biotechnology | 2072385 | 51888.38 | 1.85
United Spirits Ltd. | INE854D01024 | Beverages | 3736609 | 50593.69 | 1.81
HCL Technologies Ltd. | INE860A01027 | IT - Software | 4103703 | 50475.55 | 1.80
Shriram Finance Ltd. | INE721A01047 | Finance | 5000000 | 49135.00 | 1.76
Trent Ltd. | INE849A01020 | Retailing | 1848850 | 48469.45 | 1.73
Hindalco Industries Ltd. | INE038A01020 | Non - Ferrous Metals | 5098639 | 48018.98 | 1.72
... (69 more lines)
```

### BSLCBF: ADITYA BIRLA SUN LIFE CREDIT RISK FUND (57 chunks)

**`hierarchical:2026-09-30:BSLCBF:0`**: 98 tokens, 1 holding rows, parent `hierarchical:2026-09-30:BSLCBF:p0`, rows 8–8 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: Nexus Select Trust | ISIN: INE0NDH25011 | Industry/Rating: Realty | Qty: 1210418 | Value (Rs L): 2025.03 | % to AUM: 1.22
```

**`hierarchical:2026-09-30:BSLCBF:1`**: 98 tokens, 1 holding rows, parent `hierarchical:2026-09-30:BSLCBF:p0`, rows 9–9 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND | As on: 2026-09-30 | Section: Equity & Equity Related | Sub-section: a) Listed/awaiting listing on Stock Exchanges | Instrument: Embassy Office Parks Reit | ISIN: INE041025011 | Industry/Rating: Realty | Qty: 382865 | Value (Rs L): 1663.24 | % to AUM: 1.00
```

**`hierarchical:2026-09-30:BSLCBF:p0`** (parent of the first child): 125 tokens, 2 holding rows, rows 8–9 of sheet `BSLCBF`

```text
Scheme: ADITYA BIRLA SUN LIFE CREDIT RISK FUND
As on: 2026-09-30
Section: Equity & Equity Related
Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
[Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
Nexus Select Trust | INE0NDH25011 | Realty | 1210418 | 2025.03 | 1.22
Embassy Office Parks Reit | INE041025011 | Realty | 382865 | 1663.24 | 1.00
```

