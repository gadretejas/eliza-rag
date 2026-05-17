# System Prompt Upgrade Plan

## Status: Implemented

The system prompt has been updated (currently at v4). The brevity instruction has been removed, depth/structure rules have been added, and a data context block (corpus coverage summary) was prepended. A separate follow-up system prompt (`prompts/followup_system_prompt.md`) was also created for multi-turn chat sessions. See `docs/system_prompt_change_history.md` for the full version history.

---

## Problem

The current answer output is correct and well-cited but too brief. For a financial analyst tool, users expect depth: specific numbers, segment breakdowns, year-over-year trends, and caveats — not just a one-sentence answer with citations.

Example: the query `"What are Apple's main revenue segments?"` returned a single sentence naming the five geographic segments, with no revenue figures, no breakdown percentages, and no trend context — even though that data was present in the retrieved chunks.

**Root cause**: Rule 8 in `prompts/system_prompt.md` instructs the model to "keep answers concise", which overrides everything else. The model has the right chunks; it is just told to be brief.

---

## Three Levers

### Lever 1 — System prompt (highest impact, free, reversible)

The system prompt is the primary constraint. Changes:

- **Remove** "keep answers concise" from Rule 8
- **Replace** with: be thorough but avoid padding — every sentence should add information not already stated
- **Add** explicit instruction to include specific numbers, percentages, and dollar figures when present in sources
- **Add** instruction to surface trends when multiple filing years are retrieved (e.g. "revenue grew from $X in 2022 to $Y in 2024")
- **Add** a soft response structure:
  1. Direct answer (one sentence)
  2. Breakdown by segment, product line, or category with figures
  3. Notable trends or year-over-year changes
  4. Caveats or gaps in the source coverage

This lever alone should close most of the quality gap since the retrieval is already returning the right chunks.

### Lever 2 — Chunk size (medium impact, no cost change)

`max_chunk_chars` in `AnswerConfig` is set to 2000, which truncates longer passages mid-sentence. The Apple query retrieved 15 chunks but only cited 3 — the model may have skipped truncated chunks that contained the relevant numbers.

- Increase `max_chunk_chars` from 2000 → 3000
- Consider also increasing `top_k` from 15 → 20 for broad questions that span multiple sections or years

### Lever 3 — Model upgrade (low effort, higher cost)

`gpt-5.4-mini` is fast and cheap but produces shorter, more compressed answers. Switching to `gpt-5.4` with the same context and prompt would produce noticeably richer synthesis at roughly 3× the per-query cost (~$0.008 → ~$0.026).

This is worth considering for production but should only be evaluated after Lever 1 is applied — the model is not the bottleneck right now, the instructions are.

---

## Recommended Sequence

1. **Update the system prompt** — remove the brevity instruction, add depth and structure guidance
2. **Test on 3–5 representative queries** across different question types (segment breakdown, risk factors, multi-company comparison, time-specific metric)
3. **If answers are still shallow on number-heavy questions**, increase `max_chunk_chars` to 3000
4. **If synthesis quality is insufficient after both**, evaluate `gpt-5.4`

---

## Success Criteria

A good answer to `"What are Apple's main revenue segments?"` should include:
- All five geographic segments named
- Revenue figures for each segment (at least the most recent year)
- Which segment is largest and by how much
- Any notable trend (e.g. Greater China declining, Services growing)
- Which filing(s) the data comes from
