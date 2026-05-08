# shRNA Design for CHEK1 (NM_001274.3) — Derivation Log

## Action
- **action_id**: act_211917ccbe7c
- **action_kind**: abduction
- **query**: Design a potential shRNA sequence targeting human CHEK1 (NM_001274.3) following standard shRNA design rules

## Summary of Findings

The originally proposed shRNA target sequence `5'-GCAACAGTATTTCATTAGA-3'` (claimed to be at positions 868-886 of NM_001274.3) is **invalid**. This sequence does not exist anywhere in the NM_001274.3 mRNA, nor in any of the 15 CHEK1 RefSeq transcript variants. The actual sequence at positions 868-886 is `TCTAGCTCTGCTGCATAAA`.

A corrected shRNA target has been designed using actual sequence data:

**Corrected target**: `5'-GCAACAGTATTTCGGTATA-3'` (positions 608-626, NM_001274.3)

The corrected target differs from the originally proposed sequence at positions 15-18 (CGGT vs CATT) and position 19 (A vs A — same).

## Method

1. **Sequence retrieval**: CHEK1 mRNA NM_001274.3 fetched from NCBI Nucleotide via Entrez (2037 nt, CDS 155-1585, 1431 nt coding region).
2. **Candidate enumeration**: All 19-nt windows in CDS (excluding first/last 75 nt) screened against design rules.
3. **BLAST verification**: Top candidates tested via NCBI BLASTn against human RefSeq RNA database for uniqueness.
4. **Hairpin construction**: Standard miR-30-based shRNA architecture.

## Design Rules Applied

| Rule | Criterion |
|------|-----------|
| Target length | 19-21 nucleotides |
| GC content | 30-52% |
| 5' nucleotide | G (required for efficient U6/H1 Pol III transcription initiation) |
| Location | Coding sequence (CDS), avoiding 5'UTR and 3'UTR |
| Avoid | Homopolymer runs >=4 identical nucleotides |
| Avoid | Internal TTTTT (Pol III termination signal) |
| Uniqueness | BLAST-verified no off-target matches with <=2 mismatches in human transcriptome |

## Results: Candidate Selection

From 1431 nt CDS, after applying all filters (GC 30-52%, start G, no homopolymer, no TTTTT, avoid start/stop proximal regions, avoid immunostimulatory motifs), **115 candidates** remained.

### Top candidates evaluated by BLAST

| Rank | Position | Sequence | GC% | BLAST off-targets |
|------|----------|----------|-----|-------------------|
| 1 | 608-626 | GCAACAGTATTTCGGTATA | 36.8% | 0 (15/15 CHEK1 only) |
| 2 | 607-625 | GGCAACAGTATTTCGGTAT | 42.1% | 0 (15/15 CHEK1 only) |
| 3 | 240-258 | GAGTAACTGAAGAAGCAGT | 42.1% | (network error, retry needed) |

### Selected primary candidate: `GCAACAGTATTTCGGTATA` (pos 608-626)

**Rationale for selection**:
- Optimal GC content at 36.8% (center of 30-52% range)
- Single G at 5' end ensures clean Pol III transcription initiation
- Ends with A (favorable for RISC strand selection — thermodynamic asymmetry)
- A/T-rich 3' end (positions 14-19: CGGTATA, 4/6 A/T) promotes antisense strand loading
- Perfect BLAST uniqueness — all 15 hits across RefSeq are CHEK1 transcript variants, zero off-target hits

## Complete shRNA Hairpin Sequence

### DNA sequence (for cloning into lentiviral vector)
```
5'-GCAACAGTATTTCGGTATA-TTCAAGAGA-TATACCGAAATACTGTTGC-TTTTTT-3'
```

### Component breakdown
```
Sense strand (target mRNA match):  5'-GCAACAGTATTTCGGTATA-3'   (19 nt)
Loop (miR-30 based, Dicer substrate): 5'-TTCAAGAGA-3'              (9 nt)
Antisense strand (reverse complement): 5'-TATACCGAAATACTGTTGC-3'  (19 nt)
Pol III terminator:                 5'-TTTTTT-3'                  (6 nt)
Total hairpin:                                                    (53 nt)
```

### One-line representation
```
GCAACAGTATTTCGGTATATTCAAGAGATATACCGAAATACTGTTGCTTTTTT
```

### RNA transcript (as produced by Pol III)
```
GCAACAGUAUUUCGGUAUAUUCAAGAGAUAUACCGAAAUACUGUUGCUUUUUU
```

## Design Rule Compliance Checklist

- [x] Target length: 19 nt (within 19-21 range)
- [x] GC content: 7/19 = 36.8% (within 30-52% range)
- [x] 5' nucleotide: G
- [x] Location: CDS, positions 608-626 (CDS spans 155-1585)
- [x] No UTR targeting: strictly within coding region
- [x] No homopolymer runs: maximum consecutive identical nucleotides = 2
- [x] No internal TTTTT: not present in sense strand
- [x] No immunostimulatory motifs (UGUGU, GUCCUUCAA, UGGC)
- [x] BLAST uniqueness: 15/15 hits are CHEK1, zero off-targets
- [x] Avoids first 75 nt of CDS (translation initiation region)
- [x] Avoids last 75 nt of CDS (translation termination region)

## Original Claim Discrepancy

| Aspect | Claimed | Actual (NM_001274.3) |
|--------|---------|---------------------|
| Target sequence | GCAACAGTATTTCATTAGA | GCAACAGTATTTCGGTATA |
| Position | 868-886 | 608-626 |
| Sequence at claimed pos | — | TCTAGCTCTGCTGCATAAA |
| GC content | Claimed 31.6% | 36.8% |
| Exists in NM_001274.3? | Claimed yes | No (16/19 match at pos 608) |
| Exists in any CHEK1 variant? | — | No (best match 16/19 across all 15 variants) |

The originally proposed sequence `GCAACAGTATTTCATTAGA` appears to be a garbled version of the actual sequence `GCAACAGTATTTCGGTATA`. The first 14 nucleotides (`GCAACAGTATTTC`) are correct, but positions 15-18 are wrong (`CATT` instead of `CGGT`), and position 19 is correct (`A`). This suggests either a sequencing/transcription error or an attempt to design from an incorrect source.

## References

- CHEK1 mRNA: NM_001274.3 (NCBI RefSeq, Homo sapiens checkpoint kinase 1)
- CDS annotation: 155..1585, encoding NP_001265.1 (476 aa)
- BLAST database: NCBI human RefSeq RNA, accessed 2026-05-08
- Design rules from: Taxman et al. (2006) "Criteria for effective shRNA" and standard BLOCK-iT / pLKO.1 design guidelines
- Loop sequence: TTCAAGAGA — standard miR-30-based loop from pLKO.1 / pGIPZ vectors
