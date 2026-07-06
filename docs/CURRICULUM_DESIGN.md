# FluentAI Curriculum Depth Design

## Scope

This document designs Phase 5 curriculum depth without changing runtime code yet. It is grounded in commit `5a43138`, because other agents may be editing `fluent_ai/agent.py` and `fluent_ai/conversation.py` concurrently.

North-star references:

- Lesson Mode should generate level-aware lessons with useful phrases, grammar, examples, pronunciation notes, cultural context, micro-tasks, quizzes, and a speaking bridge.
- Multilingual support should prioritize quality: CEFR mapping, topic ladders, grammar progression, pronunciation guidance, cultural context, script support, romanization, native examples, and conversation scenarios.
- Personalization should adapt topic choice to goals, weak topics, conversation mistakes, and prior outcomes.
- Phase 5 explicitly calls for richer Spanish, French, and Hindi lessons, CEFR progression, custom goals, scenarios, debate, and work modules.

Current code references at `5a43138`:

- `fluent_ai/agent.py:TOPICS_BY_LEVEL` defines Spanish-centric topic names for A1-C2.
- `fluent_ai/agent.py:LESSON_BANK` contains six hand-written Spanish topics, mostly A1.
- `fluent_ai/agent.py:generate_lesson` uses `LESSON_BANK` only for Spanish and `_generic_lesson_bank` for non-Spanish languages.
- `fluent_ai/agent.py:generate_quiz` uses static `answers` for Spanish bank lessons and `_lesson_driven_quiz` for OpenAI or non-Spanish lessons.
- `fluent_ai/agent.py:_lesson_driven_quiz` needs at least two vocabulary pairs and two example pairs to create stable questions.
- `fluent_ai/agent.py:_generic_lesson_bank` provides one generic Hindi lesson, one generic French lesson, and one generic other-language fallback.
- `fluent_ai/conversation.py:TOPIC_LADDER` contains Spanish A1-C2 conversation topics.
- `fluent_ai/conversation.py:LANGUAGE_TOPIC_OVERRIDES` contains French and Hindi A1-A2 overrides only.
- `fluent_ai/conversation.py:conversation_topics_for` chooses language override by level, otherwise Spanish `TOPIC_LADDER`.
- `fluent_ai/openai_provider.py:OpenAIProvider.enhance_lesson` rewrites lesson vocabulary, grammar, examples, and micro-task at runtime.

## Part 1: Content Architecture

Move curriculum data out of Python literals and into JSON files:

```text
fluent_ai/
  curriculum.py
  curriculum/
    spanish.json
    french.json
    hindi.json
```

`fluent_ai/curriculum.py` should be the only runtime loader. JSON files should be static content assets with no code execution.

The first implementation should preserve the current dict shapes so `fluent_ai/agent.py:generate_lesson`, `fluent_ai/agent.py:generate_quiz`, and `fluent_ai/conversation.py:conversation_topics_for` can be migrated with minimal logic changes.

### JSON Schema

Each language file should use this top-level shape:

```json
{
  "language": "Spanish",
  "schema_version": 1,
  "levels": {
    "A1": {
      "topic_order": ["introductions"],
      "topics": {
        "introductions": {
          "title": "Greetings and introductions",
          "focus_skill": "vocabulary",
          "vocabulary": [{"target": "Me llamo", "english": "My name is", "romanization": null, "pronunciation_hint": "meh YAH-moh"}],
          "grammar": "Use ser for identity and origin.",
          "examples": [{"target": "Me llamo Ana.", "english": "My name is Ana.", "romanization": null}],
          "answers": {"mc": "My name is", "fill_prompt": "___ Ana.", "fill": "Me llamo", "open": "Me llamo Ana.", "translation": "Soy de Singapur."},
          "pronunciation_hints": ["ll in llamo is usually like y in many dialects."],
          "cultural_note": "Use mucho gusto in many first-meeting situations.",
          "conversation": [{"topic": "introductions", "complexity": "beginner", "opening": "Hola, yo empiezo. ¿Cómo te llamas?", "support": "Model answer: Me llamo Ana.", "keywords": ["me", "llamo", "soy"]}]
        }
      },
      "default_topic": "introductions"
    }
  },
  "generic": {"topic": "practice", "focus_skill": "vocabulary", "vocabulary": [], "grammar": "", "examples": [], "answers": {}, "conversation": []}
}
```

