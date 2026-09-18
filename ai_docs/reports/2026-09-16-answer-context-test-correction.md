# Answer-context final assertion correction

Prepared 2026-09-16 without running tests, model calls, benchmarks, Ruff, or compilation during the live timing window.

The parent RED output identified one failing assertion in
`test_skipped_group_does_not_block_later_groups_or_control_citation_order`.
The assertion checked internal citation IDs in serialized QA messages, although
the answer formatter sends title/text pairs. The correction keeps the existing
retrieval-ID and citation-ID assertions unchanged, then directly checks the
final QA message for the ordered `base`, `s`, and `r` title/text fragment and
excludes the 6,001-character oversized original.

Parent focused rerun is pending after live timing.
