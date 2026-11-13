# Gold answers

Computed by `src/eval/gold.py` from `holdings.parquet` (no LLM). Regenerate with `python -m src.eval gold`.

| Id | Type | Question | Gold answer | Rows used |
|---|---|---|---|---|
| Q01 | lookup | What % of AUM does Aditya Birla Sun Life Flexi Cap Fund hold in ICICI Bank Ltd. as on 30 Sep 2026? | 5.5967 % | 1 |
| Q02 | lookup | What % of AUM does Aditya Birla Sun Life Large Cap Fund hold in Infosys Ltd. as on 30 Sep 2026? | 3.2030 % | 1 |
| Q03 | lookup | What % of AUM does Aditya Birla Sun Life Small Cap Fund hold in TD Power Systems Ltd. as on 30 Sep 2026? | 3.3895 % | 1 |
| Q04 | lookup | What is the market value, in Rs lakhs, of The Federal Bank Ltd. held by Aditya Birla Sun Life Midcap Fund as on 30 Sep 2026? | 19,880.41 Rs lakhs | 1 |
| Q05 | lookup | What % of AUM does Aditya Birla Sun Life Digital India Fund hold in Tech Mahindra Ltd. as on 30 Sep 2026? | 7.8505 % | 1 |
| Q06 | lookup | What is the market value, in Rs lakhs, of Swiggy Ltd. held by Aditya Birla Sun Life Value Fund as on 30 Sep 2026? | 22,644.84 Rs lakhs | 1 |
| Q07 | lookup | What % of AUM does Aditya Birla Sun Life Medium to Long Term Fund hold in the 7.17% Tata Capital Housing Finance Ltd. bond maturing 21/05/2030, as on 30 Sep 2026? | 4.1819 % | 1 |
| Q08 | aggregation | What is the total % of AUM in equity holdings of the Banks industry for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026? | 19.2399 % | 7 |
| Q09 | aggregation | What is the total % of AUM in equity holdings of the IT - Software industry for Aditya Birla Sun Life Digital India Fund as on 30 Sep 2026? | 57.0053 % | 19 |
| Q10 | aggregation | What share of AUM do the top 5 equity holdings (by % of AUM) of Aditya Birla Sun Life Large Cap Fund make up together, as on 30 Sep 2026? | 27.4111 % | 5 |
| Q11 | aggregation | What share of AUM do the top 3 equity holdings (by % of AUM) of Aditya Birla Sun Life Midcap Fund make up together, as on 30 Sep 2026? | 9.0417 % | 3 |
| Q12 | aggregation | How many holdings are listed in the Equity & Equity Related section of Aditya Birla Sun Life Large Cap Fund as on 30 Sep 2026? | 71 | 71 |
| Q13 | aggregation | How many holdings are listed in the Equity & Equity Related section of Aditya Birla Sun Life Focused Fund as on 30 Sep 2026? | 29 | 29 |
| Q14 | aggregation | What is the total % of AUM in the Equity & Equity Related section of Aditya Birla Sun Life Aggressive Hybrid Fund as on 30 Sep 2026? | 76.1833 % | 82 |
| Q15 | debt | What % of AUM of Aditya Birla Sun Life Medium to Long Term Fund is rated AAA by any agency (CRISIL, ICRA, CARE or IND; not counting securitised AAA(SO) ratings) as on 30 Sep 2026? | 32.4157 % | 18 |
| Q16 | debt | What is the total % of AUM in Government Securities (the Government Securities sub-section of Debt Instruments) for Aditya Birla Sun Life Medium to Long Term Fund as on 30 Sep 2026? | 59.6873 % | 42 |
| Q17 | debt | List all holdings of Aditya Birla Sun Life Short Term Fund rated CARE AAA as on 30 Sep 2026. | 6 item(s): 6.80% National Housing Bank (02/04/2032) **; 7.00% Small Industries Development Bank of India (04/06/2029) (FRN) **; 7.23% Housing and Urban Development Corporation Ltd. (18/07/2029) **; 8.07% SMFG India Home Finance Co. Ltd. (10/09/2027) **; 8.75% Bharti Telecom Ltd. (05/11/2029); 7.29% National Housing Bank (04/07/2031) ** | 6 |
| Q18 | debt | List all holdings of Aditya Birla Sun Life Credit Risk Fund rated IND AA- as on 30 Sep 2026. | 3 item(s): 9.10% SK Finance Ltd. (10/08/2029) **; 8.45% Adani Airport Holdings Ltd. (12/02/2029) **; 8.50% IKF Finance Ltd. (10/03/2028) ** | 3 |
| Q19 | debt | What % of AUM of Aditya Birla Sun Life Medium Term Fund is rated AA- by any agency (CRISIL, ICRA, CARE or IND) as on 30 Sep 2026? | 15.4205 % | 11 |
| Q20 | cross_scheme | Which holds more Infosys Ltd. as a % of AUM as on 30 Sep 2026: Aditya Birla Sun Life Flexi Cap Fund or Aditya Birla Sun Life Large Cap Fund? | BSLFEF (Large Cap) | 2 |
| Q21 | cross_scheme | Which holds more HDFC Bank Ltd. as a % of AUM as on 30 Sep 2026: Aditya Birla Sun Life Flexi Cap Fund or Aditya Birla Sun Life Value Fund? | PURE (Value Fund) | 2 |
| Q22 | cross_scheme | Which holds a larger market value (Rs lakhs) of Reliance Industries Ltd. as on 30 Sep 2026: Aditya Birla Sun Life Focused Fund or Aditya Birla Sun Life Large Cap Fund? | BSLFEF (Large Cap) | 2 |
| Q23 | cross_scheme | How many equity holdings (same company in the Equity & Equity Related section) do Aditya Birla Sun Life Flexi Cap Fund and Aditya Birla Sun Life Large & Mid Cap Fund have in common as on 30 Sep 2026? | 29 | 58 |
| Q24 | cross_scheme | How many equity holdings (same company in the Equity & Equity Related section) do Aditya Birla Sun Life Large Cap Fund and Aditya Birla Sun Life Focused Fund have in common as on 30 Sep 2026? | 21 | 42 |
| Q25 | unanswerable | What is the expense ratio of Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026? | not in the data | 0 |
| Q26 | unanswerable | Who is the fund manager of Aditya Birla Sun Life Small Cap Fund as on 30 Sep 2026? | not in the data | 0 |
| Q27 | unanswerable | What was the NAV per unit of Aditya Birla Sun Life Large Cap Fund on 30 Sep 2026? | not in the data | 0 |
| Q28 | unanswerable | What was the 1-year return of Aditya Birla Sun Life Midcap Fund as on 30 Sep 2026? | not in the data | 0 |