Required topic fields:

- `title`: display label, not used as the stable key.
- `focus_skill`: one of the current skill names such as `vocabulary`, `grammar`, `conjugations`, `listening`, `speaking`, `reading`, or `translation`.
- `vocabulary`: at least five target-English pairs; Hindi items should include `romanization`.
- `grammar`: short level-appropriate explanation, compatible with `grammar_explanation` in generated lessons.
- `examples`: at least three target-English pairs; Hindi examples should include `romanization`.
- `answers`: exact answer keys for the static quiz path.
- `pronunciation_hints`: optional list, but strongly recommended for every topic.
- `cultural_note`: optional string.
- `conversation`: one or more entries shaped exactly like current conversation ladder entries: `topic`, `complexity`, `opening`, `support`, `keywords`.

Compatibility transforms in `fluent_ai/curriculum.py`:

- Convert JSON `vocabulary` objects into current `[(target, english), ...]` tuples or tuple-compatible lists.
- Convert JSON `examples` objects into current `[(target, english), ...]` tuples or tuple-compatible lists.
- Preserve `answers` as the same dict shape used by `fluent_ai/agent.py:generate_quiz`.
- Attach richer optional fields to lesson banks as `pronunciation_hints`, `cultural_note`, and `romanization`, without requiring existing code to consume them immediately.
- Keep `topic_order` as the source for `topics_by_level(language)`.
- Keep conversation entries shaped for `fluent_ai/conversation.py:conversation_topics_for`.

### Loader API

Add `fluent_ai/curriculum.py` with:

```python
def lesson_bank(language: str) -> dict[str, dict[str, Any]]:
    ...

def topics_by_level(language: str) -> dict[str, list[str]]:
    ...

def conversation_ladder(language: str) -> dict[str, list[dict[str, Any]]]:
    ...

def topic_lesson(language: str, level: str, topic: str) -> dict[str, Any]:
    ...
```

The fallback chain should be:

1. Exact language + exact topic.
2. Exact language + level `default_topic`.
3. Exact language + `generic`.
4. Spanish exact topic, for legacy topic-score compatibility when the user has Spanish-coded weak topics.
5. Existing `_generic_lesson_bank(language, topic)` until the generic literals are fully deleted.

Spanish zero-behavior-change migration:

- `TOPICS_BY_LEVEL` maps to `topics_by_level("Spanish")`.
- `LESSON_BANK` maps to `lesson_bank("Spanish")`.
- `TOPIC_LADDER` maps to `conversation_ladder("Spanish")`.
- `LANGUAGE_TOPIC_OVERRIDES["French"]` and `LANGUAGE_TOPIC_OVERRIDES["Hindi"]` map to `conversation_ladder("French")` and `conversation_ladder("Hindi")`.
- `_generic_lesson_bank` remains as the last fallback during migration, then becomes content in `generic`.

The initial Spanish extraction should preserve current strings exactly, including current missing accents, so existing tests can prove zero behavior change. A later content-depth package should replace user-facing Spanish with correct accents and diacritics.

### OpenAI Enhancement Interaction

`fluent_ai/openai_provider.py:OpenAIProvider.enhance_lesson` currently receives topic, focus skill, duration, reason, weak topics, goals, and returns richer vocabulary, grammar, examples, and micro-task.

With richer base curriculum:

- The lesson passed to `enhance_lesson` should include `pronunciation_hints` and `cultural_note` when present.
- The prompt should ask the model to preserve those hints unless it can make them more level-appropriate.
- For Hindi, the prompt should include Devanagari plus `romanization` and ask for both to remain aligned.
- Better base lessons give the model stronger grounding and reduce generic rewrites for French and Hindi.

Suggested prompt extension:

