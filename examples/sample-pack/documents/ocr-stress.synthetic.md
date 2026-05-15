# Synthetic OCR Stress Page: Mixed Columns And Broken Labels

> Synthetic sample. Inspired by public document structure, not copied from any source.

## OCR-A1 Repeated Header

Quarterly Sensor Ledger - repeated page header. Quarterly Sensor Ledger - repeated page header.

## OCR-A2 Mixed Column Text

Left column: Sensor Q-17 reports a baseline variance of 0.08. Right column: The Arabic note says "مراجعة يدوية" to indicate manual review.

## OCR-A7 Malformed Reference

Ref: [[SENS--17??]] appears with broken brackets. Ragstudio should flag this as a malformed reference label.

## OCR-B3 Split Row

| Sensor | Expected | Observed |
| --- | ---: | ---: |
| Q-17 | 0.10 | 0.08 |
| Q-18 | 0.10 | missing |

## OCR-C9 Quality Gate Trap

The missing observed value for Q-18 should not be materialized as confident evidence. The row needs manual review before vector indexing.
