from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER = ROOT / "tools" / "p0-b0" / "materialize_p0_b0.py"
FINALIZE = ROOT / ".github" / "workflows" / "finalize-p0-b0.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"patch point not found: {label}")
    return text.replace(old, new, 1)


text = MATERIALIZER.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''            raw = intact.read_bytes()
            output.write_bytes(raw[: max(32, len(raw) // 3)])
            return
''',
    '''            # A positive 6.1 smoke case must be unambiguously unreadable across
            # qpdf, pikepdf and PDFium. Recoverable truncation belongs in the boundary queue.
            output.write_bytes(b"%PDF-1.7\\n1 0 obj\\n<< /Type /Catalog\\n")
            return
''',
    "6.1 deterministic unreadable fixture",
)

text = replace_once(
    text,
    '''        "counts": {
            "official_rules": 26,
            "case_recipes": 130,
            "smoke_pdfs": 28,
            "object_self_checks_passed": 28,
            "pdfium_expected_outcomes_passed": 28,
            "qpdf_expected_outcomes_passed": 28,
            "reproducible_hashes": 28,
            "official_validator_observations": 0,
        },
''',
    '''        "counts": {
            "official_rules": 26,
            "case_recipes": 130,
            "smoke_pdfs": 28,
            "object_self_checks_passed": 28,
            "pdfium_expected_outcomes_passed": 28,
            "qpdf_expected_outcomes_passed": 28,
            "fixture_reproducibility_checks": 28,
            "ordinary_pdf_exact_byte_checks": 26,
            "encrypted_pdf_canonical_semantic_checks": 2,
            "official_validator_observations": 0,
        },
''',
    "static gate reproducibility counts",
)

text = replace_once(
    text,
    '''    write_json(OUT_TESTS / "REPRODUCIBILITY_REPORT.json", {
        "status": "PASS_LOCAL_BASELINE",
        "files_compared": 28,
        "hash_differences": 0,
        "determinism_controls": ["ReportLab invariant mode", "pikepdf deterministic_id", "stable filenames", "no timestamps in generated metadata"],
    })
''',
    '''    write_json(OUT_TESTS / "REPRODUCIBILITY_REPORT.json", {
        "status": "POLICY_DEFINED_AND_CI_EXECUTED",
        "fixtures_checked": 28,
        "ordinary_pdf_policy": "exact SHA-256 equality across independent generations",
        "encrypted_pdf_policy": "decrypt with fixture credential, save a static-ID unencrypted canonical copy, then compare SHA-256",
        "ordinary_pdf_cases": 26,
        "encrypted_pdf_cases": ["CDE-PDF-6-19-POS.pdf", "CDE-PDF-6-21-POS.pdf"],
        "reason": "AES encryption may legitimately use random file keys, salts or IVs. Raw-byte inequality is not semantic fixture drift.",
        "determinism_controls": ["ReportLab invariant mode", "pikepdf deterministic_id for ordinary PDFs", "stable filenames", "no current timestamps in generated metadata"],
    })
''',
    "tracked reproducibility report",
)

old_run_all = r'''    names=sorted(p.name for p in BUILD.glob("*.pdf")); assert len(names)==28
    diffs=[]
    for name in names:
        h1=hashlib.sha256((BUILD/name).read_bytes()).hexdigest(); h2=hashlib.sha256((BUILD2/name).read_bytes()).hexdigest()
        if h1!=h2: diffs.append(name)
    if diffs: raise AssertionError(f"non-deterministic PDFs: {diffs}")
    report={"status":"PASS","rules":26,"case_recipes":130,"smoke":28,"self_check":28,"pdfium":28,"qpdf":28,"reproducible":28,"official_observations":0,"official_status":"NOT_RUN"}
'''
new_run_all = r'''    # Re-run object assertions on the independently generated set before comparing.
    run(TEST/"validators"/"self_check_smoke.py","--manifest",TEST/"smoke_manifest.json","--input",BUILD2)
    names=sorted(p.name for p in BUILD.glob("*.pdf")); assert len(names)==28
    encrypted_passwords={"CDE-PDF-6-19-POS.pdf":"","CDE-PDF-6-21-POS.pdf":"user-password"}
    exact_byte_passed=0; canonical_semantic_passed=0; diffs=[]
    def canonical_decrypted_hash(path,password):
        import tempfile
        import pikepdf
        with tempfile.TemporaryDirectory(prefix="ezctd-canonical-") as td:
            canonical=Path(td)/"canonical.pdf"
            with pikepdf.open(path,password=password) as pdf:
                pdf.save(canonical,encryption=False,static_id=True)
            return hashlib.sha256(canonical.read_bytes()).hexdigest()
    for name in names:
        first=BUILD/name; second=BUILD2/name
        h1=hashlib.sha256(first.read_bytes()).hexdigest(); h2=hashlib.sha256(second.read_bytes()).hexdigest()
        if name in encrypted_passwords:
            c1=canonical_decrypted_hash(first,encrypted_passwords[name]); c2=canonical_decrypted_hash(second,encrypted_passwords[name])
            if c1!=c2: diffs.append({"file":name,"mode":"canonical-decrypted","first":c1,"second":c2})
            else: canonical_semantic_passed+=1
        elif h1!=h2:
            diffs.append({"file":name,"mode":"exact-byte","first":h1,"second":h2})
        else:
            exact_byte_passed+=1
    if diffs: raise AssertionError(f"fixture reproducibility failures: {diffs}")
    assert exact_byte_passed+canonical_semantic_passed==28
    report={"status":"PASS","rules":26,"case_recipes":130,"smoke":28,"self_check":28,"pdfium":28,"qpdf":28,"fixture_reproducibility":28,"exact_byte_reproducibility":exact_byte_passed,"encrypted_canonical_semantic_reproducibility":canonical_semantic_passed,"official_observations":0,"official_status":"NOT_RUN"}
'''
text = replace_once(text, old_run_all, new_run_all, "run_all reproducibility policy")

MATERIALIZER.write_text(text, encoding="utf-8", newline="\n")

if FINALIZE.exists():
    workflow = FINALIZE.read_text(encoding="utf-8")
    workflow = workflow.replace(
        "- Deterministic regeneration hashes: 28/28",
        "- Fixture reproducibility: 28/28 (exact-byte for ordinary PDFs; decrypted canonical equivalence for encrypted PDFs)",
    )
    FINALIZE.write_text(workflow, encoding="utf-8", newline="\n")

print("P0-B0 materializer v2 repairs applied")