```text
Base pronunciation hints:
- ...

Base cultural note:
- ...

For Hindi, preserve Devanagari and romanization alignment.
Return pronunciation_hints and cultural_note when useful.
```

The JSON response can later add `pronunciation_hints` and `cultural_note`, but the first loader implementation can simply pass these through from the base lesson if the provider does not return replacements.

### Accent and Unicode Policy

New content should use proper accents and diacritics: `café`, `mañana`, `¿Cómo?`, `j'étudie`, `बाज़ार`.

Verified current behavior:

- `fluent_ai/state.py:save_state` writes JSON with `ensure_ascii=False`, so progress and stored evidence can preserve non-ASCII text.
- `fluent_ai/conversation.py:normalize` strips combining marks through Unicode NFKD normalization, so conversation keyword matching is accent-insensitive.
- `fluent_ai/agent.py:normalize` lowercases and strips punctuation, but does not strip accents. Therefore quiz grading is not fully accent-insensitive today.

Implementation should not claim the evaluator already normalizes accents everywhere. It should add an accent-normalization round-trip test and either update `fluent_ai/agent.py:normalize` to match `conversation.normalize` or keep quiz answer keys and acceptable answers explicitly accent-aware.

## Part 2: Actual Content Plan

Authoring should happen in JSON implementation files, not inline in this design doc. Content must be native-quality, accent-correct, and level-appropriate.

Use stable topic slugs across languages wherever possible so weak-topic mapping, mistake-topic mapping, reviews, and progress history can transfer across Spanish, French, and Hindi.

### Topic Slug Set

Core A1-A2 slugs for parity:

- `introductions`
- `cafe_orders`
- `daily_routines`
- `numbers_time`
- `directions_travel`
- `shopping`
- `weather`
- `family`
- `work_basics`
- `likes_food`
- `past_tense`
- `conjugations`
- `core_vocabulary`

B1 slugs:

- `opinions`
- `storytelling`
- `future_plans`
- `work_and_goals`
- `news_summaries`

Legacy alias handling:

- Map current `cafe orders` to `cafe_orders`.
- Map current `travel plans` to `directions_travel` or `future_plans` depending on level.
- Map current `vocabulary` to `core_vocabulary`.
- Map current `likes and food` to `likes_food`.
- Map current `workplace situations` to `work_and_goals`.
- Keep aliases readable in the loader so old `data/progress.json` topic scores still resolve.

### Topic Tables

Spanish should reach full A1-B1 depth first. French and Hindi should get full A1-A2 lesson parity with Spanish A1-A2, plus A1-B1 conversation ladders.

| Language | Level | Topic slugs with focus_skill |
|---|---:|---|
| Spanish | A1 | `introductions`/vocabulary, `cafe_orders`/speaking, `likes_food`/vocabulary, `numbers_time`/vocabulary, `weather`/listening, `family`/vocabulary |
| Spanish | A2 | `daily_routines`/grammar, `conjugations`/conjugations, `past_tense`/conjugations, `directions_travel`/speaking, `shopping`/speaking, `work_basics`/vocabulary, `core_vocabulary`/vocabulary |
| Spanish | B1 | `opinions`/speaking, `storytelling`/grammar, `future_plans`/grammar, `work_and_goals`/speaking, `news_summaries`/reading |
| French | A1 | `introductions`/vocabulary, `cafe_orders`/speaking, `likes_food`/vocabulary, `numbers_time`/vocabulary, `weather`/listening, `family`/vocabulary |
| French | A2 | `daily_routines`/grammar, `conjugations`/conjugations, `past_tense`/conjugations, `directions_travel`/speaking, `shopping`/speaking, `work_basics`/vocabulary, `core_vocabulary`/vocabulary |
| French | B1 conversation | `opinions`/speaking, `storytelling`/speaking, `future_plans`/speaking |
| Hindi | A1 | `introductions`/vocabulary, `cafe_orders`/speaking, `likes_food`/vocabulary, `numbers_time`/vocabulary, `weather`/listening, `family`/vocabulary |
| Hindi | A2 | `daily_routines`/grammar, `conjugations`/conjugations, `past_tense`/conjugations, `directions_travel`/speaking, `shopping`/speaking, `work_basics`/vocabulary, `core_vocabulary`/vocabulary |
| Hindi | B1 conversation | `opinions`/speaking, `storytelling`/speaking, `future_plans`/speaking |

