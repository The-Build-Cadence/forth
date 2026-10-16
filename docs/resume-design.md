# Resume design

Account instructions live in Settings. An opportunity's non-null instruction override replaces them (an empty override intentionally means no custom instructions). New resumes snapshot the effective instructions and design. Changing Settings does not silently restyle already generated or approved resumes.

Explicit supported visual instructions override AI defaults on both AI and fallback generation. Supported controls are modern/classic/minimal style, single/two-column layout, sans/humanist/serif font, compact/balanced/spacious spacing, six-digit hex accent, Letter/A4 paper, and a one-to-three-page maximum. Freeform instructions still guide the AI's tone and emphasis; they are not arbitrary HTML or CSS.

In Resume Studio, **Apply saved style instructions** resolves the current opportunity/account instructions for an existing resume. Preview changes are read-only. **Save design** changes that version's design, preserves its text/evidence, and clears approval for review. Regenerate is still needed for changes to writing or emphasis. Local designer choices apply to this version, not account defaults.

The authenticated, owner-scoped `/api/resumes/{id}/design/` action returns normalized design, rendered HTML, and the resume. POST accepts `design`, `use_saved_instructions: true`, and `save: true`; omitted save is preview-only. Designer previews and exports share the HTML renderer. The preview is continuous content; PDF pagination happens at export.

Fonts are embedded from bundled, licensed Liberation Sans, Carlito, and Liberation Serif files. Helvetica/Arial requests resolve to Liberation Sans; Aptos/Calibri requests resolve to Carlito. These are disclosed compatible alternatives, not copies of Microsoft's proprietary fonts. Font licenses are included under `backend/core/assets/fonts/`.

PDF exports retain selectable text, headings, links, tags, and document outlines. Two-column flow keeps logical source order, but external ATS parsing varies, so single column remains available. Role blocks are kept together when they fit.

Requested page caps are checked against the actual PDF. If needed, export retries with compact spacing. If the cap still cannot be met, export returns 422 with an explanation; it never drops pages, clips content, or silently delivers an over-limit file. Successful artifact metadata records the actual page count and rendering design. Unavailable PDF rendering continues to produce an explicitly labeled HTML fallback.
