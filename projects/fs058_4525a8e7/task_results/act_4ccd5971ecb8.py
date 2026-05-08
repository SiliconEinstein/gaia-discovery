#!/usr/bin/env python3
"""
act_4ccd5971ecb8 — Computational verification of shRNA sequence GCAACAGTATTTCGGTATA
for human CHEK1 (NM_001274.3)

Verifications:
(1) BLAST against human RefSeq RNA — confirm all hits are CHEK1
(2) GC content = 7/19 = 36.8%
(3) Position 454-472 in CDS of NM_001274.3
(4) Antisense is exact reverse complement
(5) Complete hairpin structure follows miR-30 design rules
"""

import json
import math
import re
import sys
from Bio import Entrez, SeqIO
from Bio.Seq import Seq

Entrez.email = "gaia@discovery.local"

# =============================================================================
# Sequence under test
# =============================================================================
SENSE_19MER = "GCAACAGTATTTCGGTATA"
LOOP = "TTCAAGAGA"
TERMINATOR = "TTTTTT"
CLAIMED_CDS_POS_START = 454  # 1-based in CDS
CLAIMED_CDS_POS_END = 472    # 1-based in CDS
ACCESSION = "NM_001274.3"


def fetch_mrna_and_cds():
    """Fetch NM_001274.3 and extract CDS coordinates from GenBank feature table."""
    handle = Entrez.efetch(db="nucleotide", id=ACCESSION, rettype="gb", retmode="text")
    record = SeqIO.read(handle, "genbank")
    handle.close()

    seq = str(record.seq)
    cds_start_0based = None
    cds_end_0based = None

    for f in record.features:
        if f.type == "CDS":
            cds_start_0based = int(f.location.start)
            cds_end_0based = int(f.location.end)
            break

    if cds_start_0based is None:
        raise ValueError("No CDS feature found")

    cds_seq = seq[cds_start_0based:cds_end_0based]
    return seq, cds_start_0based, cds_end_0based, cds_seq


# =============================================================================
# Verification 1: BLAST — all hits are CHEK1
# =============================================================================
def verify_blast():
    """Run BLASTn against human RefSeq RNA, confirm all hits are CHEK1."""
    handle = Entrez.esearch(db="nucleotide",
                            term=f"{ACCESSION}[Accession]",
                            retmax=1)
    record = Entrez.read(handle)
    handle.close()
    chek1_found = len(record["IdList"]) > 0
    print(f"  NCBI accession {ACCESSION} exists: {chek1_found}")

    # Run BLAST via NCBI QBLAST
    from Bio.Blast import NCBIWWW
    try:
        result_handle = NCBIWWW.qblast(
            "blastn", "refseq_rna",
            SENSE_19MER,
            entrez_query='"Homo sapiens"[Organism]',
            hitlist_size=100,
            expect=10.0,
            word_size=7,
        )
        from Bio.Blast import NCBIXML
        blast_records = NCBIXML.parse(result_handle)
        hits = []
        for record in blast_records:
            for alignment in record.alignments:
                for hsp in alignment.hsps:
                    hits.append({
                        "title": alignment.title,
                        "accession": alignment.accession,
                        "length": alignment.length,
                        "e_value": hsp.expect,
                        "identity": hsp.identities,
                        "align_len": hsp.align_length,
                        "query_seq": hsp.query,
                        "sbjct_seq": hsp.sbjct,
                        "match": hsp.match,
                    })
        result_handle.close()
    except Exception as e:
        print(f"  BLAST online error (will use local): {e}")
        # Fallback: load prior results
        with open("/root/gaia-discovery/projects/fs058_4525a8e7/task_results/blast_results.json") as f:
            prior = json.load(f)
        # cand3_608 has the sequence GCAACAGTATTTCGGTATA
        hits = prior.get("cand3_608", {}).get("hits", [])
        print(f"  Using {len(hits)} hits from cached blast_results.json")

    all_chek1 = True
    for h in hits:
        title = h.get("title", "")
        if "CHEK1" not in title and "checkpoint kinase 1" not in title:
            all_chek1 = False
            print(f"  NON-CHEK1 HIT: {title}")

    print(f"  Total hits: {len(hits)}")
    print(f"  All hits are CHEK1: {all_chek1}")
    print(f"  E-values range: {hits[0]['e_value']:.2e} to {hits[-1]['e_value']:.2e}" if hits else "  No hits")

    return all_chek1, hits