French B1 and Hindi B1 can start as conversation-only entries in the first parity package, then receive full lesson banks after Spanish B1 and A1-A2 parity are stable.

### Worked Example: Spanish B1 Topic

```json
{
  "title": "Giving opinions with reasons",
  "focus_skill": "speaking",
  "vocabulary": [
    {"target": "creo que", "english": "I think that", "pronunciation_hint": "KREH-oh keh"},
    {"target": "desde mi punto de vista", "english": "from my point of view"},
    {"target": "por un lado", "english": "on one hand"},
    {"target": "sin embargo", "english": "however"},
    {"target": "vale la pena", "english": "it is worth it"}
  ],
  "grammar": "Use creo que plus an indicative verb for a clear opinion, then add porque plus one concrete reason.",
  "examples": [
    {"target": "Creo que las conversaciones ayudan mucho porque son reales.", "english": "I think conversations help a lot because they are real."},
    {"target": "Desde mi punto de vista, vale la pena practicar todos los días.", "english": "From my point of view, it is worth practicing every day."},
    {"target": "Por un lado es difícil; sin embargo, aprendo más rápido.", "english": "On one hand it is difficult; however, I learn faster."}
  ],
  "answers": {
    "mc": "I think that",
    "fill_prompt": "___ las conversaciones ayudan mucho.",
    "fill": "Creo que",
    "open": "Creo que practicar todos los días ayuda mucho.",
    "translation": "Desde mi punto de vista, vale la pena practicar."
  },
  "pronunciation_hints": [
    "Keep que short: keh, not kway.",
    "In rápido, stress the first syllable: RÁ-pi-do."
  ],
  "cultural_note": "In many Spanish-speaking contexts, softening an opinion with creo que can sound more conversational than a blunt statement.",
  "conversation": [
    {
      "topic": "opinions",
      "complexity": "intermediate",
      "opening": "Empecemos con una opinión. ¿Prefieres aprender con música, videos o conversaciones? ¿Por qué?",
      "support": "Give one opinion and one reason with porque.",
      "keywords": ["creo", "prefiero", "porque", "sin embargo", "vale"]
    }
  ]
}
```

### Worked Example: Hindi A1 Topic

```json
{
  "title": "Greetings and introductions",
  "focus_skill": "vocabulary",
  "vocabulary": [
    {"target": "नमस्ते", "english": "hello", "romanization": "namaste", "pronunciation_hint": "nuh-muh-STAY"},
    {"target": "मेरा नाम", "english": "my name", "romanization": "mera naam"},
    {"target": "आपका नाम क्या है?", "english": "What is your name?", "romanization": "aapka naam kya hai?"},
    {"target": "मैं ... से हूँ", "english": "I am from ...", "romanization": "main ... se hoon"},
    {"target": "मुझे खुशी हुई", "english": "Nice to meet you", "romanization": "mujhe khushi hui"}
  ],
  "grammar": "Use मेरा नाम ... है for 'my name is ...'. Use आपका for a polite 'your'.",
  "examples": [
    {"target": "नमस्ते, मेरा नाम आना है।", "english": "Hello, my name is Ana.", "romanization": "namaste, mera naam Ana hai."},
    {"target": "आपका नाम क्या है?", "english": "What is your name?", "romanization": "aapka naam kya hai?"},
    {"target": "मैं सिंगापुर से हूँ।", "english": "I am from Singapore.", "romanization": "main Singapore se hoon."}
  ],
  "answers": {
    "mc": "hello",
    "fill_prompt": "___, मेरा नाम आना है।",
    "fill": "नमस्ते",
    "open": "मेरा नाम आना है।",
    "translation": "मैं सिंगापुर से हूँ।"
  },
  "pronunciation_hints": [
    "हूँ is nasalized: hoon.",
    "Keep long आ in नाम longer than a short अ."
  ],
  "cultural_note": "नमस्ते is widely understood and polite; with strangers, prefer आप over तुम.",
  "conversation": [
    {
      "topic": "introductions",
      "complexity": "beginner",
      "opening": "नमस्ते, मैं शुरू करता हूँ। आपका नाम क्या है?",
      "support": "Model answer: मेरा नाम आना है।",
      "keywords": ["मेरा", "नाम", "है", "नमस्ते"]
    }
  ]
}
```

