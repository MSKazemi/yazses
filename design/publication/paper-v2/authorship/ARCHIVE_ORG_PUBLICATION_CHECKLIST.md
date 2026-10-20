# Internet Archive publication checklist — YazSes paper v2

Use this checklist only after the authorship protocol reports APPROVED_FOR_PUBLICATION.

The approved manuscript must not be altered during upload preparation.

## 1. Pre-upload identity checks

- [ ] Aggregate approval state is APPROVED_FOR_PUBLICATION.
- [ ] Frozen source commit is recorded.
- [ ] Final PDF SHA-256 is recorded.
- [ ] Final ordered byline is recorded.
- [ ] All authors approved the same fingerprint.
- [ ] No unresolved review request exists.
- [ ] No withdrawal has been received.
- [ ] The PDF being prepared for upload hashes to the approved SHA-256.
- [ ] The title exactly matches the approved title.

If any checkbox fails, stop.

## 2. Prepare publication-safe metadata

Prepare these fields from the approved package:

- Title
- Creator/author names in approved order
- Publication date
- Description/abstract
- Subject/keywords
- Language
- License/rights statement
- Project repository landing page
- Version label, if used
- Related identifier for the first paper, if appropriate
- Source commit / software version in description or notes, if approved
- Contact/corresponding-author information only where the person consented to making it public

Do not expose private coordination emails merely because Internet Archive offers a creator/contact field.

## 3. File package

Recommended publication package:

- approved final PDF;
- optional manuscript source archive if all included material is intended for publication and contains no private data;
- optional machine-readable citation metadata;
- optional reproducibility README referring to public repository artifacts.

Before upload:

- [ ] inspect every file name;
- [ ] inspect archives for accidental private files;
- [ ] confirm no private consent registry is included;
- [ ] confirm no private email list is included;
- [ ] confirm no credentials, tokens, local paths, or hidden files are included;
- [ ] record SHA-256 for each uploaded project-supplied file.

Repository policy note: the project does not commit PDFs to Git. The approved PDF should be generated/distributed outside the repository and identified by hash in the approval record.

## 4. Upload

During item creation:

- [ ] use the exact approved title;
- [ ] enter creator names in the exact approved order;
- [ ] use the approved description/abstract;
- [ ] use the approved license statement;
- [ ] upload the exact approved PDF;
- [ ] avoid replacing the PDF with a regenerated copy after approvals, even if visually identical;
- [ ] record the Internet Archive item identifier.

If the site transforms or derives additional files automatically, treat those as platform-generated derivatives. The uploaded project-supplied original remains the authoritative approved file.

## 5. Immediate post-upload verification

Open the resulting item and verify:

- [ ] landing page resolves;
- [ ] title is correct;
- [ ] all creator names are present;
- [ ] creator order is correct;
- [ ] abstract/description is correct;
- [ ] license/rights are correct;
- [ ] the intended PDF is downloadable;
- [ ] downloaded original matches the approved SHA-256, where technically possible;
- [ ] no unintended private file is visible;
- [ ] no author metadata was altered accidentally;
- [ ] repository/project link is correct.

If a manuscript/byline error is found, do not silently substitute a changed paper without author review. Correct the publication through a versioned process and repeat approval where manuscript content changed.

## 6. Repository follow-up

After successful publication:

- [ ] add the Internet Archive landing-page identifier/link to the appropriate paper-v2 publication record;
- [ ] record publication date;
- [ ] record final PDF SHA-256;
- [ ] record the source commit;
- [ ] update citation metadata only if it remains truthful and does not overwrite the citation for the first paper incorrectly;
- [ ] preserve the first paper's arXiv identifier as a separate related work;
- [ ] send the publication-completed message to all authors.

Do not replace the existing CITATION.cff preferred citation for the first paper until the project explicitly decides which work is the preferred citation. A second paper can be recorded without erasing the first.

## 7. Correction/version procedure

For any post-publication scientific or byline correction:

1. create a corrected manuscript;
2. create a new source commit;
3. generate a new PDF;
4. compute a new SHA-256;
5. describe the change;
6. send the corrected version to every author;
7. obtain unanimous approval of the new fingerprint;
8. publish a new version / clearly corrected item while preserving the prior record;
9. update repository metadata;
10. notify all authors.

Typographical metadata corrections on the archive landing page that do not alter the manuscript should still be logged, especially if they involve author names.

## 8. Final publication record template

~~~text
Paper: YazSes paper v2
Status: PUBLISHED
Internet Archive identifier:
Internet Archive landing page:
Publication date:
Approved source commit:
Evidence cutoff:
Approved PDF filename:
Approved PDF SHA-256:
Final author count:
Final roster digest:
Final approval round:
Final unanimous approval completed at:
Uploaded/verified by:
Notes:
~~~

This record should contain publication-safe information only.