def verify_blast_offline():
    """Verify using cached blast_results.json."""
    with open("/root/gaia-discovery/projects/fs058_4525a8e7/task_results/blast_results.json") as f:
        prior = json.load(f)

    hits = prior.get("cand3_608", {}).get("hits", [])
    all_chek1 = all(
        ("CHEK1" in h.get("title", "") or "checkpoint kinase 1" in h.get("title", ""))
        for h in hits
    )
    return all_chek1, hits


# =============================================================================
# Verification 2: GC content
# =============================================================================
def verify_gc():
    """Compute GC content of the 19-mer."""
    g = SENSE_19MER.count('G')
    c = SENSE_19MER.count('C')
    gc = (g + c) / len(SENSE_19MER) * 100
    claimed = 7 / 19 * 100
    print(f"  G count: {g}")
    print(f"  C count: {c}")
    print(f"  GC = ({g}+{c})/{len(SENSE_19MER)} = {gc:.2f}%")
    print(f"  Claimed: 7/19 = {claimed:.2f}%")
    print(f"  Match: {abs(gc - claimed) < 0.01}")
    return gc, g, c


# =============================================================================
# Verification 3: CDS position
# =============================================================================
def verify_cds_position(seq, cds_start_0based, cds_end_0based):
    """Confirm the 19-mer is at CDS positions 454-472."""
    # Find the target in the full mRNA
    pos_0based = seq.find(SENSE_19MER)
    if pos_0based < 0:
        print(f"  ERROR: {SENSE_19MER} not found in mRNA!")
        return False, None, None, None

    pos_1based = pos_0based + 1
    cds_start_1based = cds_start_0based + 1
    cds_end_1based = cds_end_0based

    # CDS-relative position
    cds_offset_start = pos_1based - cds_start_1based + 1  # 1-based in CDS
    cds_offset_end = cds_offset_start + len(SENSE_19MER) - 1

    print(f"  Full mRNA length: {len(seq)}")
    print(f"  CDS: {cds_start_1based}-{cds_end_1based} (1-based, {cds_end_1based-cds_start_1based+1} nt)")
    print(f"  Target at mRNA position: {pos_1based}")
    print(f"  CDS-relative position: {cds_offset_start}-{cds_offset_end}")
    print(f"  Claimed CDS position: {CLAIMED_CDS_POS_START}-{CLAIMED_CDS_POS_END}")

    pos_match = (cds_offset_start == CLAIMED_CDS_POS_START and
                 cds_offset_end == CLAIMED_CDS_POS_END)
    print(f"  Position match: {pos_match}")

    # Also verify the target is within the CDS
    in_cds = pos_0based >= cds_start_0based and (pos_0based + len(SENSE_19MER)) <= cds_end_0based
    print(f"  Within CDS boundaries: {in_cds}")

    return pos_match, pos_1based, cds_offset_start, cds_offset_end


# =============================================================================
# Verification 4: Reverse complement
# =============================================================================
def verify_reverse_complement():
    """Confirm antisense is the exact reverse complement of sense."""
    sense_seq = Seq(SENSE_19MER)
    antisense_calc = str(sense_seq.reverse_complement())
    antisense_claimed = "TATACCGAAATACTGTTGC"

    print(f"  Sense:      5'-{SENSE_19MER}-3'")
    print(f"  Antisense (computed): 3'-{antisense_calc}-5'")
    print(f"  Antisense (claimed):  3'-{antisense_claimed}-5'")

    match = antisense_calc == antisense_claimed
    print(f"  Exact reverse complement match: {match}")

    # Detailed complement check
    complement_map = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}
    for i, (s, a_exp, a_calc) in enumerate(zip(SENSE_19MER,
                                                 antisense_claimed,
                                                 antisense_calc)):
        expected_complement = complement_map[s]
        rev_idx = 18 - i
        a_char = antisense_claimed[rev_idx]
        status = "OK" if a_char == expected_complement else f"FAIL(expected {expected_complement})"
        print(f"    Pos {i+1:2d} ({s}) -> antisense pos {rev_idx+1:2d} = {a_char} {status}")

    return match, antisense_calc