### Quiz Answer-Key Requirements

Every lesson topic must include:

- `answers.mc`: English meaning for the first or most important vocabulary item.
- `answers.fill_prompt`: target-language prompt containing `___`.
- `answers.fill`: exact target-language fill answer.
- `answers.open`: one short target-language model answer.
- `answers.translation`: one target-language sentence for translation/reuse prompts.

For `_lesson_driven_quiz` compatibility:

- At least five vocabulary pairs.
- At least three examples.
- First vocabulary pair must be a stable, beginner-readable pair.
- First example must be a natural sentence with an English meaning.
- Open-ended answers should include clear keywords, especially in Hindi where tokenization may be less forgiving.

## Part 3: Sequenced Implementation Plan

### Work Package A: Loader and Spanish Extraction

Goal: move current Spanish literals into data files with zero behavior change.

- Changes: add `fluent_ai/curriculum.py`; add `fluent_ai/curriculum/spanish.json` from current `TOPICS_BY_LEVEL`, `LESSON_BANK`, and `TOPIC_LADDER`; wire `fluent_ai/agent.py:TOPICS_BY_LEVEL`, `LESSON_BANK`, and `fluent_ai/conversation.py:TOPIC_LADDER` through loader outputs; leave `_generic_lesson_bank` as last fallback.
- Tests: Spanish schema validation; snapshot/equality test against commit `5a43138`; every Spanish topic loadable by level; `generate_quiz` works for every extracted topic; existing tests still pass.
- Acceptance: `npm run check` green, with manual diff confirming no user-facing Spanish behavior changed.

### Work Package B: Spanish A2/B1 Depth and French A1-A2

Goal: add real depth without changing Lesson Mode orchestration.

- Changes: add accent-correct Spanish A1 replacements after zero-diff tests; add Spanish A2/B1 banks; add `fluent_ai/curriculum/french.json` with A1-A2 lesson parity and A1-B1 conversation ladders; extend aliases; update `OpenAIProvider.enhance_lesson` prompt with pronunciation hints and cultural note.
- Tests: Spanish/French schema validation; every declared topic loadable; quiz generatable for every topic/level/language; French A1-B1 ladder loadable; accent normalization round-trip for Spanish and French.
- Acceptance: `npm run check` green; demo rotates Spanish B1 opinions/storytelling/future plans; French A1-A2 no longer falls back to one generic lesson for every topic.

### Work Package C: Hindi A1-A2 and Script Support

Goal: make Hindi first-class for beginner lessons while preserving Devanagari.

- Changes: add `fluent_ai/curriculum/hindi.json` with Devanagari, romanization, pronunciation hints, and A1-A2 parity; add Hindi A1-B1 conversation ladders; preserve `romanization` metadata while returning tuple-compatible lesson fields; file a sequenced renderer follow-up for an optional transliteration toggle.
- Tests: Hindi schema validation requiring `romanization`; every Hindi A1-A2 topic loadable; quiz generatable for every Hindi topic; Devanagari keyword matching works; diacritic test covers Devanagari preservation, not ASCII-only conversion.
- Acceptance: `npm run check` green; Hindi no longer uses the same generic bank for every topic; demo can expose Devanagari plus romanization data to the renderer.

## Stopping Conditions

Stop implementation if:

- Loader migration changes Spanish behavior before a zero-diff test exists.
- JSON content cannot generate quizzes for every declared topic.
- Hindi romanization is missing or mismatched with Devanagari examples.
- A package would require editing concurrent Python changes without rereading the latest files.

The correct path is additive curriculum data first, runtime wiring second, UI rendering last.
