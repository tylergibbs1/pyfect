- `pyfect.ai.openai.generated` and `pyfect.ai.openrouter.generated` (schemas, `types` and
  generated clients) follow Effect 4.1.5's `Generated.ts`; OpenAI followed 4.1.4's and
  OpenRouter 4.1.2's. OpenAI keeps every name. OpenRouter renames 34 schemas (with their types)
  and 150 nested types, removes 208 schemas (187 of them Effect's numbered names such as
  `Objects_17`) and 514 nested types, and adds 1,173 schemas and 85 client methods. Integer
  fields are typed `int` instead of `float`, and OpenRouter's `ChatToolCall.id` and
  `ChatStreamToolCall.index` are `NotRequired` (read them with `.get(...)`). The full list,
  old name → new name, is on [AI providers in 0.7.0](https://pyfect.dev/docs/ai-providers-migration),
  made by `scripts/ai_generated_migration.py`; for example `CompletedEvent` →
  `StreamEventsResponseCompleted` and `BaseRefusalDeltaEvent` → `RefusalDeltaEvent`.
  `openrouter.language_model.ConfigService` takes 4.1.5's request options (`deferred_tools`,
  the new plugins and service tiers).