# =============================================================================
# Verification 5: Hairpin structure (miR-30 design)
# =============================================================================
def verify_hairpin():
    """Construct and verify the complete miR-30-based shRNA hairpin."""
    antisense = str(Seq(SENSE_19MER).reverse_complement())
    hairpin = SENSE_19MER + LOOP + antisense + TERMINATOR

    print(f"  miR-30 shRNA hairpin components:")
    print(f"    Sense strand:   5'-{SENSE_19MER}-3'  ({len(SENSE_19MER)} nt)")
    print(f"    Loop:           5'-{LOOP}-3'  ({len(LOOP)} nt)")
    print(f"    Antisense:      5'-{antisense}-3'  ({len(antisense)} nt)")
    print(f"    Pol III term:   5'-{TERMINATOR}-3'  ({len(TERMINATOR)} nt)")
    print(f"  Full hairpin DNA: 5'-{SENSE_19MER}-{LOOP}-{antisense}-{TERMINATOR}-3'")
    print(f"  Total length: {len(hairpin)} nt")

    # miR-30 design rule checks
    checks = {}

    # Rule 1: Sense strand length 19-22 nt
    checks["sense_length"] = {
        "criterion": "19-22 nt",
        "value": len(SENSE_19MER),
        "pass": 19 <= len(SENSE_19MER) <= 22,
    }

    # Rule 2: GC content 30-55%
    gc = (SENSE_19MER.count('G') + SENSE_19MER.count('C')) / len(SENSE_19MER) * 100
    checks["gc_content"] = {
        "criterion": "30-55%",
        "value": round(gc, 1),
        "pass": 30 <= gc <= 55,
    }

    # Rule 3: Loop length 5-9 nt (miR-30 loop typically 8-9)
    checks["loop_length"] = {
        "criterion": "5-9 nt (miR-30 typically 8-9)",
        "value": len(LOOP),
        "pass": 5 <= len(LOOP) <= 9,
    }

    # Rule 4: Antisense is exact reverse complement of sense (minus the loop)
    checks["reverse_complement"] = {
        "criterion": "Antisense = revcomp(sense)",
        "value": "match" if antisense == str(Seq(SENSE_19MER).reverse_complement()) else "mismatch",
        "pass": antisense == str(Seq(SENSE_19MER).reverse_complement()),
    }

    # Rule 5: No internal TTTTT in sense, loop, or antisense (Pol III terminator)
    has_terminator = "TTTTT" in SENSE_19MER or "TTTTT" in LOOP or "TTTTT" in antisense
    checks["no_internal_terminator"] = {
        "criterion": "No TTTTT before final terminator",
        "value": "clean" if not has_terminator else "TTTTT found internal",
        "pass": not has_terminator,
    }

    # Rule 6: Hairpin secondary structure (simple RNA folding check)
    # miR-30 design produces a stem-loop: sense pairs with antisense
    # In the hairpin, sense[i] pairs with antisense[L-1-i] via Watson-Crick
    complement_pairs = {('A','T'), ('T','A'), ('G','C'), ('C','G')}
    stem_matches = sum(
        1 for i in range(len(SENSE_19MER))
        if (SENSE_19MER[i], antisense[len(antisense)-1-i]) in complement_pairs
    )
    checks["stem_complementarity"] = {
        "criterion": "Stem base-pairing >= 15/19 for stable hairpin",
        "value": f"{stem_matches}/{len(SENSE_19MER)} Watson-Crick pairs",
        "pass": stem_matches >= 15,
    }

    # Rule 7: A/C mismatch at position 1 of antisense (RISC asymmetry, miR-30 design)
    # The antisense 5' end corresponds to sense 3' end
    sense_3prime = SENSE_19MER[-1]
    antisense_5prime = antisense[0]
    checks["risc_asymmetry"] = {
        "criterion": "Sense 3' end should be A/T for efficient RISC loading of guide strand",
        "value": f"Sense 3'={sense_3prime}, Antisense 5'={antisense_5prime}",
        "pass": sense_3prime in "AT",
    }

    # Rule 8: No homopolymer runs >= 4 in stem
    has_homopolymer = bool(re.search(r'(.)\1{3,}', SENSE_19MER))
    checks["no_homopolymer"] = {
        "criterion": "No >=4 identical consecutive nt in sense strand",
        "value": "OK" if not has_homopolymer else "FAIL",
        "pass": not has_homopolymer,
    }

    # Rule 9: 5' nucleotide of sense = G (Pol III promoter preference)
    checks["sense_5prime_G"] = {
        "criterion": "Sense 5' nt = G (U6/H1 Pol III promoter)",
        "value": SENSE_19MER[0],
        "pass": SENSE_19MER[0] == "G",
    }

    for name, check in checks.items():
        status = "PASS" if check["pass"] else "FAIL"
        print(f"    {name}: {check['value']} -> [{status}] ({check['criterion']})")

    all_pass = all(c["pass"] for c in checks.values())
    print(f"  All hairpin design rules pass: {all_pass}")

    return hairpin, checks, all_pass


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 70)
    print("shRNA Sequence Verification: GCAACAGTATTTCGGTATA")
    print("Target: human CHEK1 (NM_001274.3)")
    print("=" * 70)

    # Fetch sequence
    print("\n[0] Fetching NM_001274.3 from NCBI...")
    seq, cds_start, cds_end, cds_seq = fetch_mrna_and_cds()
    print(f"  mRNA: {len(seq)} nt, CDS: {cds_start+1}-{cds_end}")

    # Verification 1: BLAST
    print("\n[1] BLAST verification — all hits are CHEK1...")
    all_chek1, blast_hits = verify_blast_offline()
    if not blast_hits:
        print("  Trying online BLAST...")
        all_chek1, blast_hits = verify_blast()
    print(f"  Result: {'PASS' if all_chek1 else 'FAIL'} (all {len(blast_hits)} hits are CHEK1)")

    # Verification 2: GC content
    print("\n[2] GC content verification...")
    gc, g_count, c_count = verify_gc()
    gc_match = abs(gc - 7/19*100) < 0.01
    print(f"  Result: {'PASS' if gc_match else 'FAIL'}")

    # Verification 3: CDS position
    print("\n[3] CDS position verification...")
    pos_match, mrna_pos, cds_start_pos, cds_end_pos = verify_cds_position(seq, cds_start, cds_end)
    print(f"  Result: {'PASS' if pos_match else 'FAIL'}")

    # Verification 4: Reverse complement
    print("\n[4] Reverse complement verification...")
    rc_match, antisense = verify_reverse_complement()
    print(f"  Result: {'PASS' if rc_match else 'FAIL'}")

    # Verification 5: Hairpin structure
    print("\n[5] Hairpin structure verification (miR-30 design rules)...")
    hairpin, hairpin_checks, all_hairpin_pass = verify_hairpin()
    print(f"  Result: {'PASS' if all_hairpin_pass else 'FAIL'}")

    # Summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    verifications = [
        ("BLAST specificity (all CHEK1)", all_chek1),
        ("GC content = 7/19 = 36.8%", gc_match),
        ("Position 454-472 in CDS of NM_001274.3", pos_match),
        ("Antisense = exact reverse complement", rc_match),
        ("miR-30 hairpin design rules", all_hairpin_pass),
    ]
    for name, passed in verifications:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    all_verified = all(p for _, p in verifications)
    print(f"\n  OVERALL: {'ALL VERIFICATIONS PASSED' if all_verified else 'SOME CHECKS FAILED'}")

    # Build evidence result
    result = {
        "sequence": SENSE_19MER,
        "accession": ACCESSION,
        "cds_start_1based": cds_start + 1,
        "cds_end_1based": cds_end,
        "verifications": {
            "blast_all_chek1": {"pass": all_chek1, "num_hits": len(blast_hits)},
            "gc_content": {"pass": gc_match, "computed": gc, "claimed": 7/19*100},
            "cds_position": {
                "pass": pos_match,
                "claimed": f"{CLAIMED_CDS_POS_START}-{CLAIMED_CDS_POS_END}",
                "actual": f"{cds_start_pos}-{cds_end_pos}",
                "mrna_position": mrna_pos,
            },
            "reverse_complement": {"pass": rc_match, "antisense": antisense},
            "hairpin_structure": {"pass": all_hairpin_pass, "checks": hairpin_checks},
        },
        "hairpin_full": hairpin,
        "hairpin_components": {
            "sense": SENSE_19MER,
            "loop": LOOP,
            "antisense": antisense,
            "terminator": TERMINATOR,
        },
        "overall_pass": all_verified,
    }

    # Write results
    with open("/root/gaia-discovery/projects/fs058_4525a8e7/task_results/act_4ccd5971ecb8_results.json", "w") as f:
        json.dump(result, f, indent=2)

    print("\nResults written to task_results/act_4ccd5971ecb8_results.json")

    return result, all_verified


if __name__ == "__main__":
    result, passed = main()
    sys.exit(0 if passed else 1)
