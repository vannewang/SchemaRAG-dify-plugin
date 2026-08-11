## [ERR-20260811-001] apply_patch_anchor_mismatch

**Logged**: 2026-08-11T11:55:00+08:00
**Priority**: low
**Status**: resolved
**Area**: docs

### Summary
README documentation patch used a table-row anchor whose spacing did not match the file.

### Error
```
apply_patch verification failed: Failed to find expected lines in README_CN.md
```

### Context
- Operation: append SQL memory tool documentation to the root READMEs.
- No file was modified because patch verification failed before application.

### Suggested Fix
Use stable Markdown headings or nearby section separators as patch anchors instead of aligned table whitespace.

### Metadata
- Reproducible: yes
- Related Files: README.md, README_CN.md

### Resolution
- **Resolved**: 2026-08-11T11:55:00+08:00
- **Notes**: Retry with section-heading anchors.

---
