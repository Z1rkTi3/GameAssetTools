# Validate and repair

Run `validate <id> --blend <file>`; inspect compact errors/warnings and the report
path. Read only the failing components. Repair the recipe/config or intentional
manual state rather than suppressing validation. Rebuild affected geometry and
rerun the relevant check. Output report replacement needs `--overwrite`.

Errors block GLB export. Warnings identify review decisions such as manual edits,
unapplied scale, hidden content, or missing materials. Validation does not establish
artistic accuracy; use previews for that. Details: `docs/validation.md`.
