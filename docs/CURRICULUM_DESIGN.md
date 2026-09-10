# Curriculum structure and authoring decisions

## Implemented content path

`fluent_ai/curriculum.py` loads packaged JSON assets for Spanish, French, and Hindi. `pyproject.toml` includes `curriculum/*.json` in the Python package. The loader caches parsed assets and returns copies so callers cannot mutate shared content.

The public helpers are `lesson_bank(language)`, `topics_by_level(language)`, `conversation_ladder(language)`, and `topic_lesson(language, level, topic)`. Lessons and conversations consume these helpers instead of requiring content to live in Python literals.

## Asset contract

Each language asset has `language`, `schema_version`, `levels`, and `generic`. A level declares `topic_order`, `topics`, and `default_topic`; it may also declare conversation entries directly. Topic records contain:

- `title` and `focus_skill`;
- target/English `vocabulary` and `examples`, with optional romanization and pronunciation hints;
- a grammar explanation and exact quiz `answers`;
- optional `pronunciation_hints`, `cultural_note`, and conversation prompts with topic, complexity, opening, support, and keywords.

Stable topic keys support persisted mastery/review records. Aliases bridge older names such as `vocabulary` to newer content keys. The loader converts rich vocabulary/examples into the pair format used by lesson generation while retaining rich records for script and pronunciation display.

## Lookup and quality boundaries

`topic_lesson` tries the language bank's exact topic, its alias, the level default, then generic content. If generic content is absent it can try the Spanish bank for legacy compatibility, otherwise returns `None`. Unknown language files resolve to Spanish. These are compatibility rules, not evidence of broad multilingual course coverage.

Preserve accents and Devanagari in authored/displayed content; write JSON as UTF-8. Hindi material should keep romanization aligned with native text. Matching normalization must not erase meaningful script characters. Provide enough vocabulary/examples and correct answer keys for deterministic quiz generation; test every declared topic and level after content edits.

OpenAI enhances the selected lesson at runtime, including available pronunciation/culture context. Static banks remain useful scaffolding and test fixtures, while real lessons still require OpenAI. Native-language content review and deeper Hindi/French/advanced coverage remain in the [roadmap](FLUENTAI_LIMITLESS_IDEAL.md).

`tests/test_curriculum.py` covers asset/loader behavior. Also run the full suite and mocked smoke, and verify installed-package loading when changing package data.
